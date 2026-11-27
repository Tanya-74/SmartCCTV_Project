"""One-click demo with screen recording (Windows). Normally started by run_demo.bat.

    .venv\\Scripts\\python.exe scripts\\run_demo.py                    # full demo
    ... run_demo.py --live-seconds 20                                 # shorter live part
    ... run_demo.py --mode upload                                     # upload part only
    ... run_demo.py --no-screen-record                                # force the browser-only recording

Starts the fake RTSP camera and the web server (each in a minimised window), records the
screen with the ffmpeg that ships with imageio-ffmpeg, runs scripts/demo_playwright.py,
then finalises the video and stops only what this script started.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
OUT = ROOT / "demo_recordings"
VIDEO = ROOT / "data" / "videos" / "Assault001_x264.mp4"
RTSP_PORT = 8554
FPS = 20

LOG = None


def say(msg: str):
    line = f"[launcher] {msg}"
    print(line, flush=True)
    log(line)


def log(line: str):
    if LOG:
        LOG.write(line + "\n")
        LOG.flush()


# ---------------------------------------------------------------- windows helpers
def screen_layout() -> tuple[str, str]:
    """Browser on the left, this console on the right. Returns both windows as
    'x,y,w,h' in physical screen pixels."""
    u = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        u.SetProcessDPIAware()
    area = wintypes.RECT()
    u.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA
    w, h = area.right - area.left, area.bottom - area.top
    bw = int(w * 0.64)
    browser = (area.left, area.top, bw, h)
    console = (area.left + bw, area.top, w - bw, h)
    return ",".join(map(str, browser)), ",".join(map(str, console))


def place_console(rect: str):
    k, u = ctypes.windll.kernel32, ctypes.windll.user32
    k.GetConsoleWindow.restype = wintypes.HWND
    hwnd = k.GetConsoleWindow()
    if not hwnd:
        return
    x, y, w, h = map(int, rect.split(","))
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [wintypes.UINT]
    u.ShowWindow(hwnd, 9)                                       # restore if minimised or maximised
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)                                   # a process's first call can be ignored
    u.SetWindowPos(hwnd, wintypes.HWND(-1), x, y, w, h, 0x0040)  # always on top while the demo runs
    # turn off "QuickEdit": otherwise an accidental click in the console freezes the demo
    k.GetStdHandle.restype = wintypes.HANDLE
    handle = k.GetStdHandle(-10)
    mode = wintypes.DWORD()
    if k.GetConsoleMode(handle, ctypes.byref(mode)):
        k.SetConsoleMode(handle, (mode.value & ~0x0040) | 0x0080)


def keep_on_top(browser_rect: str, console_rect: str):
    """While recording: if the demo browser or this console gets minimised, covered or moved,
    put it back (without taking keyboard focus away from whatever you are doing)."""
    k, u = ctypes.windll.kernel32, ctypes.windll.user32
    k.GetConsoleWindow.restype = wintypes.HWND
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [wintypes.UINT]
    windows = [(k.GetConsoleWindow(), console_rect)]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        title = ctypes.create_unicode_buffer(300)
        u.GetWindowTextW(hwnd, title, 300)
        if title.value.startswith("Smart CCTV - automated demo") and u.IsWindowVisible(hwnd):
            windows.append((hwnd, browser_rect))
        return True

    u.EnumWindows(visit, 0)
    for hwnd, rect in windows:
        if not hwnd:
            continue
        if u.IsIconic(hwnd) or u.IsZoomed(hwnd):
            u.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        x, y, w, h = map(int, rect.split(","))
        u.SetWindowPos(hwnd, wintypes.HWND(-1), x, y, w, h, 0x0010 | 0x0040)  # no-activate


def start_minimised(args: list[str]) -> subprocess.Popen:
    """Run a command in its own minimised classic console window."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7  # SW_SHOWMINNOACTIVE
    return subprocess.Popen(["conhost.exe", *args], cwd=ROOT, startupinfo=si,
                            creationflags=subprocess.CREATE_NEW_CONSOLE)


def kill_tree(proc: subprocess.Popen | None, name: str):
    if proc is None:
        return
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    say(f"Stopped the {name}.")


# ---------------------------------------------------------------- network helpers
def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def port_free(port: int) -> bool:
    if port_open(port):
        return False
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def server_ready(base: str) -> bool:
    try:
        with urllib.request.urlopen(base + "/status", timeout=3) as r:
            return "total_alerts" in json.loads(r.read())
    except Exception:
        return False


# ---------------------------------------------------------------- recording
def grab_args(ffmpeg: str) -> list[str]:
    return [ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
            "-f", "gdigrab", "-framerate", str(FPS), "-draw_mouse", "1", "-i", "desktop"]


def screen_capture_works(ffmpeg: str) -> str | None:
    """Grab one second of the screen. Returns None if fine, else the error text."""
    test = OUT / "_capture_test.mp4"
    try:
        r = subprocess.run(grab_args(ffmpeg) + ["-t", "1", "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2",
                                                "-c:v", "libx264", "-preset", "ultrafast",
                                                "-pix_fmt", "yuv420p", str(test)],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and test.exists() and test.stat().st_size > 1000:
            return None
        return (r.stderr or "empty output").strip()[-300:]
    except Exception as e:
        return str(e)
    finally:
        test.unlink(missing_ok=True)


def start_recording(ffmpeg: str, target: Path):
    err = open(OUT / "ffmpeg_last.log", "w")
    proc = subprocess.Popen(
        grab_args(ffmpeg) + ["-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264",
                             "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                             "-movflags", "+faststart", str(target)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    time.sleep(2)
    return proc if proc.poll() is None else None


def stop_recording(proc: subprocess.Popen):
    """Send 'q' so ffmpeg writes the MP4 index and the file is playable."""
    if proc.poll() is not None:
        say("The recorder had already stopped on its own - see demo_recordings\\ffmpeg_last.log")
        return
    say("Stopping the screen recording and finalising the video...")
    try:
        proc.stdin.write(b"q")
        proc.stdin.flush()
        proc.stdin.close()
        proc.wait(timeout=120)
    except Exception as e:
        say(f"ffmpeg did not stop cleanly ({e}); forcing it to close.")
        proc.kill()


def video_duration(ffmpeg: str, path: Path) -> str | None:
    """Decode the whole file. Returns its duration text if it is playable."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path), "-f", "null", "-"],
                       capture_output=True, text=True, errors="replace", timeout=600)
    if r.returncode != 0:
        return None
    for line in r.stderr.splitlines():
        if "Duration:" in line:
            d = line.split("Duration:")[1].split(",")[0].strip()
            if d != "N/A":
                return d
    times = [p.split()[0] for p in r.stderr.split("time=")[1:]]
    return times[-1] if times else None


# ---------------------------------------------------------------- main
def main() -> int:
    global LOG
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["both", "upload", "live"], default="both")
    ap.add_argument("--slow-mo", type=int, default=700)
    ap.add_argument("--live-seconds", type=int, default=90)
    ap.add_argument("--upload-timeout", type=int, default=300)
    ap.add_argument("--end-seconds", type=int, default=6, help="hold the finished dashboard this long")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--no-screen-record", action="store_true", help="use the browser-only recording")
    ap.add_argument("--no-open", action="store_true", help="do not open the recordings folder at the end")
    a = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")
    if not VIDEO.exists():
        print(f"Sample video not found: {VIDEO}")
        return 1
    try:
        import imageio_ffmpeg
        import playwright  # noqa: F401
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        print(f"A required package is missing in .venv ({e}). Run: .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        return 1

    OUT.mkdir(exist_ok=True)
    LOG = open(OUT / "last_run.log", "w", encoding="utf-8")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    began = time.time()
    camera = server = recorder = demo = None
    release = OUT / "_demo_ready"
    release.unlink(missing_ok=True)
    result, demo_rc = None, 1

    browser_rect, console_rect = screen_layout()
    place_console(console_rect)

    try:
        # 1. fake camera
        if a.mode != "upload":
            if port_open(RTSP_PORT):
                say(f"Something is already serving port {RTSP_PORT} (a fake camera you started?). Using it, and leaving it running.")
            else:
                say("Starting the fake camera (minimised window)...")
                camera = start_minimised([sys.executable, str(SCRIPTS / "simulate_rtsp.py"), str(VIDEO)])
                for _ in range(120):
                    if port_open(RTSP_PORT) or camera.poll() is not None:
                        break
                    time.sleep(0.5)
                time.sleep(3)  # give ffmpeg a moment to start publishing
                if camera.poll() is not None or not port_open(RTSP_PORT):
                    say("The fake camera failed to start. To see why, run:  "
                        ".venv\\Scripts\\python.exe scripts\\simulate_rtsp.py data\\videos\\Assault001_x264.mp4")
                    return 1
                say("Fake camera is running.")

        # 2. web server
        port = a.port
        while not port_free(port):
            say(f"Port {port} is busy, trying {port + 1}.")
            port += 1
            if port > a.port + 50:
                say("No free port found.")
                return 1
        base = f"http://127.0.0.1:{port}"
        say(f"Starting the web server on port {port} (minimised window)...")
        server = start_minimised([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)])
        for _ in range(180):
            if server_ready(base):
                break
            if server.poll() is not None:
                break
            time.sleep(1)
        if not server_ready(base):
            say(f"The server did not respond. To see why, run:  .venv\\Scripts\\python.exe -m uvicorn main:app --port {port}")
            return 1
        say(f"Server is responding at {base}")

        # 3. recording
        place_console(console_rect)  # again: opening the background windows can minimise this one
        time.sleep(1)
        mp4 = OUT / f"demo_{stamp}.mp4"
        webm = OUT / f"demo_{stamp}_browser.webm"
        if a.no_screen_record:
            say("Screen recording switched off: recording the browser page only.")
        else:
            problem = screen_capture_works(ffmpeg)
            if problem is None:
                recorder = start_recording(ffmpeg, mp4)
                problem = None if recorder else "the recorder exited immediately (see ffmpeg_last.log)"
            if problem:
                say(f"Screen recording does not work here: {problem}")
                say("Falling back to recording the browser page only.")
            else:
                say(f"Recording the full screen to {mp4.name}")
        result = mp4 if recorder else webm

        # 4. the demo
        cmd = [sys.executable, "-u", str(SCRIPTS / "demo_playwright.py"),
               "--base-url", base, "--mode", a.mode, "--video", str(VIDEO),
               "--slow-mo", str(a.slow_mo), "--live-seconds", str(a.live_seconds),
               "--upload-timeout", str(a.upload_timeout), "--end-seconds", str(a.end_seconds),
               "--window", browser_rect, "--ready-file", str(release)]
        if not recorder:
            cmd += ["--record-video", str(webm)]
        demo = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                env=dict(os.environ, PYTHONIOENCODING="utf-8"))

        def forward():
            for line in demo.stdout:
                print(line, end="", flush=True)
                log(line.rstrip())

        pump = threading.Thread(target=forward, daemon=True)
        pump.start()
        while demo.poll() is None:
            if release.exists():          # final dashboard has been held on screen
                if recorder:
                    stop_recording(recorder)
                    recorder = None
                release.unlink(missing_ok=True)  # lets the demo close the browser
            if recorder:
                keep_on_top(browser_rect, console_rect)
            time.sleep(0.5)
        pump.join(timeout=10)
        demo_rc = demo.returncode
        if demo_rc != 0:
            say(f"The demo script ended with an error (code {demo_rc}); see the lines above.")
    except KeyboardInterrupt:
        say("Interrupted - cleaning up.")
    finally:
        if recorder:
            stop_recording(recorder)
        if demo is not None and demo.poll() is None:
            kill_tree(demo, "demo browser")
        release.unlink(missing_ok=True)
        kill_tree(camera, "fake camera")
        kill_tree(server, "web server")

    # 5. check the video
    took = time.time() - began
    say(f"Total run time: {int(took // 60)} min {int(took % 60)} s")
    if result is None or not result.exists() or result.stat().st_size == 0:
        say("NO VIDEO was produced. See demo_recordings\\last_run.log and ffmpeg_last.log")
        return 1
    length = video_duration(ffmpeg, result)
    if not length:
        say(f"The video file exists but could not be decoded: {result}")
        return 1
    say(f"Video saved ({result.stat().st_size / 1e6:.1f} MB, length {length}):")
    say(f"   {result}")
    if not a.no_open:
        os.startfile(OUT)
    return demo_rc


if __name__ == "__main__":
    sys.exit(main())

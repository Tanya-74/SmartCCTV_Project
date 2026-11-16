"""Visible-browser demo of the Smart CCTV dashboard.

    python scripts/demo_playwright.py                 # both demos
    python scripts/demo_playwright.py --mode upload   # only the file-upload demo
    python scripts/demo_playwright.py --mode live     # only the RTSP live demo

Before the live demo, the fake camera must be running (separate terminal):
    python scripts/simulate_rtsp.py data/videos/Assault001_x264.mp4
The server is started automatically if it is not already running.
"""
from __future__ import annotations
import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).resolve().parent.parent
RTSP_URL = "rtsp://127.0.0.1:8554/cam1"


def say(msg: str):
    print(f"[demo] {msg}", flush=True)


# ---------------------------------------------------------------- server handling
def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def is_our_app(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=3) as r:
            return "total_alerts" in json.loads(r.read())
    except Exception:
        return False


def ensure_server() -> tuple[str, subprocess.Popen | None]:
    """Reuse the app if it is already running; otherwise start it (port 8000, or 8001 if 8000 is busy)."""
    for port in (8000, 8001):
        if is_our_app(port):
            say(f"Smart CCTV server is already running on port {port} - using it.")
            return f"http://127.0.0.1:{port}", None
    port = 8000 if not port_open(8000) else 8001
    if port_open(port):
        sys.exit(f"Ports 8000 and 8001 are both used by other programs. Free one and retry.")
    if port == 8001:
        say("Port 8000 is busy with another program, so I will use port 8001.")
    say(f"Starting the Smart CCTV server on port {port} (loading the AI model takes a few seconds)...")
    log = open(ROOT / "data" / "demo_server.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
                            cwd=ROOT, stdout=log, stderr=log)
    for _ in range(90):
        if proc.poll() is not None:
            sys.exit("The server stopped unexpectedly - see data/demo_server.log")
        if is_our_app(port):
            say("Server is up.")
            return f"http://127.0.0.1:{port}", proc
        time.sleep(1)
    proc.terminate()
    sys.exit("Server did not start within 90 seconds - see data/demo_server.log")


# ---------------------------------------------------------------- helpers
def api(page, base: str, path: str):
    r = page.request.get(base + path)
    return r.json()


def job_by_id(page, base: str, job_id: str) -> dict | None:
    return next((j for j in api(page, base, "/status")["jobs"] if j["id"] == job_id), None)


def show_alerts(page, new_count: int):
    cards = page.locator("#feed .card")
    for i in range(min(new_count, cards.count(), 3)):
        c = cards.nth(i)
        badge = c.locator(".badge").inner_text()
        sev = c.locator("b").first.inner_text()
        text = c.locator(".body > div").nth(1).inner_text()
        say(f"   alert card: {badge}, {sev} - {text[:110]}")


def pause(page, seconds: float):
    page.wait_for_timeout(int(seconds * 1000))


# ---------------------------------------------------------------- demo 1: upload
def demo_upload(page, base: str, video: Path, timeout_s: int):
    say("=== DEMO 1: analysing an uploaded video file ===")
    before = page.locator("#feed .card").count()
    say(f"Choosing the video file '{video.name}' in the upload box...")
    page.set_input_files("#file", str(video))
    say("Keeping the restricted zone on 'default' (the red area on the picture).")
    page.select_option("#zone", "default")
    say("Clicking 'Upload & analyse' - the server will now detect people, track them, "
        "and ask Gemini about every zone breach.")
    with page.expect_response(lambda r: r.url.endswith("/upload") and r.request.method == "POST") as resp:
        page.click("#btn")
    job_id = resp.value.json()["job_id"]
    say(f"Upload accepted (job {job_id}). Watching the progress bar in 'Processing status'...")
    page.locator("#jobs").scroll_into_view_if_needed()

    start, last = time.time(), None
    while time.time() - start < timeout_s:
        j = job_by_id(page, base, job_id)
        if j:
            line = (f"   {j['status']}: {j['progress']}% - {j['breaches']} zone breach(es), "
                    f"{j['breaches_classified']} analysed by Gemini, {j['alerts_created']} alert(s)")
            if line != last:
                say(line)
                last = line
            if j["status"] in ("done", "error"):
                break
        time.sleep(2)
    else:
        say("Timed out waiting for the video to finish - continuing anyway.")
        return
    if j["status"] == "error":
        say(f"The job ended with an error: {j['errors'][:1]}")
    pause(page, 1.5)
    page.locator("#feed").scroll_into_view_if_needed()
    new = page.locator("#feed .card").count() - before
    say(f"Done. {max(new, 0)} new alert card(s) appeared on the live feed (red/orange = more severe):")
    show_alerts(page, new)
    pause(page, 3)


# ---------------------------------------------------------------- demo 2: live RTSP
def demo_live(page, base: str, live_seconds: int):
    say("=== DEMO 2: live camera (RTSP) ===")
    if not port_open(8554):
        say("The fake camera is NOT running (nothing is listening on port 8554), so I am skipping this demo.")
        say("Start it in another terminal, then run this script again with '--mode live':")
        say("   python scripts/simulate_rtsp.py data/videos/Assault001_x264.mp4")
        return
    before = page.locator("#feed .card").count()
    page.locator("#cam").scroll_into_view_if_needed()
    say(f"Typing the camera address {RTSP_URL} into 'Connect a live camera'...")
    page.fill("#camurl", RTSP_URL)
    page.fill("#camname", "Demo camera (fake RTSP)")
    say("Clicking 'Start live analysis' - the server connects to the stream and keeps analysing it, no end.")
    with page.expect_response(lambda r: r.url.endswith("/streams") and r.request.method == "POST") as resp:
        page.click("#cambtn")
    if resp.value.status != 200:
        say(f"The server refused the stream: {resp.value.json().get('detail')}")
        return
    sid = resp.value.json()["stream_id"]
    page.locator("#jobs").scroll_into_view_if_needed()

    say("Waiting for the connection (the badge should turn green and say LIVE)...")
    start = time.time()
    while time.time() - start < 30:
        j = job_by_id(page, base, sid)
        if j and j["status"] == "live":
            break
        time.sleep(1)
    else:
        j = job_by_id(page, base, sid)
        say(f"Could not connect to the camera. Status: {j['status'] if j else '?'}; "
            f"last message: {(j['errors'][-1:] if j else '')}")
        page.request.delete(f"{base}/streams/{sid}")
        return
    say("Connected - the camera feed is LIVE. Now analysing about 10 frames per second.")

    start, last, got_alert = time.time(), None, False
    while time.time() - start < live_seconds:
        j = job_by_id(page, base, sid)
        line = (f"   live: {j['fps']} fps, {j['frames_processed']} frames, {j['breaches']} zone breach(es), "
                f"{j['breaches_classified']} analysed, {j['alerts_created']} alert(s)")
        if line != last:
            say(line)
            last = line
        if j["alerts_created"] >= 1 and not got_alert:
            got_alert = True
            say("A live alert was raised! Scrolling to it. (Letting it run a little longer.)")
            page.locator("#feed").scroll_into_view_if_needed()
            deadline = min(start + live_seconds, time.time() + 8)
            while time.time() < deadline:
                time.sleep(1)
            break
        time.sleep(2)
    if not got_alert:
        say(f"No alert within {live_seconds} seconds - this depends on what the looped video shows and "
            "when people enter the zone. Try a longer wait with --live-seconds 180.")

    new = page.locator("#feed .card").count() - before
    if new > 0:
        say(f"{new} live alert card(s) appeared, pushed instantly over the WebSocket:")
        show_alerts(page, new)
    say("Stopping the live stream with the 'Stop' button...")
    page.locator("#jobs").scroll_into_view_if_needed()
    page.get_by_role("button", name="Stop").first.click()
    for _ in range(15):
        j = job_by_id(page, base, sid)
        if j and j["status"] == "stopped":
            say("Stream stopped.")
            break
        time.sleep(1)
    pause(page, 2)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["both", "upload", "live"], default="both")
    ap.add_argument("--video", default="data/videos/Assault001_x264.mp4", help="video for the upload demo")
    ap.add_argument("--slow-mo", type=int, default=700, help="milliseconds between browser actions")
    ap.add_argument("--upload-timeout", type=int, default=300, help="max seconds to wait for the upload job")
    ap.add_argument("--live-seconds", type=int, default=90, help="how long to watch the live stream")
    ap.add_argument("--headless", action="store_true", help="no visible window (for testing)")
    a = ap.parse_args()

    video = (ROOT / a.video) if not Path(a.video).is_absolute() else Path(a.video)
    if a.mode in ("both", "upload") and not video.exists():
        sys.exit(f"Sample video not found: {video}")

    base, server = ensure_server()
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge", headless=a.headless, slow_mo=a.slow_mo)
                say("Opened Microsoft Edge.")
            except Exception:
                browser = p.chromium.launch(headless=a.headless, slow_mo=a.slow_mo)
                say("Opened Chromium.")
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            say(f"Opening the dashboard at {base} ...")
            page.goto(base)
            page.wait_for_selector("#feed")
            say("Dashboard loaded. The green dot in the top-left means the live alert connection is on.")
            pause(page, 2)
            if a.mode in ("both", "upload"):
                demo_upload(page, base, video, a.upload_timeout)
            if a.mode in ("both", "live"):
                demo_live(page, base, a.live_seconds)
            say("Demo finished. Leaving the window open for 10 more seconds...")
            pause(page, 10)
            browser.close()
    finally:
        if server is not None:
            say("Shutting down the server I started.")
            server.terminate()


if __name__ == "__main__":
    main()

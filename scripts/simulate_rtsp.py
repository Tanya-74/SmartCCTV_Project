"""Fake IP camera: loops a video file as a live RTSP stream on this computer.

    python scripts/simulate_rtsp.py data/videos/Assault001_x264.mp4
    -> stream available at rtsp://127.0.0.1:8554/cam1

How it works:
  1. MediaMTX (a small open-source RTSP server, downloaded once into tools/) plays the
     role of the camera's network interface.
  2. ffmpeg reads the video file in real time (-re), loops it forever, and pushes it
     to MediaMTX exactly like a camera would.
Leave this running, then start the stream in the app (dashboard or POST /streams).
Press Ctrl+C to stop both.
"""
import argparse
import hashlib
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools" / "mediamtx"
VERSION = "v1.21.4"
ZIP_NAME = f"mediamtx_{VERSION}_windows_amd64.zip"
BASE = f"https://github.com/bluenviron/mediamtx/releases/download/{VERSION}"


def ensure_mediamtx() -> Path:
    exe = TOOLS / "mediamtx.exe"
    if exe.exists():
        return exe
    TOOLS.mkdir(parents=True, exist_ok=True)
    print(f"Downloading MediaMTX {VERSION} (one-time)...")
    data = urllib.request.urlopen(f"{BASE}/{ZIP_NAME}", timeout=120).read()
    sums = urllib.request.urlopen(f"{BASE}/checksums.sha256", timeout=60).read().decode()
    expected = next(l.split()[0] for l in sums.splitlines() if l.strip().endswith(ZIP_NAME))
    if hashlib.sha256(data).hexdigest() != expected:
        sys.exit("MediaMTX download failed its checksum - refusing to run it.")
    zp = TOOLS / ZIP_NAME
    zp.write_bytes(data)
    with zipfile.ZipFile(zp) as z:
        z.extractall(TOOLS)
    zp.unlink()
    print("MediaMTX downloaded and checksum verified.")
    return exe


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="video file to loop as the 'camera'")
    ap.add_argument("--path", default="cam1", help="stream name -> rtsp://127.0.0.1:8554/<path>")
    ap.add_argument("--port", type=int, default=8554)
    a = ap.parse_args()
    if not Path(a.video).exists():
        sys.exit(f"Video not found: {a.video}")

    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    server = ensure_mediamtx()

    srv = subprocess.Popen([str(server)], cwd=TOOLS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    if srv.poll() is not None:
        sys.exit("MediaMTX failed to start (is port 8554 already in use?)")
    url = f"rtsp://127.0.0.1:{a.port}/{a.path}"
    cam = subprocess.Popen([
        ffmpeg, "-hide_banner", "-loglevel", "warning",
        "-re", "-stream_loop", "-1", "-i", a.video,       # read in real time, loop forever
        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", "-g", "30",
        "-f", "rtsp", "-rtsp_transport", "tcp", url,
    ])
    print(f"\nFake camera is LIVE at  {url}\nLooping: {a.video}\nPress Ctrl+C to stop.\n")
    try:
        while cam.poll() is None and srv.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in (cam, srv):
            if p.poll() is None:
                p.terminate()
        print("Stopped.")


if __name__ == "__main__":
    main()

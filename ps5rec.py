#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Screen recorder for a jailbroken PS5 -- captures the whole screen (home UI
included) over the local network, without Remote Play or a capture card.

It drives the PBS payload (github.com/seregonwar/PBS-Payload), which uses the
console's own hardware H.264 encoder (Avcap2). PBS is loaded once per boot and
serves the live feed on port 9999 (falling back into 9999-10008 if busy).

Commands:
  status                  show console / stream state
  load                    send pbs.elf to the ELF loader if the stream is down
  record [FILE.mp4]       record to a file on the console, download, remux to MP4
  stream [FILE.h264]      pull raw /frames straight to disk (no console storage)
  remux IN.h264 OUT.mp4   re-encode/downsample an existing capture

Video and audio are captured together. PBS serves audio as raw PCM (stereo,
48 kHz, float32) on /audio; it is recorded alongside the video and muxed into
the MP4 with AAC. Use --no-audio to record video only.

Output framerate defaults to 15 fps (--fps). Use --fps 0 for the native rate
(the encoder runs at 60 fps), or --fps 60 to keep all frames.

Host, ports and defaults come from flags, then environment, then .env.
"""

import argparse
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PBS_ELF = ROOT / "pbs" / "payload" / "build" / "ps5" / "pbs.elf"
CAPTURES = ROOT / "captures"
PORT_FIRST, PORT_LAST = 9999, 10008
LOADER_PORT = 9021

STOP = False


def _handle_sigint(signum, frame):
    global STOP
    STOP = True


signal.signal(signal.SIGINT, _handle_sigint)


# --------------------------------------------------------------------------- config
def env_value(key, default=None):
    if key in os.environ:
        return os.environ[key]
    env_file = ROOT / ".env"
    if env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = raw.strip().partition("=")
            if sep and name.strip() == key and value.strip():
                return value.strip()
    return default


def host():
    """Console address from --host, env, or .env. None until configured."""
    return env_value("PS5_HOST")


# --------------------------------------------------------------------------- http
def http(method, path, port, timeout=5, data=None, host_override=None):
    """Return (status, body). Uses urllib so no third-party packages are needed."""
    base = f"http://{host_override or host()}:{port}"
    request = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"User-Agent": "ps5rec/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, OSError):
        return 0, b""


def get_json(path, port, timeout=5, host_override=None):
    code, body = http("GET", path, port, timeout, host_override=host_override)
    if code != 200:
        return None
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None


def find_port(host_override=None, timeout=1.5):
    """Scan the PBS port window; return the first port answering /status.json."""
    for port in range(PORT_FIRST, PORT_LAST + 1):
        if get_json("/status.json", port, timeout, host_override) is not None:
            return port
    return None


def send_elf(port=LOADER_PORT, elf=PBS_ELF, host_override=None):
    elf = Path(elf)
    if not elf.is_file():
        raise SystemExit(f"ps5rec: no payload at {elf}")
    destination = host_override or host()
    with socket.create_connection((destination, port), timeout=10) as connection:
        connection.sendall(elf.read_bytes())
        connection.shutdown(socket.SHUT_WR)
        connection.settimeout(2)
        try:
            reply = connection.recv(4096).decode("utf-8", "replace").strip()
        except OSError:
            reply = ""
    print(f"sent {elf.name} ({elf.stat().st_size:,} bytes) to {destination}:{port} {reply}")


def ensure_stream(port, host_override=None):
    """Return a working PBS port, loading the payload if needed."""
    found = find_port(host_override)
    if found:
        return found
    if port is None:
        raise SystemExit("ps5rec: no PBS stream found and --port not set (try: load)")
    print(f"no stream answering; loading {PBS_ELF.name} via the ELF loader")
    send_elf(host_override=host_override)
    for _ in range(30):
        time.sleep(1)
        found = find_port(host_override, timeout=0.6)
        if found:
            print(f"PBS is live on port {found}")
            return found
    raise SystemExit("ps5rec: payload loaded but no stream appeared; check the console and klog")


# --------------------------------------------------------------------------- ffmpeg
def remux(source, target, fps=0, native_fps=60.0, crf=20, preset="veryfast", audio=None):
    """Wrap/encode an Annex B H.264 file into an MP4 at the requested fps.

    If audio is given (raw f32le stereo 48 kHz), mux it in as AAC.
    """
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    cmd += ["-fflags", "+genpts", "-r", str(native_fps or 60.0), "-i", str(source)]
    has_audio = audio is not None and Path(audio).is_file() and Path(audio).stat().st_size > 0
    if has_audio:
        cmd += ["-f", "f32le", "-ar", "48000", "-ac", "2", "-i", str(audio)]
    if fps and abs(fps - native_fps) > 0.5:
        cmd += ["-vf", f"fps={fps}", "-c:v", "libx264", "-preset", preset,
                "-crf", str(crf), "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]
    if has_audio:
        # No -shortest: with -c:v copy it silently drops the audio stream.
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-movflags", "+faststart", str(target)]
    print("  " + " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise SystemExit(f"ps5rec: ffmpeg failed: {result.stderr.strip()[-800:]}")
    return target


# --------------------------------------------------------------------------- modes
def cmd_status(args):
    port = find_port(args.host)
    if port is None:
        print(f"no PBS stream on {args.host}:{PORT_FIRST}-{PORT_LAST}")
        return 1
    config = get_json("/config.json", port, host_override=args.host) or {}
    status = get_json("/status.json", port, host_override=args.host) or {}
    print(f"PBS live at http://{args.host}:{port}/")
    print(f"  config : {json.dumps(config)}")
    print(f"  status : {json.dumps(status)}")
    return 0


def cmd_load(args):
    send_elf(args.loader_port, args.elf, args.host)
    port = None
    for _ in range(30):
        time.sleep(1)
        port = find_port(args.host, timeout=0.6)
        if port:
            break
    if port:
        print(f"PBS is live on port {port}")
        return 0
    print("payload sent; no stream detected yet -- check the console", file=sys.stderr)
    return 1


def wait_seconds(seconds):
    deadline = time.monotonic() + seconds
    while not STOP and time.monotonic() < deadline:
        time.sleep(min(0.2, deadline - time.monotonic()))


def capture_audio(port, stop, path, host_override=None):
    """Drain PBS's /audio into raw f32le PCM until stop is set.

    Like /frames, the HTTP stream is 8-byte (!II size, pts) headers followed by
    the PCM block. Only the payload belongs in the .f32le file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(f"http://{host_override or host()}:{port}/audio",
                                    timeout=5) as response, path.open("wb") as output:
            while not stop.is_set():
                header = response.read(8)
                if len(header) < 8:
                    break
                size, pts = struct.unpack("!II", header)
                if not 0 < size <= 0x200000:
                    break
                data = bytearray()
                while len(data) < size:
                    part = response.read(size - len(data))
                    if not part:
                        break
                    data.extend(part)
                if len(data) != size:
                    break
                output.write(data)
    except Exception as error:
        print(f"  audio capture: {error}", file=sys.stderr)


def start_audio(port, host_override):
    """Return (stop_event, path, thread), or (None, None, None)."""
    stop = threading.Event()
    path = CAPTURES / "_raw" / f"audio-{time.strftime('%Y%m%d-%H%M%S')}.f32le"
    thread = threading.Thread(target=capture_audio, args=(port, stop, path, host_override),
                              daemon=True)
    thread.start()
    return stop, path, thread


def stop_audio(stop, thread):
    if stop is None:
        return
    stop.set()
    thread.join(timeout=5)


def cmd_record(args):
    port = ensure_stream(args.port, args.host)
    status = get_json("/status.json", port, host_override=args.host) or {}
    native = float(status.get("fps") or 60.0)
    print(f"recording from {args.host}:{port} ({status.get('width')}x{status.get('height')} "
          f"@ {native:.1f} fps) -> target {args.fps or int(native)} fps")

    http("POST", "/record/start", port, host_override=args.host)
    print("  recording started (waiting for next keyframe)")
    audio_stop, audio_path, audio_thread = (None, None, None)
    if not args.no_audio:
        audio_stop, audio_path, audio_thread = start_audio(port, args.host)
        print("  audio capture started (48 kHz stereo)")
    wait_seconds(args.seconds)
    print("  stopping...")
    http("POST", "/record/stop", port, host_override=args.host)
    stop_audio(audio_stop, audio_thread)

    name = None
    for _ in range(20):
        status = get_json("/status.json", port, host_override=args.host) or {}
        if status.get("recording") in (False, "false", None) and status.get("recording_name"):
            name = status["recording_name"]
            break
        time.sleep(0.5)
    if not name:
        recordings = get_json("/recordings", port, host_override=args.host) or []
        h264 = [item["name"] for item in recordings
                if item.get("name", "").endswith(".h264") and not item.get("active")]
        if h264:
            name = sorted(h264)[-1]

    target = Path(args.file) if args.file else CAPTURES / time.strftime("ps5-home-%Y%m%d-%H%M%S.mp4")
    if not name:
        raise SystemExit("ps5rec: no finished recording was found on the console")

    raw_dir = CAPTURES / "_raw"
    raw = raw_dir / name
    raw_dir.mkdir(parents=True, exist_ok=True)
    code, body = http("GET", f"/recordings/{name}", port, timeout=120, host_override=args.host)
    if code != 200 or not body:
        raise SystemExit(f"ps5rec: could not download {name} (HTTP {code})")
    raw.write_bytes(body)
    print(f"  downloaded {name} ({len(body):,} bytes)")

    audio_ok = audio_path is not None and audio_path.is_file() and audio_path.stat().st_size > 0
    if audio_ok:
        print(f"  captured {audio_path.stat().st_size:,} bytes of audio")
    remux(raw, target, fps=args.fps, native_fps=native, crf=args.crf,
          audio=audio_path if audio_ok else None)
    print(f"  -> {target}")
    if not args.keep_raw:
        raw.unlink()
        if audio_path is not None:
            audio_path.unlink(missing_ok=True)
    if args.delete_remote:
        http("DELETE", f"/recordings/{name}", port, host_override=args.host)
        print(f"  deleted {name} from the console")
    return 0


def cmd_stream(args):
    port = ensure_stream(args.port, args.host)
    target = Path(args.file) if args.file else CAPTURES / time.strftime("ps5-stream-%Y%m%d-%H%M%S.h264")
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"streaming raw H.264 from {args.host}:{port}/frames -> {target} "
          f"(Ctrl+C to stop)")
    config = get_json("/config.json", port, host_override=args.host) or {}
    written = 0
    deadline = None if args.seconds <= 0 else time.monotonic() + args.seconds
    audio_stop, audio_path, audio_thread = (None, None, None)
    if args.mp4 and not args.no_audio:
        audio_stop, audio_path, audio_thread = start_audio(port, args.host)
        print("  audio capture started (48 kHz stereo)")
    with urllib.request.urlopen(f"http://{args.host}:{port}/frames", timeout=5) as response, \
            target.open("wb") as output:
        # Annex B needs SPS/PPS at the head of the file.
        for nal in ("sps", "pps"):
            try:
                output.write(b"\0\0\0\1" + bytes.fromhex(config[nal]))
                written += 4 + len(config[nal]) // 2
            except (KeyError, ValueError):
                pass
        while not STOP:
            if deadline and time.monotonic() >= deadline:
                break
            header = response.read(8)
            if len(header) < 8:
                break
            size, pts = struct.unpack("!II", header)
            if not 0 < size <= 0x200000:
                raise SystemExit(f"ps5rec: bad frame size {size}")
            data = bytearray()
            while len(data) < size:
                part = response.read(size - len(data))
                if not part:
                    raise SystemExit("ps5rec: stream ended mid-frame")
                data.extend(part)
            output.write(data)
            written += size
    print(f"  wrote {written:,} bytes to {target}")
    stop_audio(audio_stop, audio_thread)
    if args.mp4:
        mp4 = target.with_suffix(".mp4")
        audio_ok = audio_path is not None and audio_path.is_file() and audio_path.stat().st_size > 0
        remux(target, mp4, fps=args.fps, native_fps=args.native_fps, crf=args.crf,
              audio=audio_path if audio_ok else None)
        print(f"  -> {mp4}")
    return 0


def cmd_remux(args):
    remux(args.input, args.output, fps=args.fps, native_fps=args.native_fps,
          crf=args.crf, audio=args.audio)
    print(f"-> {args.output}")
    return 0


# --------------------------------------------------------------------------- cli
def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default=host(), help="PS5 address (default: %(default)s)")
    parser.add_argument("--port", type=int, default=None,
                        help="PBS port (default: autodetect 9999-10008)")
    parser.add_argument("--fps", type=int, default=int(env_value("PS5REC_FPS", "15")),
                        help="output fps: 0=native 60, 15=goal, 60=max (default: %(default)s)")
    parser.add_argument("--native-fps", type=float, default=60.0,
                        help="source fps for remux when console is unreachable (default: %(default)s)")
    parser.add_argument("--crf", type=int, default=20, help="x264 quality (default: %(default)s)")
    parser.add_argument("--seconds", type=float, default=0,
                        help="record length; 0 = until Ctrl+C (default: %(default)s)")
    parser.add_argument("--no-audio", action="store_true",
                        help="do not capture/mux the console's audio")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    loading = sub.add_parser("load")
    loading.add_argument("--loader-port", type=int, default=LOADER_PORT)
    loading.add_argument("--elf", default=str(PBS_ELF))

    recording = sub.add_parser("record")
    recording.add_argument("file", nargs="?")
    recording.add_argument("--keep-raw", action="store_true")
    recording.add_argument("--delete-remote", action="store_true",
                           help="delete the .h264 from the console after download")

    streaming = sub.add_parser("stream")
    streaming.add_argument("file", nargs="?")
    streaming.add_argument("--mp4", action="store_true", help="also encode an MP4")
    streaming.add_argument("--seconds", type=float, default=0)

    remuxing = sub.add_parser("remux")
    remuxing.add_argument("input")
    remuxing.add_argument("output")
    remuxing.add_argument("--audio", help="raw f32le stereo 48 kHz audio file to mux in")
    args = parser.parse_args()

    if args.command in ("status", "load", "record", "stream") and not args.host:
        raise SystemExit("no console address set: run ./configure.sh <ip>, "
                         "or pass --host <ip>")
    if args.seconds and args.command not in ("record", "stream"):
        parser.error("--seconds only applies to record/stream")
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ps5rec: ffmpeg is required (install it first)")

    return {
        "status": cmd_status,
        "load": cmd_load,
        "record": cmd_record,
        "stream": cmd_stream,
        "remux": cmd_remux,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

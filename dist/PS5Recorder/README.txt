PS5 Home Screen Recorder
========================
Launches the PBS hardware H.264 encoder. Stream: http://<PS5-IP>:9999/

To save a video on this console:
  1. Open http://<PS5-IP>:9999/ in a browser on your network.
  2. Click Record, then Stop.
  3. The .h264 file lands in /data/pbs/recordings/ on this console.
  4. Copy it via FTP (port 1337) and remux with ffmpeg, or run
     ps5rec.py record on your PC to download + remux to MP4 automatically.

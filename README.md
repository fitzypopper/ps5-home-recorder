# PS5 home-screen recorder

Records the **whole PS5 screen — home screen / system UI included — at 15 fps by
default, up to 60 fps**, with no Remote Play and no capture card. It uses the
console's own Avcap2 hardware H.264 encoder via the
[PBS payload](https://github.com/seregonwar/PBS-Payload).

Console: `192.168.1.136`, firmware **13.40**, jailbroken (etaHEN + kstuff).

## How it works

The PBS payload runs on the console and exposes the live feed at
`http://192.168.1.136:9999/`. It can write an **H.264 video file to the console's
own disk** at `/data/pbs/recordings/`. `ps5rec.py` starts/stops that recording,
captures the console's audio at the same time (`/audio`, 48 kHz stereo float32),
downloads the video, and muxes both into an MP4 on your PC.

```
pbs.elf (on PS5) --hardware H.264--> /data/pbs/recordings/pbs-*.h264  (video on PS5)
                              \--- /audio (48 kHz stereo PCM) ---> audio.f32le (PC)
                                        |
                                  ffmpeg mux
                                        v
                        captures/ps5-home-*.mp4  (H.264 video + AAC stereo audio)
```

Audio is on by default. Pass `--no-audio` before the command for video only.
The console-side `.h264` is video-only; the sound lives in the MP4 on the PC.

The web interface's Record button also saves audio now: each recording writes
a companion `<name>.f32le` (raw 48 kHz stereo PCM) beside the `.h264` in
`/data/pbs/recordings/`, and the `.json` lists its audio codec. Both files are
downloadable from the web UI (`/recordings/<name>`) or FTP. To combine them:

```bash
python3 ps5rec.py --fps 0 --native-fps 60 remux file.h264 out.mp4 --audio file.f32le
```

## Video file locations

- **On the console:** `/data/pbs/recordings/pbs-<timestamp>-<seq>.h264`
  (plus a `.json` with width/height/fps). Copy it off with FTP port **1337**,
  user `anonymous`, any password.
- **On the PC:** `captures/ps5-home-<timestamp>.mp4` (15 fps H.264 video + AAC
  stereo audio). `ps5rec.py record` does the download + remux for you.

The console file is raw H.264 (video only), not MP4. To play it directly, remux:
`python3 ps5rec.py remux file.h264 out.mp4 --fps 15`, or add
`--audio recording.f32le` to mux a separately captured audio file, or just use
`record`, which handles both.

## Quick start

```bash
cd ~/Projects/ps5-home-recorder

# one-time per console boot: start the payload (ELF loader on port 9021)
python3 ps5rec.py load
python3 ps5rec.py status                 # confirm 1920x1080 @ ~60fps

# record 30s to an MP4 on the PC (console keeps the .h264 too)
./go.sh 30                               # 30s @ 15fps
./go.sh 30 60                            # 30s @ 60fps (max)
./go.sh                                  # until Ctrl+C
```

`go.sh [seconds] [fps]`; `0` seconds = until Ctrl+C. The video is always saved
on the console first, then copied/remuxed to the PC.

Other commands:

| Command | Purpose |
| --- | --- |
| `python3 ps5rec.py status` | Show stream state, resolution, fps |
| `python3 ps5rec.py load` | Send `pbs.elf` to port 9021 |
| `python3 ps5rec.py record [file.mp4]` | Record → download → MP4 |
| `python3 ps5rec.py stream [file.h264] --mp4` | Pull raw `/frames` live to PC |
| `python3 ps5rec.py remux IN.h264 OUT.mp4` | Remux an existing capture |

`record` options: `--delete-remote` removes the `.h264` from the console after
download; `--keep-raw` keeps the raw video and audio locally. Global flags go
before the command: `--fps N` (`0` = native 60), `--seconds N`, `--crf N`,
`--no-audio` (video only). `remux` accepts `--audio FILE` for a raw f32le file.

You can also use the built-in web UI: open `http://192.168.1.136:9999/`, click
**Record**, then **Stop** — the `.h264` lands in `/data/pbs/recordings/`.

## Installed homebrew package

The launcher package is installed at:

```
/data/homebrew/PS5Recorder/
  PS5Recorder.elf    <- the PBS payload
  homebrew.js        <- launcher entry ("Home Recorder")
  sce_sys/icon0.png
  README.txt
```

Launch **Home Recorder** from the homebrew launcher, or send the ELF directly
with `python3 ps5rec.py load` (port 9021). Source of the package is in
`dist/PS5Recorder/`. Re-deploy after changes with `./deploy-payload.sh`.

**Why a payload and not a native app tile:** an earlier native-app build
(`FAKE99301/eboot.bin`) crashed with a page fault at `0x0`. PBS calls kernel
helpers from the payload SDK's `crt1.o`, which are only initialized by elfldr;
the native app CRT never initializes them. That tile was removed. Use the
payload entry above.

## Firmware note (13.40)

PBS's automatic fallback picks 1440p on unknown firmwares. On **13.40** that
fails with `OpenVideo() -> 0x81950008` (see `/data/pbs/inject.txt`), so the
payload exits before serving port 9999. `pbs.elf` here was rebuilt with
`-DPBS_PS5_DEFAULT_1080P` so it requests **1920×1080** first, which works.
Rebuild with `./build-payload.sh` if you need to regenerate it.

## Logs

- `/data/pbs/inject.txt` — PBS capture log (profile, OpenVideo result, errors).
- Kernel log: `nc 192.168.1.136 3232` — shows `payload.elf calls exit()` and
  app crash reports (`notifyAppCrash`, `SCE_SHELL_UTIL_ERROR_APPLICATION_CRASH`).
- `/data/etaHEN/experimental-utility.log` and `experimental-daemon.log` — etaHEN.
- ShadowMount+ library UI: `http://192.168.1.136:10101/`.

## Security / notes

- PBS HTTP endpoints and FTP are **unauthenticated local-network services**.
  Keep the console on a trusted LAN; never expose these ports to the Internet.
- A 15 Mbps–60 Mbps capture fills disk quickly. Use `--delete-remote` or clear
  old files in `/data/pbs/recordings/` from time to time.
- Avcap2 capture can conflict with other capture consumers (Remote Play etc.);
  stop competing captures first.
- The recorder was verified end-to-end on this console: 1920×1080 @ 60 fps,
  recordings written to `/data/pbs/recordings/`, downloaded and remuxed to
  15 fps MP4s with AAC stereo audio (48 kHz) captured from `/audio`.

## Layout / attribution

- `pbs/` — PBS Payload (GPL-3.0-or-later), rebuilt for 1080p on FW 13.40.
- `tools/`, `payload/`, `build/` — PS5 DevLoop (GPL-3.0-or-later) still-capture fallback.
- `ps5rec.py`, `*.sh` — recorder driver and build/deploy helpers.
- `dist/PS5Recorder/` — homebrew launcher package installed to `/data/homebrew`.
- `captures/` — output MP4s (gitignored).

Not affiliated with Sony Interactive Entertainment.

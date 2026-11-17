#!/usr/bin/env bash
# Rebuild PBS payload with a 1080p first request (required on FW 13.40 here:
# the automatic 1440p request fails with OpenVideo 0x81950008).
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export PS5_PAYLOAD_SDK=/home/fitzypopper/orbit-store-ps5/app/.deps/native/ps5-payload-sdk
export PBS_PS5_EXTRA_DEFINES='-DPBS_PS5_DEFAULT_1080P'
bash "$ROOT/pbs/payload/build.sh" ps5
cp "$ROOT/pbs/payload/build/ps5/pbs.elf" "$ROOT/dist/PS5Recorder/PS5Recorder.elf"
echo "==> updated dist/PS5Recorder/PS5Recorder.elf"

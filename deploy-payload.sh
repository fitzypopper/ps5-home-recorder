#!/usr/bin/env bash
# Deploy the homebrew payload package to /data/homebrew/PS5Recorder via FTP.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ -f $ROOT/.env ]]; then set -a; . "$ROOT/.env"; set +a; fi
PS5=${PS5_HOST:-}
if [[ -z $PS5 ]]; then echo "no console address: run ./configure.sh <ip>" >&2; exit 1; fi
SRC=$ROOT/dist/PS5Recorder
DST=/data/homebrew/PS5Recorder
python3 - "$PS5" "$SRC" "$DST" <<'PY'
import ftplib, os, sys
host, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
f=ftplib.FTP(); f.connect(host,1337,timeout=30); f.login('anonymous','')
def mkdir(p):
    try: f.mkd(p)
    except ftplib.error_perm: pass
mkdir(dst); mkdir(dst+'/sce_sys')
for root,_,files in os.walk(src):
    rel=os.path.relpath(root,src)
    if rel!='.': mkdir(dst+'/'+rel)
    for name in files:
        lp=os.path.join(root,name); rp=dst+'/'+('' if rel=='.' else rel+'/')+name
        with open(lp,'rb') as fh: f.storbinary('STOR '+rp,fh)
        print('put',rp,os.path.getsize(lp))
f.quit()
PY
echo "==> deployed. Launch 'Home Recorder' from the homebrew launcher, or: python3 ps5rec.py load"

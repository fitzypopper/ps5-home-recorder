#!/usr/bin/env bash
# Set this machine's PS5 address. Usage: ./configure.sh [IP]
# With no IP it asks for one. Writes .env (gitignored).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

ip="${1:-}"
if [[ -z $ip ]]; then
    read -r -p "PS5 IP address: " ip
fi
if [[ -z $ip ]]; then echo "no address given" >&2; exit 1; fi

printf '# Console address (set by ./configure.sh)\nPS5_HOST=%s\n' "$ip" > .env
echo "wrote .env with PS5_HOST=$ip"

# best-effort check, never fatal
python3 - "$ip" <<'PY' || true
import socket, sys
ip=sys.argv[1]
for port in (9021, 9999):
    s=socket.socket(); s.settimeout(1.5)
    try:
        s.connect((ip,port)); print(f"  {ip}:{port} reachable")
    except Exception:
        print(f"  {ip}:{port} not reachable (start the payload / check the IP)")
    finally:
        s.close()
PY
echo "done. Now: python3 ps5rec.py load && ./go.sh 30"

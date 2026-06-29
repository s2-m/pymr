#!/usr/bin/env bash
#
# End-to-end round-trip: start a headless pymr listener, push a structure into
# it, and verify (over RPC) that the object actually loaded. Uses xvfb-run for a
# virtual display when available, falling back to PyMOL's headless mode.
#
# Runs two ways with no extra setup:
#   * a full install on PATH   -> uses the `pymr` wrapper
#   * straight from a checkout -> `pixi run -e viewer integration`, which uses
#     the repo's bin/pymr on the viewer env's python + PyMOL
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PYMOL_RPC_PORT:-$((9000 + UID % 1000))}"
VIEWER_ENV="$REPO/.pixi/envs/viewer"
export PATH="$HOME/.local/bin:$PATH"   # the wrappers install.sh linked, if any

# Resolve how to invoke pymr + which python speaks RPC for verification.
if command -v pymr >/dev/null 2>&1; then
    PYMR=(pymr)
    PYBIN="${PYMR_TEST_PYTHON:-$VIEWER_ENV/bin/python}"
elif [ -x "$VIEWER_ENV/bin/python" ]; then
    PYMR=("$VIEWER_ENV/bin/python" "$REPO/bin/pymr")
    PYBIN="$VIEWER_ENV/bin/python"
else
    PYMR=(python "$REPO/bin/pymr")   # already inside an activated env
    PYBIN=python
fi

"$PYBIN" -c 'import pymol_remote' 2>/dev/null \
    || { echo "no viewer env (run ./install.sh full, or: pixi install -e viewer)"; exit 1; }

work="$(mktemp -d)"
srv=""
cleanup() {
    [ -n "$srv" ] && kill "$srv" 2>/dev/null || true
    pkill -f pymol_remote 2>/dev/null || true
    rm -rf "$work"
}
trap cleanup EXIT

cat > "$work/ala.pdb" <<'PDB'
ATOM      1  N   ALA A   1      11.104  13.207  10.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      12.560  13.207  10.000  1.00  0.00           C
ATOM      3  C   ALA A   1      13.000  14.650  10.000  1.00  0.00           C
ATOM      4  O   ALA A   1      12.200  15.560  10.000  1.00  0.00           O
ATOM      5  CB  ALA A   1      13.100  12.400  11.200  1.00  0.00           C
END
PDB
# A second structure so the push goes through the batched set_states loader
# (len(batch) > 1), exercising the raw-bytes + gzip-sniff + cmd.load path.
cp "$work/ala.pdb" "$work/gly.pdb"

# Exercise token auth end-to-end: a 0600 secret both the listener and pusher
# read. With it set, the listener requires a matching X-Pymol-Token header.
export PYMR_TOKEN_FILE="$work/token"
( umask 077; printf 'integration-test-secret\n' > "$PYMR_TOKEN_FILE" )
echo "[integration] token auth via $PYMR_TOKEN_FILE"

echo "[integration] starting headless listener on port $PORT ..."
if command -v xvfb-run >/dev/null; then
    xvfb-run -a "${PYMR[@]}" start -q -K >"$work/server.log" 2>&1 &
else
    "${PYMR[@]}" start -cq -K >"$work/server.log" 2>&1 &
fi
srv=$!

echo "[integration] waiting for the listener ..."
ready=""
for _ in $(seq 1 120); do
    if "$PYBIN" -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1', $PORT))==0 else 1)"; then
        ready=1
        break
    fi
    sleep 1
done
if [ -z "$ready" ]; then
    echo "[integration] listener never came up; server log:"
    cat "$work/server.log"
    exit 1
fi

echo "[integration] pushing structures (batched) ..."
"${PYMR[@]}" "$work/ala.pdb" "$work/gly.pdb"

echo "[integration] verifying objects on the listener (with token) ..."
PYMOL_RPC_PORT="$PORT" "$PYBIN" - <<'PY'
import os
from pymol_remote.client import PymolSession, TimeoutTransport

token = open(os.path.expanduser(os.environ["PYMR_TOKEN_FILE"])).read().strip()
_base = TimeoutTransport.send_content
def _send(self, connection, request_body):
    connection.putheader("X-Pymol-Token", token)
    return _base(self, connection, request_body)
TimeoutTransport.send_content = _send

session = PymolSession(hostname="127.0.0.1", port=int(os.environ["PYMOL_RPC_PORT"]))
names = [str(n).lower() for n in session.get_names()]
for obj in ("ala", "gly"):
    assert any(obj in n for n in names), f"pushed object {obj!r} not found: {names}"
print("[integration] listener objects:", names)
PY

echo "[integration] verifying a wrong token is rejected ..."
PYMOL_RPC_PORT="$PORT" "$PYBIN" - <<'PY'
import os
import sys
from pymol_remote.client import PymolSession, TimeoutTransport

_base = TimeoutTransport.send_content
def _send(self, connection, request_body):
    connection.putheader("X-Pymol-Token", "WRONG-TOKEN")
    return _base(self, connection, request_body)
TimeoutTransport.send_content = _send

try:
    PymolSession(hostname="127.0.0.1", port=int(os.environ["PYMOL_RPC_PORT"]), force_new=True)
except Exception as exc:
    print("[integration] wrong token correctly rejected:", type(exc).__name__)
    sys.exit(0)
print("[integration] ERROR: wrong token was accepted!", file=sys.stderr)
sys.exit(1)
PY

echo "[integration] PASS"

#!/usr/bin/env bash
#
# Turnkey installer for pymr — a file-pushing CLI on top of pymol_remote.
#
#   ./install.sh            # full: open-source PyMOL + client. Run the listener
#                           #       (`pymr start`), push to it, and view locally
#                           #       (`pyml`) — one machine.
#   ./install.sh pusher     # client only: a headless machine that just pushes
#                           #       structures to a remote listener (no PyMOL).
#
# pixi (the only prerequisite) provisions everything into envs inside this repo.
# Thin wrappers are linked into ~/.local/bin (override with $BINDIR) so `pymr`
# (and, for a full install, `pyml`) are on your PATH while still pointing back at
# this checkout.
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLE="${1:-full}"
BIN="${BINDIR:-$HOME/.local/bin}"

PIXI="$(command -v pixi || true)"
[ -z "$PIXI" ] && [ -x "$HOME/.pixi/bin/pixi" ] && PIXI="$HOME/.pixi/bin/pixi"
if [ -z "$PIXI" ]; then
    echo "ERROR: pixi not found. Install it first, then re-run:" >&2
    echo "    curl -fsSL https://pixi.sh/install.sh | bash" >&2
    exit 1
fi

mkdir -p "$BIN"

# link_cmd <name> <env-dir> [pymol-bin]
# Write a wrapper that runs bin/<name> on the given env's python, optionally
# exporting PYMR_PYMOL_BIN so the launchers find this env's PyMOL by default.
link_cmd() {
    local name="$1" env="$2" pymol="${3:-}"
    {
        echo '#!/usr/bin/env bash'
        [ -n "$pymol" ] && echo "export PYMR_PYMOL_BIN=\"$pymol\""
        echo "exec \"$env/bin/python\" \"$REPO/bin/$name\" \"\$@\""
    } > "$BIN/$name"
    chmod +x "$BIN/$name"
    echo "  linked $BIN/$name  (python: $env/bin/python)"
}

case "$ROLE" in
    full|viewer|both)
        echo "[full] solving env (pymol-open-source + pymol-remote) ..."
        "$PIXI" install --manifest-path "$REPO/pixi.toml" -e viewer
        env="$REPO/.pixi/envs/viewer"
        link_cmd pymr "$env" "$env/bin/pymol"
        link_cmd pyml "$env" "$env/bin/pymol"
        ;;
    pusher|client)
        echo "[pusher] solving client env (pymol-remote) ..."
        "$PIXI" install --manifest-path "$REPO/pixi.toml"
        link_cmd pymr "$REPO/.pixi/envs/default"
        ;;
    *)
        echo "usage: ./install.sh [full|pusher]" >&2
        exit 1
        ;;
esac

# Shared RPC secret: a 0600 token (readable only by you) that `pymr start`
# requires as an X-Pymol-Token header — the real credential, since the loopback
# port is guessable on a shared machine. Generated once and never overwritten; copy
# it to each machine you push from/to (a shared home directory propagates it).
TOKEN_FILE="${PYMR_TOKEN_FILE:-$HOME/.config/pymr/token}"
if [ -s "$TOKEN_FILE" ]; then
    echo "  RPC token present: $TOKEN_FILE"
else
    mkdir -p "$(dirname "$TOKEN_FILE")"
    if command -v openssl >/dev/null 2>&1; then
        secret="$(openssl rand -hex 32)"
    else
        secret="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
    fi
    ( umask 077; printf '%s\n' "$secret" > "$TOKEN_FILE" )
    chmod 600 "$TOKEN_FILE"
    echo "  generated RPC token: $TOKEN_FILE (mode 600, readable only by you)"
    echo "  -> copy this file to any other machine you push from/to."
fi

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "NOTE: $BIN is not on \$PATH — add it to use the commands." ;;
esac

echo
echo "Done ($ROLE)."
echo "    pymr start              # launch PyMOL with the RPC listener (the viewer)"
echo "    pymr structure.cif      # push structures into the running listener"
echo "    pymr --cycle dir/       # step through a directory one at a time"
case "$ROLE" in
    full|viewer|both)
        echo "    pyml structure.cif      # open in a local PyMOL (no RPC)" ;;
esac

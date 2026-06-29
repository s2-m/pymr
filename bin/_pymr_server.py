"""Server-side bootstrap injected into PyMOL by `pymr start`.

Runs inside PyMOL's Python: starts the pymol_remote RPC server, then registers
`set_states` — a batch loader that loads many structures in a single RPC call.
Pushing a directory then costs one round-trip instead of one per file, which is
the dominant cost over an SSH tunnel. If this module is unavailable (e.g. an
older listener), the pusher falls back to per-file `set_state` automatically.
"""

from __future__ import annotations


def _set_states(items: list) -> int:
    """Load many structures in one call.

    Each item is ``[buffer, object, format]``; *buffer* is the (optionally
    gzipped) file bytes — PyMOL auto-detects the gzip magic regardless of the
    temp file's extension. Returns the number of structures successfully loaded.
    """
    import tempfile

    from pymol import cmd

    loaded = 0
    for buffer, obj, fmt in items:
        data = getattr(buffer, "data", buffer)  # xmlrpc Binary -> bytes if needed
        try:
            with tempfile.NamedTemporaryFile(delete=True, suffix="." + fmt) as tmp:
                with open(tmp.name, "wb") as fh:
                    fh.write(data)
                cmd.delete(obj)
                cmd.load(tmp.name, obj, 0, fmt)
            loaded += 1
        except Exception as exc:  # report and keep going
            print(f"pymr set_states: failed to load {obj!r}: {exc}")
    return loaded


def _enable_token_auth(srv) -> None:
    """Reject RPC requests without a matching ``X-Pymol-Token`` when a token is
    configured — the listener otherwise runs arbitrary code with no auth, and on
    a shared machine the loopback port is guessable. Swaps the live server's
    ``RequestHandlerClass``; the pusher connects after the tunnel is up, so it
    picks up the new handler.
    """
    import hmac

    from _pymr_common import resolve_token

    token = resolve_token()
    if not token:
        print("pymr: RPC auth OFF (no token) — rely on loopback + SSH tunnel.")
        return

    base = srv.RequestHandlerClass

    class _AuthRequestHandler(base):
        def do_POST(self):  # BaseHTTPRequestHandler dispatch name
            sent = self.headers.get("X-Pymol-Token", "")
            if not hmac.compare_digest(sent, token):
                self.close_connection = True
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return super().do_POST()

    srv.RequestHandlerClass = _AuthRequestHandler
    print("pymr: RPC auth ON — clients must send a matching token.")


def register(server) -> None:
    """Register the batch loader on an already-launched pymol_remote server.

    The server is launched *before* this is imported, so a failure here (or a
    missing module) leaves the listener up — the pusher just falls back to
    per-file pushes. *server* is the ``pymol_remote.server`` module.
    """
    srv = getattr(server, "_GLOBAL_PYMOL_XMLRPC_SERVER", None)
    if srv is None or not hasattr(srv, "register_function_with_kwargs"):
        print("pymr: RPC server unavailable; batch loader not registered.")
        return
    _enable_token_auth(srv)
    srv.register_function_with_kwargs(_set_states, "set_states")
    print("pymr: batch loader `set_states` registered.")

# pymr

A file-pushing CLI built on [`pymol_remote`](https://github.com/Croydon-Brixton/pymol-remote):
view protein structures in PyMOL on the machine that has your **display** while the files
live on the machine that has your **data** — reads locally, ships compressed bytes over RPC,
no shared filesystem needed.

It installs open-source PyMOL via [pixi](https://pixi.sh) (the only prerequisite)
and gives you two commands:

| Command         | Where it runs            | What it does |
|-----------------|--------------------------|--------------|
| `pymr start`    | viewer (has the display) | Launch PyMOL with the RPC listener on `$PYMOL_RPC_PORT`. |
| `pymr <files>`  | pusher (has the data)    | Push structure bytes into the running listener over RPC. |
| `pyml <files>`  | viewer                   | Open files in a local PyMOL (no RPC). |

## Install

Prerequisite: pixi — `curl -fsSL https://pixi.sh/install.sh | bash`

```bash
git clone https://github.com/s2-m/pymr && cd pymr

./install.sh           # full: open-source PyMOL + RPC client
./install.sh pusher    # client only: for headless machines that only push
```

Wrappers are linked into `~/.local/bin` (override with `BINDIR=...`); make sure
that's on your `PATH`.

## Updating

```bash
git pull && ./install.sh
```

`pixi install` runs as part of `install.sh`, so the environment is updated
automatically whenever dependencies change. Nothing is downloaded if they haven't.

## Remote workflow

1. **Viewer** — start the listener:
   ```bash
   pymr start
   ```
2. **Tunnel** the port from the pusher back to the viewer. Open the tunnel when
   you're ready to push — idle SSH connections are often dropped by firewalls, so
   bring it up on demand rather than leaving it open. Run on the viewer:
   ```bash
   ssh -R $PYMOL_RPC_PORT:localhost:$PYMOL_RPC_PORT you@remote-host
   ```
   Or add to `~/.ssh/config` on the viewer for one-time setup:
   ```sshconfig
   Host remote-host
       RemoteForward 9042 localhost:9042   # replace 9042 with your $PYMOL_RPC_PORT
       ControlMaster auto
       ControlPath ~/.ssh/cm-%r@%h:%p
       ControlPersist 10m
   ```
3. **Pusher** — push structures in:
   ```bash
   pymr design.cif               # one structure
   pymr results/                 # every structure in a directory
   pymr 'designs/*_top?.cif'     # globs (quote them)
   pymr --cycle big_dir/         # step through one at a time (arrows / n / p / q)
   pymr run.pml                  # replay a .pml; local load lines push bytes
   pymr session.pse              # load a saved session (replaces the current one)
   ```

Each push reads the file locally and ships the bytes — the listener never needs
to see the path. Multiple files are sent in batched `set_states` RPC calls
(chunked, default 200 per call — set `PYMR_BATCH_SIZE`), so a whole directory is
a handful of round-trips rather than one per file. Older listeners without the
batch loader work fine — the pusher falls back to per-file pushes automatically.
The HTTP transport gzips request bodies, so nothing is pre-compressed on the wire.

Single-structure pushes use [`atomworks`](https://github.com/RosettaCommons/atomworks)
`view_pymol` for normalized serialization (and to read BCIF inputs); a raw
byte-push fallback handles formats atomworks can't serialize (e.g. density maps).
Multi-file/directory pushes ship raw bytes through `set_states` (atomworks is not
involved unless the listener lacks the batch loader).

## Local viewing

```bash
pyml                    # empty PyMOL GUI
pyml structure.cif      # open one file
pyml results/           # open every structure in a directory
pyml --bg model.pdb     # detached from the terminal
```

`pymr start` and `pyml` launch PyMOL normally, so `~/.pymolrc` and your plugins
load as usual.

## Custom PyMOL binary

Both commands respect **`PYMR_PYMOL_BIN`**; the pixi open-source build is the default:

```bash
PYMR_PYMOL_BIN=/path/to/pymol pymr start
```

For a custom build to act as the listener it needs `pymol_remote` importable —
`pymr start` injects it onto `PYTHONPATH` automatically, or install it directly
with `pip install pymol-remote`.

## Security

The RPC listener lets a connected client run arbitrary Python on the viewer machine.
`pymol_remote` has **no authentication**, and on a shared multi-user machine other
users sit on the same host — so the reverse tunnel's loopback port (which is per-user
predictable) can be reached by a co-located user. pymr adds a **shared-secret token**
so the port isn't the only boundary.

- **Token auth (recommended).** `install.sh` generates `~/.config/pymr/token`
  (mode `0600`). When it (or `$PYMOL_RPC_TOKEN`) is set, `pymr start` requires a
  matching `X-Pymol-Token` header — verified constant-time — and the pusher sends
  it automatically, so a co-located user who guesses your port gets `401` instead
  of a Python shell. **Copy the token file to each machine you push from/to** (a
  shared home directory propagates it automatically; otherwise copy it once per
  machine). With no token set, behavior is unchanged.
- Run `pymr start` on a **single-user machine you control** (your desktop/laptop)
  and reach it from the remote machine over the SSH reverse tunnel above. **Don't
  start a listener on a shared multi-user machine.**
- By default `pymol_remote` binds **`localhost`**, so only your SSH tunnel can reach it.
  **Do not set `PYMOL_RPC_HOST=0.0.0.0`** on an untrusted network: that exposes code
  execution to anyone who can reach the port. `pymr start` warns when binding off
  loopback; set `PYMR_ALLOW_SHARED_HOST=1` to silence it once you've secured the host.

## Development

The `dev` pixi environment adds ruff and pytest on top of the default pusher
dependencies. No separate install step — pixi resolves it on first use:

```bash
pixi run -e dev lint             # ruff check
pixi run -e dev format           # ruff format
pixi run -e dev test             # pytest unit tests
pixi run -e viewer integration   # headless round-trip: start → push → verify
tests/check.sh                   # both: unit tests + round-trip
```

## Environment variables

| Variable          | Default        | Description |
|-------------------|----------------|-------------|
| `PYMOL_RPC_HOST`  | `127.0.0.1`    | Listener host to connect/push to. |
| `PYMOL_RPC_PORT`  | `9000 + (UID % 1000)` | Listener RPC port. The default is UID-derived, so it differs per machine — pin the same value on both ends to use a tunnel. |
| `PYMOL_RPC_TOKEN` | unset          | Shared secret required on every RPC request. Overrides the token file; must match on both ends. |
| `PYMR_TOKEN_FILE` | `~/.config/pymr/token` | Where the shared secret is read from when `PYMOL_RPC_TOKEN` is unset. |
| `PYMR_ALLOW_NO_AUTH` | unset       | Allow `pymr start` to launch the no-PyMOL fallback listener (which can't enforce auth) even when a token is configured. |
| `PYMR_PYMOL_BIN`  | pixi env PyMOL | PyMOL binary for `pymr start` and `pyml`. |
| `PYMR_TIMEOUT`    | `120`          | RPC socket timeout in seconds. |
| `PYMR_BATCH_SIZE` | `200`          | Structures per batched `set_states` RPC when pushing many files. |
| `PYMR_ALLOW_SHARED_HOST` | unset   | Silence the warning when `pymr start` binds a non-loopback `PYMOL_RPC_HOST`. |
| `BINDIR`          | `~/.local/bin` | Where command wrappers are linked. |

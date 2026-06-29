"""Shared helpers for the ``pymr`` and ``pyml`` launchers.

Input expansion (files / directories / globs) and PyMOL object-name derivation
live here so both entry points behave identically. This module deliberately
avoids heavy imports (notably ``pymol_remote``) so the local-only ``pyml`` can
use it on machines where the RPC client isn't installed.
"""

from __future__ import annotations

import glob
import os

DEFAULT_TOKEN_FILE = "~/.config/pymr/token"


def token_file() -> str:
    """Path to the shared-secret file ($PYMR_TOKEN_FILE or ~/.config/pymr/token)."""
    return os.path.expanduser(os.environ.get("PYMR_TOKEN_FILE") or DEFAULT_TOKEN_FILE)


def resolve_token() -> str | None:
    """The shared RPC secret, or None when no auth is configured.

    Order: ``$PYMOL_RPC_TOKEN`` → the token file (written by ``install.sh``,
    mode 0600) → None. Must match on both the viewer and the pusher."""
    token = os.environ.get("PYMOL_RPC_TOKEN")
    if token:
        return token.strip() or None
    try:
        with open(token_file()) as fh:
            return fh.read().strip() or None
    except OSError:
        return None


_STRUCTURE_BASE: tuple[str, ...] = (
    # PDB family
    ".pdb",
    ".ent",
    ".p5m",
    ".pqr",
    ".pdbqt",
    # CIF family
    ".cif",
    ".mmcif",
    ".bcif",
    # Small-molecule
    ".mol",
    ".mol2",
    ".sdf",
    ".sd",
    # Other coordinate formats
    ".xyz",
    ".mae",
    # Density / map formats
    ".ccp4",
    ".map",
    ".mrc",
    ".xplor",
    ".dx",
    ".cube",
    ".dsn6",
    ".brix",
    ".omap",
    # PyMOL pickle
    ".pkl",
)

# Gzip variants: only compound extensions (e.g. .pdb.gz) — bare .gz is excluded.
_STRUCTURE_GZ: tuple[str, ...] = tuple(ext + ".gz" for ext in _STRUCTURE_BASE)

STRUCTURE_EXTENSIONS: tuple[str, ...] = _STRUCTURE_BASE + _STRUCTURE_GZ
SCRIPT_EXTENSIONS: tuple[str, ...] = (".pml",)
# .pse.gz and .pze are PyMOL's gzip session formats.
SESSION_EXTENSIONS: tuple[str, ...] = (".pse", ".pse.gz", ".pze")
SUPPORTED_EXTENSIONS: tuple[str, ...] = (
    STRUCTURE_EXTENSIONS + SCRIPT_EXTENSIONS + SESSION_EXTENSIONS
)

# Suffixes stripped when deriving an object name (up to two passes, so .pdb.gz → foo).
_NAME_SUFFIXES: frozenset[str] = frozenset((".gz", ".pml", ".pse", ".pze", *_STRUCTURE_BASE))


def expand_inputs(
    inputs: list[str],
    extensions: tuple[str, ...] = SUPPORTED_EXTENSIONS,
) -> list[str]:
    """Expand *inputs* (files, directories, globs) into a de-duplicated list of
    absolute paths whose names end in one of *extensions*.

    Command-line order is preserved: each argument keeps its position, so the
    paths load (and appear in the PyMOL object list) in the order given. A
    directory or glob argument is expanded in sorted order internally, but does
    not reorder the arguments around it. The first occurrence of a path wins;
    later duplicates are dropped."""
    found: dict[str, None] = {}
    for raw in inputs:
        for path in _expand_one(raw, extensions):
            found.setdefault(path, None)
    return list(found)


def _expand_one(path: str, extensions: tuple[str, ...]) -> list[str]:
    path = os.path.expanduser(path)
    if any(ch in path for ch in "*?["):
        return sorted(
            os.path.abspath(p)
            for p in glob.glob(path, recursive=True)
            if p.lower().endswith(extensions)
        )
    if os.path.isdir(path):
        return sorted(
            os.path.abspath(os.path.join(root, name))
            for root, _, names in os.walk(path)
            for name in names
            if name.lower().endswith(extensions)
        )
    if os.path.isfile(path) and path.lower().endswith(extensions):
        return [os.path.abspath(path)]
    print(f"Warning: no matching files for {path}")
    return []


def object_name(path: str) -> str:
    """The base object name PyMOL would give *path*, dropping up to two suffixes
    so ``foo.cif`` and ``foo.cif.gz`` both yield ``foo``."""
    base = os.path.basename(path)
    for _ in range(2):
        stem, ext = os.path.splitext(base)
        if ext.lower() in _NAME_SUFFIXES:
            base = stem
        else:
            break
    return base or "structure"


def dedupe_by_object(files: list[str]) -> tuple[list[str], list[str]]:
    """Partition *files* into ``(kept, dropped)`` so no two kept structures
    collapse to the same PyMOL object name (e.g. ``foo.cif`` and ``foo.cif.gz``).

    Scripts (``.pml``) are always kept — they create no object. Used by the local
    launcher, where files share one PyMOL command line and a name collision is a
    hard load error.
    """
    kept: list[str] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for path in files:
        if path.lower().endswith(SCRIPT_EXTENSIONS):
            kept.append(path)
            continue
        stem = object_name(path).lower()
        if stem in seen:
            dropped.append(path)
        else:
            seen.add(stem)
            kept.append(path)
    return kept, dropped


class UniqueNamer:
    """Allocate collision-free PyMOL object names, appending ``_2``, ``_3`` … on
    reuse (e.g. ``model.cif`` from two directories becomes ``model``, ``model_2``).
    Used by the remote pusher, where each structure is loaded under an explicit
    name and a collision would otherwise silently overwrite the previous one.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def allocate(self, base: str) -> str:
        count = self._counts.get(base, 0) + 1
        self._counts[base] = count
        return base if count == 1 else f"{base}_{count}"

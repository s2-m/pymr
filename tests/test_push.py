"""Unit tests for the push-side helpers in the `pymr` script: format mapping,
batch-loader detection, the batched byte-push, and `load`-line interception.

The launcher is an extension-less script, so it's loaded by path. `atomworks`
is a required top-level import in `pymr`; it is available in all pixi envs
(including `dev`) via the workspace-level `[pypi-dependencies]`.
"""

import gzip
import importlib.machinery
import importlib.util
import os

import pytest

_PYMR = os.path.join(os.path.dirname(__file__), "..", "bin", "pymr")


@pytest.fixture(scope="module")
def pymr():
    loader = importlib.machinery.SourceFileLoader("pymr_script", _PYMR)
    spec = importlib.util.spec_from_loader("pymr_script", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakeSession:
    """Minimal stand-in for a PymolSession (no PyMOL/RPC required)."""

    def __init__(self, *, has_set_states: bool):
        self._available_commands = {"do", "set_state"}
        if has_set_states:
            self._available_commands.add("set_states")
        self.sent = None

    def set_states(self, payload):
        self.sent = payload
        return len(payload)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a.pdb", "pdb"),
        ("a.cif", "cif"),
        ("a.cif.gz", "cif"),  # .gz stripped before lookup
        ("a.mmcif", "cif"),
        ("a.bcif", "bcif"),
        ("a.sdf", "sdf"),
        ("a.sd", "sdf"),
        ("a.mol2", "mol2"),
        ("a.ccp4", "ccp4"),
        ("a.map", "ccp4"),
        ("a.dsn6", "brix"),
        ("a.omap", "brix"),
        ("a.pdb.gz", "pdb"),
        ("a.xyz", "xyz"),
        ("a.unknown", "cif"),  # unrecognized -> cif default
    ],
)
def test_file_format(pymr, path, expected):
    assert pymr._file_format(path) == expected


def test_server_has(pymr):
    assert pymr._server_has(FakeSession(has_set_states=True), "set_states") is True
    assert pymr._server_has(FakeSession(has_set_states=False), "set_states") is False


def test_push_states_batch_sends_raw_bytes_and_count(pymr, tmp_path):
    plain = tmp_path / "x.pdb"
    plain.write_bytes(b"ATOM PLAIN\n")
    already_gz = tmp_path / "y.cif.gz"
    gz_bytes = gzip.compress(b"data_block\n")
    already_gz.write_bytes(gz_bytes)

    session = FakeSession(has_set_states=True)
    loaded = pymr._push_states_batch(session, [(str(plain), "x"), (str(already_gz), "y")])

    assert loaded == 2  # server-reported load count, not a bare bool
    (buf_x, name_x, fmt_x), (buf_y, name_y, fmt_y) = session.sent
    # No application-level compression: plain bytes go out untouched.
    assert (name_x, fmt_x) == ("x", "pdb")
    assert buf_x == b"ATOM PLAIN\n"
    # A file already gzipped on disk is forwarded verbatim (PyMOL sniffs it).
    assert (name_y, fmt_y) == ("y", "cif")
    assert buf_y == gz_bytes


def test_push_states_batch_skips_unreadable_file(pymr, tmp_path):
    good = tmp_path / "good.pdb"
    good.write_bytes(b"ATOM\n")
    missing = tmp_path / "gone.pdb"  # never created -> open() raises

    session = FakeSession(has_set_states=True)
    loaded = pymr._push_states_batch(session, [(str(good), "good"), (str(missing), "gone")])

    # The bad file is skipped, not fatal; the good one still loads.
    assert loaded == 1
    assert [name for _, name, _ in session.sent] == ["good"]


def test_push_states_batch_returns_none_when_unavailable(pymr, tmp_path):
    plain = tmp_path / "x.pdb"
    plain.write_bytes(b"ATOM\n")
    session = FakeSession(has_set_states=False)
    assert pymr._push_states_batch(session, [(str(plain), "x")]) is None
    assert session.sent is None


@pytest.mark.parametrize(
    ("line", "expected_name"),
    [
        ("load model.pdb", None),
        ("load model.pdb, custom", "custom"),
    ],
)
def test_maybe_intercept_load_accepts_local_structure(
    pymr, tmp_path, monkeypatch, line, expected_name
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "model.pdb").write_bytes(b"ATOM\n")
    hit = pymr._maybe_intercept_load(line)
    assert hit is not None
    abspath, name = hit
    assert abspath == str(tmp_path / "model.pdb")
    assert name == expected_name


def test_maybe_intercept_load_passes_through_keyword_and_missing(pymr, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "model.pdb").write_bytes(b"ATOM\n")
    # state=2 is a load kwarg, not an object name -> don't byte-push, pass through.
    assert pymr._maybe_intercept_load("load model.pdb, state=2") is None
    # Non-existent local path / non-structure -> not intercepted.
    assert pymr._maybe_intercept_load("load nope.pdb") is None
    assert pymr._maybe_intercept_load("bg_color white") is None


def test_maybe_intercept_load_handles_quoted_path_with_space(pymr, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "my model.pdb").write_bytes(b"ATOM\n")
    hit = pymr._maybe_intercept_load('load "my model.pdb"')
    assert hit is not None
    assert hit[0] == str(tmp_path / "my model.pdb")

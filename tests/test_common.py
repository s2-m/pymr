"""Unit tests for the pure helpers in `_pymr_common` (no PyMOL/RPC required)."""

import os

import _pymr_common as common
import pytest


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("foo.pdb", "foo"),
        ("foo.cif", "foo"),
        ("foo.cif.gz", "foo"),
        ("/a/b/model.pdb", "model"),
        ("/a/b/model.cif.gz", "model"),
        ("run.pml", "run"),
        ("weird.v2.pdb", "weird.v2"),  # only known structure suffixes are stripped
        ("noext", "noext"),
    ],
)
def test_object_name(path, expected):
    assert common.object_name(path) == expected


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return str(path)


def test_expand_inputs_directory_is_recursive_and_filtered(tmp_path):
    a = _touch(tmp_path / "a.pdb")
    b = _touch(tmp_path / "b.cif")
    _touch(tmp_path / "notes.txt")  # wrong extension -> excluded
    d = _touch(tmp_path / "sub" / "d.pdb")  # nested -> included (os.walk)

    result = common.expand_inputs([str(tmp_path)])

    assert result == sorted(os.path.abspath(p) for p in (a, b, d))


def test_expand_inputs_preserves_command_line_order(tmp_path):
    c = _touch(tmp_path / "c.pdb")
    a = _touch(tmp_path / "a.pdb")
    b = _touch(tmp_path / "b.pdb")

    # Explicit args keep their typed order — not re-sorted alphabetically.
    assert common.expand_inputs([c, a, b]) == [os.path.abspath(p) for p in (c, a, b)]


def test_expand_inputs_dedupe_keeps_first_position(tmp_path):
    b = _touch(tmp_path / "b.pdb")
    a = _touch(tmp_path / "a.pdb")

    # Duplicate drops to its first occurrence; order otherwise as given.
    assert common.expand_inputs([b, a, b]) == [os.path.abspath(b), os.path.abspath(a)]


def test_expand_inputs_glob(tmp_path):
    a1 = _touch(tmp_path / "a1.pdb")
    a2 = _touch(tmp_path / "a2.pdb")
    _touch(tmp_path / "b.cif")

    result = common.expand_inputs([str(tmp_path / "*.pdb")])

    assert result == sorted(os.path.abspath(p) for p in (a1, a2))


def test_expand_inputs_single_file_and_dedupe(tmp_path):
    a = _touch(tmp_path / "a.pdb")

    # Passing the same file twice collapses to one absolute path.
    assert common.expand_inputs([a, a]) == [os.path.abspath(a)]


def test_expand_inputs_extension_filter(tmp_path):
    _touch(tmp_path / "a.pdb")
    b = _touch(tmp_path / "b.cif")

    result = common.expand_inputs([str(tmp_path)], extensions=(".cif",))

    assert result == [os.path.abspath(b)]


def test_expand_inputs_missing_returns_empty(tmp_path, capsys):
    assert common.expand_inputs([str(tmp_path / "nope.pdb")]) == []
    assert "no matching files" in capsys.readouterr().out.lower()


def test_dedupe_by_object_drops_same_stem_keeps_scripts():
    files = ["/x/foo.cif", "/y/foo.cif.gz", "/z/bar.pdb", "/w/run.pml"]

    kept, dropped = common.dedupe_by_object(files)

    assert kept == ["/x/foo.cif", "/z/bar.pdb", "/w/run.pml"]
    assert dropped == ["/y/foo.cif.gz"]


def test_dedupe_by_object_scripts_never_collide():
    files = ["/a/run.pml", "/b/run.pml"]

    kept, dropped = common.dedupe_by_object(files)

    assert kept == files
    assert dropped == []


def test_unique_namer_sequences_collisions():
    namer = common.UniqueNamer()

    assert namer.allocate("model") == "model"
    assert namer.allocate("model") == "model_2"
    assert namer.allocate("model") == "model_3"
    assert namer.allocate("other") == "other"

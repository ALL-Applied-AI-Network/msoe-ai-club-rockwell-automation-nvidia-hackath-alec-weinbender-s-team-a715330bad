"""twin.py: finds the vendored twin and puts it on sys.path once."""

import sys
import types

import pytest

from sim_server.twin import DEFAULT_TWIN_DIR, use_twin

REQUIRED = ("scene_config.py", "cell.py", "ik.py", "fk.py", "gripper_geometry.py")


def test_the_default_is_this_repos_twin_and_use_is_idempotent():
    assert DEFAULT_TWIN_DIR.name == "fanuc_er4ia_sim" and (DEFAULT_TWIN_DIR / "cell.py").is_file()
    path = use_twin()
    assert use_twin(path) == path
    assert sys.path.count(str(path)) == 1


def test_a_directory_without_the_twin_is_refused(tmp_path):
    (tmp_path / "cell.py").write_text("")
    with pytest.raises(FileNotFoundError, match="scene_config.py"):
        use_twin(tmp_path)


def test_two_different_twins_are_never_mixed(tmp_path, monkeypatch):
    for name in REQUIRED:
        (tmp_path / name).write_text("")
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setitem(sys.modules, "scene_config", types.SimpleNamespace(__file__=str(elsewhere / "scene_config.py")))
    with pytest.raises(RuntimeError, match="already imported"):
        use_twin(tmp_path)
    assert str(tmp_path.resolve()) not in sys.path

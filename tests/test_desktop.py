from __future__ import annotations

import app as desktop


def test_app_data_dir_is_project_root_in_source_mode():
    assert desktop.app_data_dir() == desktop._PROJECT_ROOT


def test_default_workspace_prefers_last_used(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    assert desktop._default_workspace({"last_workspace": str(other)}, frozen=False) == other.resolve()
    assert (
        desktop._default_workspace({"last_workspace": str(tmp_path / "missing")}, frozen=False)
        == desktop._PROJECT_ROOT
    )


def test_find_free_port():
    port = desktop.find_free_port(12990, 5)
    assert isinstance(port, int) and 12990 <= port < 12995


def test_state_roundtrip(tmp_path):
    f = tmp_path / "state.json"
    desktop.save_state(f, {"last_workspace": "C:\\x"})
    assert desktop.load_state(f)["last_workspace"] == "C:\\x"
    assert desktop.load_state(tmp_path / "missing.json") == {}

import argparse
import importlib.util
import sys
from pathlib import Path
import pytest


def _load_check_style_module():
    root = Path(__file__).resolve().parents[1]
    scripts_dir = root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    module_path = scripts_dir / "check_style.py"
    spec = importlib.util.spec_from_file_location("check_style", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_watch_signature_changes_on_diff_content():
    check_style = _load_check_style_module()
    sig_a = check_style._watch_signature(["a.py"], {"a.py": "x"})
    sig_b = check_style._watch_signature(["a.py"], {"a.py": "y"})
    sig_empty = check_style._watch_signature([], {})

    assert sig_a != sig_b
    assert sig_empty == "EMPTY"


def test_build_watch_check_command_omits_watch_flags():
    check_style = _load_check_style_module()
    args = argparse.Namespace(
        staged=True,
        full_scan=False,
        plugin_dir=Path("/tmp/plugin"),
        watch=True,
        watch_interval_seconds=1.0,
        watch_debounce_seconds=0.5,
        watch_max_runs=1,
    )

    cmd = check_style.build_watch_check_command(args)
    joined = " ".join(map(str, cmd))
    assert "--staged" in joined
    assert "--plugin-dir" in joined
    assert "--watch" not in joined


def test_run_watch_mode_triggers_once_and_stops(monkeypatch):
    check_style = _load_check_style_module()
    args = argparse.Namespace(
        staged=False,
        full_scan=False,
        plugin_dir=None,
        watch=True,
        watch_interval_seconds=0.1,
        watch_debounce_seconds=0.0,
        watch_max_runs=1,
        stream=False,
        stream_worker=False,
    )

    sequence = [
        (["a.py"], {"a.py": "diff-1"}),
        (["a.py"], {"a.py": "diff-1"}),
    ]
    calls = {"idx": 0, "run": 0}

    def fake_resolve_target_files(staged, full_scan):
        i = min(calls["idx"], len(sequence) - 1)
        calls["idx"] += 1
        return sequence[i]

    def fake_run(cmd, check=False):
        calls["run"] += 1
        return argparse.Namespace(returncode=0)

    monkeypatch.setattr(check_style, "resolve_target_files", fake_resolve_target_files)
    monkeypatch.setattr(check_style.subprocess, "run", fake_run)
    monkeypatch.setattr(check_style.time, "sleep", lambda _x: None)
    monkeypatch.setattr(check_style.time, "monotonic", lambda: 1.0)

    check_style.run_watch_mode(args)

    assert calls["run"] == 1


def test_run_watch_mode_rejects_full_scan():
    check_style = _load_check_style_module()
    args = argparse.Namespace(
        staged=False,
        full_scan=True,
        plugin_dir=None,
        watch=True,
        watch_interval_seconds=0.1,
        watch_debounce_seconds=0.0,
        watch_max_runs=1,
        stream=False,
        stream_worker=False,
    )

    with pytest.raises(SystemExit):
        check_style.run_watch_mode(args)

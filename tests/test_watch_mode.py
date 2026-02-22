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
        watch_queue_max=8,
        watch_reinsert_delay_seconds=2.0,
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
        watch_queue_max=8,
        watch_reinsert_delay_seconds=2.0,
        stream=False,
        stream_worker=False,
    )

    with pytest.raises(SystemExit):
        check_style.run_watch_mode(args)


def test_watch_queue_overflow_moves_oldest_to_delayed_and_restores():
    check_style = _load_check_style_module()
    pending = []
    delayed = []

    check_style._watch_enqueue_signature(
        pending_queue=pending,
        delayed_queue=delayed,
        signature="sig-1",
        now=1.0,
        queue_max=1,
        reinsert_delay=2.0,
        last_applied_signature=None,
    )
    check_style._watch_enqueue_signature(
        pending_queue=pending,
        delayed_queue=delayed,
        signature="sig-2",
        now=2.0,
        queue_max=1,
        reinsert_delay=2.0,
        last_applied_signature=None,
    )

    assert [item["signature"] for item in pending] == ["sig-2"]
    assert [item["signature"] for item in delayed] == ["sig-1"]
    assert delayed[0]["eligible_at"] == 4.0

    check_style._watch_restore_delayed_signatures(
        pending_queue=pending,
        delayed_queue=delayed,
        now=3.9,
        queue_max=2,
    )
    assert [item["signature"] for item in pending] == ["sig-2"]
    assert [item["signature"] for item in delayed] == ["sig-1"]

    check_style._watch_restore_delayed_signatures(
        pending_queue=pending,
        delayed_queue=delayed,
        now=4.1,
        queue_max=2,
    )
    assert [item["signature"] for item in pending] == ["sig-2", "sig-1"]
    assert delayed == []


def test_watch_priority_from_diff_marks_security_related_changes_high():
    check_style = _load_check_style_module()
    normal = check_style._watch_priority_from_diff({"a.py": "print('hello')"})
    medium = check_style._watch_priority_from_diff({"a.py": "add audit logging for compliance"})
    high = check_style._watch_priority_from_diff({"a.py": "set user password and auth token"})

    assert normal == check_style.WATCH_PRIORITY_NORMAL
    assert medium == check_style.WATCH_PRIORITY_MEDIUM
    assert high == check_style.WATCH_PRIORITY_HIGH


def test_watch_queue_overflow_keeps_high_priority_entries():
    check_style = _load_check_style_module()
    pending = []
    delayed = []

    check_style._watch_enqueue_signature(
        pending_queue=pending,
        delayed_queue=delayed,
        signature="high-1",
        now=1.0,
        queue_max=2,
        reinsert_delay=2.0,
        last_applied_signature=None,
        priority=0,
    )
    check_style._watch_enqueue_signature(
        pending_queue=pending,
        delayed_queue=delayed,
        signature="normal-1",
        now=1.1,
        queue_max=2,
        reinsert_delay=2.0,
        last_applied_signature=None,
        priority=1,
    )
    check_style._watch_enqueue_signature(
        pending_queue=pending,
        delayed_queue=delayed,
        signature="high-2",
        now=1.2,
        queue_max=2,
        reinsert_delay=2.0,
        last_applied_signature=None,
        priority=0,
    )

    assert [item["signature"] for item in pending] == ["high-1", "high-2"]
    assert [item["signature"] for item in delayed] == ["normal-1"]


def test_watch_restore_delayed_prefers_high_priority_when_capacity_limited():
    check_style = _load_check_style_module()
    pending = []
    delayed = [
        {"signature": "normal-a", "eligible_at": 1.0, "priority": check_style.WATCH_PRIORITY_NORMAL},
        {"signature": "high-a", "eligible_at": 1.0, "priority": check_style.WATCH_PRIORITY_HIGH},
    ]

    check_style._watch_restore_delayed_signatures(
        pending_queue=pending,
        delayed_queue=delayed,
        now=2.0,
        queue_max=1,
    )

    assert [item["signature"] for item in pending] == ["high-a"]
    assert [item["signature"] for item in delayed] == ["normal-a"]


def test_watch_priority_from_rule_severity_uses_matching_rule_level():
    check_style = _load_check_style_module()
    rules = [
        ("rule_low.md", ["*.py"], "body", {"severity": "low"}),
        ("rule_high.md", ["security_*.md"], "body", {"severity": "high"}),
    ]

    p1 = check_style._watch_priority_from_rule_severity(["main.py"], rules)
    p2 = check_style._watch_priority_from_rule_severity(["security_notes.md"], rules)
    p3 = check_style._watch_priority_from_rule_severity(["README.txt"], rules)

    assert p1 == check_style.WATCH_PRIORITY_NORMAL
    assert p2 == check_style.WATCH_PRIORITY_HIGH
    assert p3 == check_style.WATCH_PRIORITY_NORMAL


def test_watch_priority_combines_rule_severity_and_diff_keywords():
    check_style = _load_check_style_module()
    rules = [
        ("rule_medium.md", ["*.md"], "body", {"severity": "medium"}),
    ]
    target_files = ["notes.md"]
    diff_chunks = {"notes.md": "minor edit"}

    combined = min(
        check_style._watch_priority_from_diff(diff_chunks),
        check_style._watch_priority_from_rule_severity(target_files, rules),
    )
    assert combined == check_style.WATCH_PRIORITY_MEDIUM

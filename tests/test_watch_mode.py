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
        watch_history_ttl_seconds=3600,
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

    def fake_run(cmd, check=False, **kwargs):
        if isinstance(cmd, list) and cmd and cmd[0] != "git":
            calls["run"] += 1
        return argparse.Namespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(check_style, "resolve_target_files", fake_resolve_target_files)
    monkeypatch.setattr(check_style.subprocess, "run", fake_run)
    monkeypatch.setattr(check_style, "_update_watch_priority_stats", lambda root, target_files, priority: None)
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
        watch_history_ttl_seconds=3600,
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


def test_watch_priority_from_recent_queue_uses_highest_severity(tmp_path):
    check_style = _load_check_style_module()
    _results_dir, queue_dir = check_style._violations_dir(tmp_path)
    queue_dir.mkdir(parents=True, exist_ok=True)

    low_id = "1" * 64
    high_id = "2" * 64
    low_path = check_style._queue_state_path(queue_dir, low_id, check_style.ViolationStatus.PENDING, 300)
    high_path = check_style._queue_state_path(queue_dir, high_id, check_style.ViolationStatus.PENDING, 100)

    check_style._write_json_atomically(
        low_path,
        {
            "id": low_id,
            "run_id": "s1",
            "target_file_path": "notes.md",
            "severity": "low",
            "status": "pending",
        },
    )
    check_style._write_json_atomically(
        high_path,
        {
            "id": high_id,
            "run_id": "s1",
            "target_file_path": "notes.md",
            "severity": "high",
            "status": "pending",
        },
    )

    priority = check_style._watch_priority_from_recent_queue(tmp_path, ["notes.md"])
    assert priority == check_style.WATCH_PRIORITY_HIGH


def test_watch_priority_from_recent_queue_returns_normal_without_matches(tmp_path):
    check_style = _load_check_style_module()
    _results_dir, queue_dir = check_style._violations_dir(tmp_path)
    queue_dir.mkdir(parents=True, exist_ok=True)

    other_id = "3" * 64
    other_path = check_style._queue_state_path(queue_dir, other_id, check_style.ViolationStatus.PENDING, 100)
    check_style._write_json_atomically(
        other_path,
        {
            "id": other_id,
            "run_id": "s1",
            "target_file_path": "other.md",
            "severity": "high",
            "status": "pending",
        },
    )

    priority = check_style._watch_priority_from_recent_queue(tmp_path, ["notes.md"])
    assert priority == check_style.WATCH_PRIORITY_NORMAL


def test_watch_priority_from_history_stats_uses_recent_record(tmp_path):
    check_style = _load_check_style_module()
    now = 1_700_000_000.0
    check_style._save_watch_priority_stats(
        tmp_path,
        {
            "version": 1,
            "files": {
                "notes.md": {
                    "last_priority": check_style.WATCH_PRIORITY_HIGH,
                    "last_seen_at": now - 10.0,
                    "seen_count": 3,
                }
            },
        },
    )

    original_time = check_style.time.time
    check_style.time.time = lambda: now
    try:
        priority = check_style._watch_priority_from_history_stats(
            tmp_path,
            ["notes.md"],
            ttl_seconds=3600,
        )
    finally:
        check_style.time.time = original_time
    assert priority == check_style.WATCH_PRIORITY_HIGH


def test_watch_priority_from_history_stats_ignores_expired_record(tmp_path):
    check_style = _load_check_style_module()
    now = 1_700_000_000.0
    check_style._save_watch_priority_stats(
        tmp_path,
        {
            "version": 1,
            "files": {
                "notes.md": {
                    "last_priority": check_style.WATCH_PRIORITY_HIGH,
                    "last_seen_at": now - 4000.0,
                    "seen_count": 3,
                }
            },
        },
    )

    original_time = check_style.time.time
    check_style.time.time = lambda: now
    try:
        priority = check_style._watch_priority_from_history_stats(
            tmp_path,
            ["notes.md"],
            ttl_seconds=3600,
        )
    finally:
        check_style.time.time = original_time
    assert priority == check_style.WATCH_PRIORITY_NORMAL

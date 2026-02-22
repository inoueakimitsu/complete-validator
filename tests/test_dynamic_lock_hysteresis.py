import importlib.util
import sys
from pathlib import Path


def _load_test_harness_module():
    root = Path(__file__).resolve().parents[1]
    tests_dir = root / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    module_path = tests_dir / "test_harness.py"
    spec = importlib.util.spec_from_file_location("test_harness_module", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lock_hysteresis_keeps_locked_rule_allow_before_threshold():
    harness = _load_test_harness_module()
    rule_results = [{"rule": "meeting_rules/security_discussion.md", "status": "deny"}]
    lockable = {"meeting_rules/security_discussion.md"}
    locked = {"meeting_rules/security_discussion.md"}
    streaks = {"meeting_rules/security_discussion.md": 0}

    harness._apply_lock_hysteresis(
        rule_results=rule_results,
        lockable_rules=lockable,
        locked_rules=locked,
        deny_streaks=streaks,
        unlock_hysteresis=2,
    )

    assert rule_results[0]["status"] == "allow"
    assert "meeting_rules/security_discussion.md" in locked
    assert streaks["meeting_rules/security_discussion.md"] == 1


def test_lock_hysteresis_unlocks_on_threshold_and_exposes_deny():
    harness = _load_test_harness_module()
    rule_results = [{"rule": "meeting_rules/security_discussion.md", "status": "deny"}]
    lockable = {"meeting_rules/security_discussion.md"}
    locked = {"meeting_rules/security_discussion.md"}
    streaks = {"meeting_rules/security_discussion.md": 1}

    harness._apply_lock_hysteresis(
        rule_results=rule_results,
        lockable_rules=lockable,
        locked_rules=locked,
        deny_streaks=streaks,
        unlock_hysteresis=2,
    )

    assert rule_results[0]["status"] == "deny"
    assert "meeting_rules/security_discussion.md" not in locked
    assert streaks["meeting_rules/security_discussion.md"] == 0


def test_lock_hysteresis_locks_when_rule_becomes_allow():
    harness = _load_test_harness_module()
    rule_results = [{"rule": "meeting_rules/security_discussion.md", "status": "allow"}]
    lockable = {"meeting_rules/security_discussion.md"}
    locked = set()
    streaks = {}

    harness._apply_lock_hysteresis(
        rule_results=rule_results,
        lockable_rules=lockable,
        locked_rules=locked,
        deny_streaks=streaks,
        unlock_hysteresis=2,
    )

    assert "meeting_rules/security_discussion.md" in locked
    assert streaks["meeting_rules/security_discussion.md"] == 0


def test_unlock_by_change_keyword_immediately_releases_lock():
    harness = _load_test_harness_module()
    locked = {"meeting_rules/security_discussion.md"}
    streaks = {"meeting_rules/security_discussion.md": 1}
    unlock_map = {"meeting_rules/security_discussion.md": ["security", "threat model"]}

    harness._apply_lock_unlock_by_change(
        append_text="Added SECURITY appendix and checklist",
        locked_rules=locked,
        deny_streaks=streaks,
        unlock_on_change_keywords=unlock_map,
        unlock_on_change_symbols={},
    )

    assert "meeting_rules/security_discussion.md" not in locked
    assert streaks["meeting_rules/security_discussion.md"] == 0


def test_unlock_by_change_keyword_does_not_unlock_when_unrelated_change():
    harness = _load_test_harness_module()
    locked = {"meeting_rules/security_discussion.md"}
    streaks = {"meeting_rules/security_discussion.md": 1}
    unlock_map = {"meeting_rules/security_discussion.md": ["security", "threat model"]}

    harness._apply_lock_unlock_by_change(
        append_text="Added participant introductions and schedule",
        locked_rules=locked,
        deny_streaks=streaks,
        unlock_on_change_keywords=unlock_map,
        unlock_on_change_symbols={},
    )

    assert "meeting_rules/security_discussion.md" in locked
    assert streaks["meeting_rules/security_discussion.md"] == 1


def test_unlock_by_change_symbol_releases_lock_when_identifier_matches():
    harness = _load_test_harness_module()
    locked = {"meeting_rules/security_discussion.md"}
    streaks = {"meeting_rules/security_discussion.md": 1}

    harness._apply_lock_unlock_by_change(
        append_text="def validate_token(token):\n    return token.strip()",
        locked_rules=locked,
        deny_streaks=streaks,
        unlock_on_change_keywords={},
        unlock_on_change_symbols={"meeting_rules/security_discussion.md": ["validate_token"]},
    )

    assert "meeting_rules/security_discussion.md" not in locked
    assert streaks["meeting_rules/security_discussion.md"] == 0


def test_unlock_by_change_symbol_does_not_release_on_non_matching_identifier():
    harness = _load_test_harness_module()
    locked = {"meeting_rules/security_discussion.md"}
    streaks = {"meeting_rules/security_discussion.md": 1}

    harness._apply_lock_unlock_by_change(
        append_text="def summarize_notes(text):\n    return text",
        locked_rules=locked,
        deny_streaks=streaks,
        unlock_on_change_keywords={},
        unlock_on_change_symbols={"meeting_rules/security_discussion.md": ["validate_token"]},
    )

    assert "meeting_rules/security_discussion.md" in locked
    assert streaks["meeting_rules/security_discussion.md"] == 1


def test_unlock_by_evidence_terms_releases_lock_when_change_hits_evidence():
    harness = _load_test_harness_module()
    locked = {"meeting_rules/security_discussion.md"}
    streaks = {"meeting_rules/security_discussion.md": 1}
    evidence = {"meeting_rules/security_discussion.md": {"auth", "token"}}

    harness._apply_lock_unlock_by_change(
        append_text="Authentication policy now requires rotating credentials.",
        locked_rules=locked,
        deny_streaks=streaks,
        unlock_on_change_keywords={},
        unlock_on_change_symbols={},
        lock_evidence_terms=evidence,
    )

    assert "meeting_rules/security_discussion.md" not in locked
    assert streaks["meeting_rules/security_discussion.md"] == 0


def test_unlock_by_evidence_terms_keeps_lock_when_change_is_unrelated():
    harness = _load_test_harness_module()
    locked = {"meeting_rules/security_discussion.md"}
    streaks = {"meeting_rules/security_discussion.md": 1}
    evidence = {"meeting_rules/security_discussion.md": {"auth", "token"}}

    harness._apply_lock_unlock_by_change(
        append_text="Added attendee list and next meeting schedule.",
        locked_rules=locked,
        deny_streaks=streaks,
        unlock_on_change_keywords={},
        unlock_on_change_symbols={},
        lock_evidence_terms=evidence,
    )

    assert "meeting_rules/security_discussion.md" in locked
    assert streaks["meeting_rules/security_discussion.md"] == 1


def test_extract_changed_symbols_includes_ast_nodes():
    harness = _load_test_harness_module()
    symbols = harness._extract_changed_symbols(
        "class TokenGuard:\n"
        "    def validate_token(self, token):\n"
        "        return self.policy.check(token)\n"
    )

    assert "TokenGuard" in symbols
    assert "validate_token" in symbols
    assert "policy" in symbols
    assert "check" in symbols


def test_extract_changed_symbols_fallback_on_syntax_error():
    harness = _load_test_harness_module()
    symbols = harness._extract_changed_symbols("validate_token(")

    assert "validate_token" in symbols

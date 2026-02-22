import importlib.util
from pathlib import Path
import pytest


def _load_check_style_module():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "scripts" / "check_style.py"
    spec = importlib.util.spec_from_file_location("check_style", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_rule_config_fallback_when_missing(monkeypatch, tmp_path):
    check_style = _load_check_style_module()
    missing_path = tmp_path / "missing-rule-config.json"
    monkeypatch.setenv("RULE_VALIDATOR_RULE_CONFIG_PATH", str(missing_path))

    loaded = check_style.load_rule_config(tmp_path)

    assert loaded == {"version": 1, "rules": {}, "decision_log": []}


def test_load_rule_config_fallback_when_broken_json(monkeypatch, tmp_path):
    check_style = _load_check_style_module()
    broken_path = tmp_path / "broken-rule-config.json"
    broken_path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("RULE_VALIDATOR_RULE_CONFIG_PATH", str(broken_path))

    loaded = check_style.load_rule_config(tmp_path)

    assert loaded == {"version": 1, "rules": {}, "decision_log": []}


def test_save_rule_config_normalizes_and_roundtrips(monkeypatch, tmp_path):
    check_style = _load_check_style_module()
    target_path = tmp_path / "rule-config.json"
    monkeypatch.setenv("RULE_VALIDATOR_RULE_CONFIG_PATH", str(target_path))

    source = {
        "version": 3,
        "rules": {"r1": {"context_level": "diff"}, "bad": "invalid"},
        "decision_log": [{"decision_id": "abc"}, "invalid"],
    }

    saved_path = check_style.save_rule_config(tmp_path, source)
    loaded = check_style.load_rule_config(tmp_path)

    assert saved_path == target_path
    assert target_path.exists()
    assert loaded["version"] == 3
    assert loaded["rules"] == {"r1": {"context_level": "diff"}}
    assert loaded["decision_log"] == [{"decision_id": "abc"}]


def test_rule_config_default_path_roundtrip(monkeypatch, tmp_path):
    check_style = _load_check_style_module()
    monkeypatch.delenv("RULE_VALIDATOR_RULE_CONFIG_PATH", raising=False)

    source = {"version": 2, "rules": {"r2": {"model": "haiku"}}, "decision_log": []}
    saved_path = check_style.save_rule_config(tmp_path, source)
    loaded = check_style.load_rule_config(tmp_path)

    assert saved_path == tmp_path / ".complete-validator" / "rule-config.json"
    assert saved_path.exists()
    assert loaded["version"] == 2
    assert loaded["rules"] == {"r2": {"model": "haiku"}}
    assert loaded["decision_log"] == []


def test_append_rule_config_decision_persists_audit_log_and_rule_update(monkeypatch, tmp_path):
    check_style = _load_check_style_module()
    target_path = tmp_path / "rule-config.json"
    monkeypatch.setenv("RULE_VALIDATOR_RULE_CONFIG_PATH", str(target_path))

    saved_path, decision = check_style.append_rule_config_decision(
        tmp_path,
        "readable_code/02_naming.md",
        {"model": "haiku", "context_level": "diff"},
        changed_by="auto_tuning",
        reason="shadow run maintained quality with lower cost",
        metrics_snapshot={"f1_current": 0.95, "f1_candidate": 0.95, "cost_ratio": 0.6},
        decision_id="20260222-100000-tune-abc123",
        timestamp="2026-02-22T10:00:00+0900",
    )

    loaded = check_style.load_rule_config(tmp_path)
    assert saved_path == target_path
    assert decision["decision_id"] == "20260222-100000-tune-abc123"
    assert decision["changed_by"] == "auto_tuning"
    assert decision["reason"] == "shadow run maintained quality with lower cost"
    assert decision["timestamp"] == "2026-02-22T10:00:00+0900"
    assert loaded["rules"]["readable_code/02_naming.md"]["model"] == "haiku"
    assert loaded["rules"]["readable_code/02_naming.md"]["context_level"] == "diff"
    assert len(loaded["decision_log"]) == 1
    assert loaded["decision_log"][0]["metrics_snapshot"]["cost_ratio"] == 0.6


def test_append_rule_config_decision_rejects_incomplete_inputs(monkeypatch, tmp_path):
    check_style = _load_check_style_module()
    monkeypatch.setenv("RULE_VALIDATOR_RULE_CONFIG_PATH", str(tmp_path / "rule-config.json"))

    with pytest.raises(ValueError):
        check_style.append_rule_config_decision(
            tmp_path,
            "",
            {"model": "haiku"},
            changed_by="auto_tuning",
            reason="ok",
            metrics_snapshot={"f1": 0.9},
        )

    with pytest.raises(ValueError):
        check_style.append_rule_config_decision(
            tmp_path,
            "readable_code/02_naming.md",
            {"model": "haiku"},
            changed_by="",
            reason="ok",
            metrics_snapshot={"f1": 0.9},
        )

    with pytest.raises(ValueError):
        check_style.append_rule_config_decision(
            tmp_path,
            "readable_code/02_naming.md",
            {"model": "haiku"},
            changed_by="auto_tuning",
            reason="",
            metrics_snapshot={"f1": 0.9},
        )

    with pytest.raises(ValueError):
        check_style.append_rule_config_decision(
            tmp_path,
            "readable_code/02_naming.md",
            {"model": "haiku"},
            changed_by="auto_tuning",
            reason="ok",
            metrics_snapshot="invalid",
        )

import importlib.util
from pathlib import Path


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

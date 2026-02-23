import argparse
import importlib.util
import json
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


def test_persist_shadow_comparison_writes_expected_payload(tmp_path):
    harness = _load_test_harness_module()

    harness.persist_shadow_comparison(
        root=tmp_path,
        scenario="static",
        current_name="baseline",
        current_metrics={"f1": 0.80, "disruption_rate": 0.10},
        current_timing={"wall_time": 2.0, "llm_calls": 20},
        candidate_name="optimized",
        candidate_metrics={"f1": 0.85, "disruption_rate": 0.12},
        candidate_timing={"wall_time": 1.5, "llm_calls": 12},
    )

    out_path = tmp_path / "tests" / "results" / "shadow_static__baseline_vs_optimized.json"
    assert out_path.exists()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["scenario"] == "shadow"
    assert payload["base_scenario"] == "static"
    assert payload["current"]["config"] == "baseline"
    assert payload["candidate"]["config"] == "optimized"
    assert payload["delta"]["f1"] == 0.04999999999999993
    assert payload["delta"]["disruption_rate"] == 0.01999999999999999
    assert payload["delta"]["wall_time"] == -0.5
    assert payload["delta"]["llm_calls"] == -8


def test_main_two_configs_calls_shadow_persist(monkeypatch):
    harness = _load_test_harness_module()
    args = argparse.Namespace(
        scenario="static",
        config=["tests/configs/baseline.json", "tests/configs/optimized.json"],
        fixture=None,
        recorded=True,
        record=False,
        sanitize_recordings=False,
        show_results=None,
        wait_seconds=120,
        max_fixpoint_iterations=3,
        oscillation_limit=1,
        lock_unlock_hysteresis=2,
        approve_shadow_recommendation=False,
        regression_max_drop=0.05,
        regression_max_disruption_increase=0.10,
        regression_scenario="static",
    )

    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(
        harness,
        "resolve_default_configs",
        lambda _args, root: [root / "tests" / "configs" / "baseline.json", root / "tests" / "configs" / "optimized.json"],
    )
    monkeypatch.setattr(
        harness,
        "load_runtime_config_for_recommendation",
        lambda _config_path: {
            "default_model": "haiku",
            "context_level": "smart",
            "batching": True,
            "cache": True,
        },
    )
    monkeypatch.setattr(
        harness,
        "discover_rule_keys_for_recommendation",
        lambda _root: ["readable_code/08_functions.md", "security/01_auth.md"],
    )

    def fake_run_static(config_path, fixture_filter, runner_cfg, recorded, record=False, sanitize_recordings=False):
        if config_path.stem == "baseline":
            return (
                {"f1": 0.80, "disruption_rate": 0.10, "precision": 0.8, "recall": 0.8, "tp": 8, "fp": 2, "fn": 2, "tn": 8},
                {
                    "timing": {"wall_time": 2.0, "llm_calls": 20},
                    "rule_metrics": {
                        "readable_code/08_functions.md": {"f1": 0.70, "disruption_rate": 0.20, "support": 8},
                        "security/01_auth.md": {"f1": 0.90, "disruption_rate": 0.10, "support": 8},
                    },
                },
            )
        return (
            {"f1": 0.85, "disruption_rate": 0.12, "precision": 0.85, "recall": 0.85, "tp": 9, "fp": 2, "fn": 1, "tn": 8},
            {
                "timing": {"wall_time": 1.5, "llm_calls": 12},
                "rule_metrics": {
                    "readable_code/08_functions.md": {"f1": 0.72, "disruption_rate": 0.18, "support": 8},
                    "security/01_auth.md": {"f1": 0.70, "disruption_rate": 0.30, "support": 8},
                },
            },
        )

    monkeypatch.setattr(harness, "run_static", fake_run_static)
    monkeypatch.setattr(harness, "print_comparison", lambda *args, **kwargs: None)
    monkeypatch.setattr(harness, "print_and_persist", lambda *args, **kwargs: None)

    calls = []
    recommendation_calls = []
    decision_calls = []

    def fake_persist_shadow_comparison(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(harness, "persist_shadow_comparison", fake_persist_shadow_comparison)
    monkeypatch.setattr(
        harness,
        "persist_shadow_recommendation",
        lambda **kwargs: recommendation_calls.append(kwargs),
    )
    monkeypatch.setattr(
        harness,
        "persist_shadow_recommendation_decision",
        lambda **kwargs: decision_calls.append(kwargs),
    )

    harness.main()

    assert len(calls) == 1
    assert calls[0]["scenario"] == "static"
    assert calls[0]["current_name"] == "baseline"
    assert calls[0]["candidate_name"] == "optimized"
    assert len(recommendation_calls) == 1
    assert recommendation_calls[0]["scenario"] == "static"
    assert recommendation_calls[0]["current_name"] == "baseline"
    assert recommendation_calls[0]["candidate_name"] == "optimized"
    assert recommendation_calls[0]["rule_recommendations"] == {
        "readable_code/08_functions.md": {
            "model": "haiku",
            "context_level": "smart",
            "batching": True,
            "cache": True,
        }
    }
    assert len(decision_calls) == 1
    assert decision_calls[0]["approve"] is False


def test_evaluate_shadow_recommendation_recommends_when_quality_kept_and_cost_improves():
    harness = _load_test_harness_module()

    recommendation = harness.evaluate_shadow_recommendation(
        current_metrics={"f1": 0.90, "disruption_rate": 0.10},
        candidate_metrics={"f1": 0.89, "disruption_rate": 0.12},
        current_timing={"wall_time": 10.0, "llm_calls": 20},
        candidate_timing={"wall_time": 8.0, "llm_calls": 14},
        max_f1_drop=0.02,
        max_disruption_increase=0.03,
    )

    assert recommendation["adopt_candidate"] is True
    assert recommendation["guardrail_passed"] is True
    assert recommendation["cost_improved"] is True
    assert recommendation["reasons"] == []


def test_evaluate_shadow_recommendation_rejects_when_f1_drop_exceeds_guardrail():
    harness = _load_test_harness_module()

    recommendation = harness.evaluate_shadow_recommendation(
        current_metrics={"f1": 0.90, "disruption_rate": 0.10},
        candidate_metrics={"f1": 0.80, "disruption_rate": 0.08},
        current_timing={"wall_time": 10.0, "llm_calls": 20},
        candidate_timing={"wall_time": 8.0, "llm_calls": 10},
        max_f1_drop=0.02,
        max_disruption_increase=0.03,
    )

    assert recommendation["adopt_candidate"] is False
    assert recommendation["guardrail_passed"] is False
    assert recommendation["cost_improved"] is True
    assert any("F1 dropped" in reason for reason in recommendation["reasons"])


def test_build_rule_recommendations_uses_candidate_runtime_config():
    harness = _load_test_harness_module()
    recommendations = harness.build_rule_recommendations(
        ["readable_code/08_functions.md", "security/01_auth.md"],
        {
            "default_model": "haiku",
            "context_level": "smart",
            "batching": True,
            "cache": False,
        },
    )

    assert recommendations == {
        "readable_code/08_functions.md": {
            "model": "haiku",
            "context_level": "smart",
            "batching": True,
            "cache": False,
        },
        "security/01_auth.md": {
            "model": "haiku",
            "context_level": "smart",
            "batching": True,
            "cache": False,
        },
    }


def test_build_rule_recommendations_filters_by_rule_level_guardrails():
    harness = _load_test_harness_module()
    recommendations = harness.build_rule_recommendations(
        ["readable_code/08_functions.md", "security/01_auth.md", "docs/01_style.md"],
        {
            "default_model": "haiku",
            "context_level": "smart",
            "batching": True,
            "cache": False,
        },
        current_rule_metrics={
            "readable_code/08_functions.md": {"f1": 0.70, "disruption_rate": 0.20, "support": 8},
            "security/01_auth.md": {"f1": 0.90, "disruption_rate": 0.10, "support": 8},
            "docs/01_style.md": {"f1": 0.50, "disruption_rate": 0.05, "support": 1},
        },
        candidate_rule_metrics={
            "readable_code/08_functions.md": {"f1": 0.72, "disruption_rate": 0.18, "support": 8},
            "security/01_auth.md": {"f1": 0.80, "disruption_rate": 0.12, "support": 8},
            "docs/01_style.md": {"f1": 0.90, "disruption_rate": 0.01, "support": 1},
        },
        max_f1_drop=0.01,
        max_disruption_increase=0.01,
        min_support=2,
    )

    assert recommendations == {
        "readable_code/08_functions.md": {
            "model": "haiku",
            "context_level": "smart",
            "batching": True,
            "cache": False,
        }
    }


def test_persist_shadow_recommendation_decision_applies_when_approved(tmp_path):
    harness = _load_test_harness_module()
    recommendation = {
        "adopt_candidate": True,
        "guardrail_passed": True,
        "cost_improved": True,
        "rule_recommendations": {
            "readable_code/08_functions.md": {
                "model": "haiku",
                "context_level": "smart",
                "batching": True,
                "cache": True,
            }
        },
        "deltas": {
            "f1_drop": 0.0,
            "disruption_increase": 0.0,
            "wall_time": -1.0,
            "llm_calls": -5,
        },
        "thresholds": {"max_f1_drop": 0.05, "max_disruption_increase": 0.1},
        "reasons": [],
    }

    harness.persist_shadow_recommendation_decision(
        root=tmp_path,
        scenario="static",
        current_name="baseline",
        candidate_name="optimized",
        recommendation=recommendation,
        approve=True,
    )

    out_path = (
        tmp_path
        / "tests"
        / "results"
        / "shadow_recommendation_decision_static__baseline_vs_optimized.json"
    )
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["decision"]["status"] == "applied"

    config_path = tmp_path / ".complete-validator" / "rule-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert "__harness__/selected_profile" in config["rules"]
    assert config["rules"]["__harness__/selected_profile"]["selected_config"] == "optimized"
    assert "readable_code/08_functions.md" in config["rules"]
    assert config["rules"]["readable_code/08_functions.md"]["model"] == "haiku"
    assert config["rules"]["readable_code/08_functions.md"]["context_level"] == "smart"
    assert len(config["decision_log"]) == 1


def test_persist_shadow_recommendation_decision_stays_pending_without_approval(tmp_path):
    harness = _load_test_harness_module()
    recommendation = {
        "adopt_candidate": True,
        "guardrail_passed": True,
        "cost_improved": True,
        "deltas": {
            "f1_drop": 0.0,
            "disruption_increase": 0.0,
            "wall_time": -1.0,
            "llm_calls": -5,
        },
        "thresholds": {"max_f1_drop": 0.05, "max_disruption_increase": 0.1},
        "reasons": [],
    }

    harness.persist_shadow_recommendation_decision(
        root=tmp_path,
        scenario="static",
        current_name="baseline",
        candidate_name="optimized",
        recommendation=recommendation,
        approve=False,
    )

    out_path = (
        tmp_path
        / "tests"
        / "results"
        / "shadow_recommendation_decision_static__baseline_vs_optimized.json"
    )
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["decision"]["status"] == "pending_approval"
    assert not (tmp_path / ".complete-validator" / "rule-config.json").exists()


def test_build_rule_recommendations_uses_evidence_metrics_and_excludes_rejected_evidence():
    harness = _load_test_harness_module()
    recommendations = harness.build_rule_recommendations(
        ["readable_code/08_functions.md", "security/01_auth.md"],
        {
            "default_model": "haiku",
            "context_level": "smart",
            "batching": True,
            "cache": False,
        },
        current_rule_metrics={
            "readable_code/08_functions.md": {"f1": 0.8, "disruption_rate": 0.1, "support": 10},
            "security/01_auth.md": {"f1": 0.8, "disruption_rate": 0.1, "support": 10},
        },
        candidate_rule_metrics={
            "readable_code/08_functions.md": {"f1": 0.8, "disruption_rate": 0.1, "support": 10},
            "security/01_auth.md": {"f1": 0.8, "disruption_rate": 0.1, "support": 10},
        },
        current_evidence_metrics={
            "readable_code/08_functions.md#expected_unsatisfied:auth-token": {
                "f1": 0.70,
                "disruption_rate": 0.20,
                "support": 3,
            },
            "security/01_auth.md#expected_unsatisfied:access-control": {
                "f1": 0.95,
                "disruption_rate": 0.05,
                "support": 3,
            },
        },
        candidate_evidence_metrics={
            "readable_code/08_functions.md#expected_unsatisfied:auth-token": {
                "f1": 0.75,
                "disruption_rate": 0.15,
                "support": 3,
            },
            "security/01_auth.md#expected_unsatisfied:access-control": {
                "f1": 0.70,
                "disruption_rate": 0.20,
                "support": 3,
            },
        },
        max_f1_drop=0.01,
        max_disruption_increase=0.01,
        min_support=2,
        min_evidence_support=2,
    )

    assert recommendations == {
        "readable_code/08_functions.md": {
            "model": "haiku",
            "context_level": "smart",
            "batching": True,
            "cache": False,
        }
    }
def test_build_rule_recommendations_falls_back_to_rule_metrics_when_evidence_insufficient():
    harness = _load_test_harness_module()
    recommendations = harness.build_rule_recommendations(
        ["readable_code/08_functions.md"],
        {
            "default_model": "haiku",
            "context_level": "smart",
            "batching": True,
            "cache": False,
        },
        current_rule_metrics={"readable_code/08_functions.md": {"f1": 0.70, "disruption_rate": 0.20, "support": 8}},
        candidate_rule_metrics={"readable_code/08_functions.md": {"f1": 0.72, "disruption_rate": 0.18, "support": 8}},
        current_evidence_metrics={
            "readable_code/08_functions.md#expected_unsatisfied:tiny": {
                "f1": 0.70,
                "disruption_rate": 0.20,
                "support": 1,
            }
        },
        candidate_evidence_metrics={
            "readable_code/08_functions.md#expected_unsatisfied:tiny": {
                "f1": 0.72,
                "disruption_rate": 0.18,
                "support": 1,
            }
        },
        max_f1_drop=0.01,
        max_disruption_increase=0.01,
        min_support=2,
        min_evidence_support=2,
    )

    assert "readable_code/08_functions.md" in recommendations

def test_build_evidence_comparison_writes_raw_metrics():
    harness = _load_test_harness_module()
    comparison = harness.build_evidence_comparison(
        {
            "readable_code/08_functions.md#expected_unsatisfied:auth-token": {
                "tp": 3,
                "fp": 1,
                "fn": 0,
                "tn": 4,
                "support": 4,
                "f1": 0.86,
                "disruption_rate": 0.2,
            }
        },
        {
            "readable_code/08_functions.md#expected_unsatisfied:auth-token": {
                "tp": 2,
                "fp": 2,
                "fn": 1,
                "tn": 3,
                "support": 4,
                "f1": 0.57,
                "disruption_rate": 0.4,
            }
        },
        max_f1_drop=0.05,
        max_disruption_increase=0.1,
        min_evidence_support=1,
        current_evidence_samples={
            "readable_code/08_functions.md#expected_unsatisfied:auth-token": [
                {
                    "fixture": "case_01",
                    "file": "app.py",
                    "expected": "unsatisfied",
                    "predicted": "unsatisfied",
                    "message": "token check missing",
                }
            ]
        },
        candidate_evidence_samples={
            "readable_code/08_functions.md#expected_unsatisfied:auth-token": [
                {
                    "fixture": "case_01",
                    "file": "app.py",
                    "expected": "unsatisfied",
                    "predicted": "satisfied",
                    "message": "missed token check",
                }
            ]
        },
    )
    assert len(comparison) == 1
    row = comparison[0]
    assert row["evidence_key"] == "readable_code/08_functions.md#expected_unsatisfied:auth-token"
    assert row["rule_key"] == "readable_code/08_functions.md"
    assert row["current"]["support"] == 4
    assert row["candidate"]["support"] == 4
    assert row["delta"]["f1_drop"] == 0.29000000000000004
    assert row["delta"]["disruption_increase"] == 0.2
    assert row["threshold_ref"]["min_evidence_support"] == 1
    assert row["samples"]["current"][0]["fixture"] == "case_01"
    assert row["samples"]["candidate"][0]["predicted"] == "satisfied"


def test_persist_shadow_recommendation_includes_evidence_comparison(tmp_path):
    harness = _load_test_harness_module()
    harness.persist_shadow_recommendation(
        root=tmp_path,
        scenario="static",
        current_name="baseline",
        current_metrics={"f1": 0.9, "disruption_rate": 0.1},
        current_timing={"wall_time": 10.0, "llm_calls": 20},
        candidate_name="optimized",
        candidate_metrics={"f1": 0.9, "disruption_rate": 0.1},
        candidate_timing={"wall_time": 8.0, "llm_calls": 15},
        rule_recommendations={"readable_code/08_functions.md": {"model": "haiku"}},
        evidence_comparison=[
            {
                "evidence_key": "readable_code/08_functions.md#expected_unsatisfied:auth-token",
                "rule_key": "readable_code/08_functions.md",
                "current": {"support": 3, "f1": 0.8, "disruption_rate": 0.2, "tp": 0, "fp": 0, "fn": 0, "tn": 0},
                "candidate": {"support": 3, "f1": 0.7, "disruption_rate": 0.3, "tp": 0, "fp": 0, "fn": 0, "tn": 0},
                "delta": {"f1_drop": 0.1, "disruption_increase": 0.1},
                "threshold_ref": {
                    "max_f1_drop": 0.05,
                    "max_disruption_increase": 0.1,
                    "min_evidence_support": 2,
                },
            }
        ],
        max_f1_drop=0.05,
        max_disruption_increase=0.1,
    )
    out_path = (
        tmp_path
        / "tests"
        / "results"
        / "shadow_recommendation_static__baseline_vs_optimized.json"
    )
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert "evidence_summary" not in payload
    assert payload["evidence_comparison"][0]["evidence_key"] == (
        "readable_code/08_functions.md#expected_unsatisfied:auth-token"
    )

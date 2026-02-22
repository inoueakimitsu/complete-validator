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

    def fake_run_static(config_path, fixture_filter, runner_cfg, recorded, record=False, sanitize_recordings=False):
        if config_path.stem == "baseline":
            return (
                {"f1": 0.80, "disruption_rate": 0.10, "precision": 0.8, "recall": 0.8, "tp": 8, "fp": 2, "fn": 2, "tn": 8},
                {"timing": {"wall_time": 2.0, "llm_calls": 20}},
            )
        return (
            {"f1": 0.85, "disruption_rate": 0.12, "precision": 0.85, "recall": 0.85, "tp": 9, "fp": 2, "fn": 1, "tn": 8},
            {"timing": {"wall_time": 1.5, "llm_calls": 12}},
        )

    monkeypatch.setattr(harness, "run_static", fake_run_static)
    monkeypatch.setattr(harness, "print_comparison", lambda *args, **kwargs: None)
    monkeypatch.setattr(harness, "print_and_persist", lambda *args, **kwargs: None)

    calls = []

    def fake_persist_shadow_comparison(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(harness, "persist_shadow_comparison", fake_persist_shadow_comparison)

    harness.main()

    assert len(calls) == 1
    assert calls[0]["scenario"] == "static"
    assert calls[0]["current_name"] == "baseline"
    assert calls[0]["candidate_name"] == "optimized"

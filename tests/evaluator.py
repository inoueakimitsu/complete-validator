"""Compute precision / recall / f1 and compare with annotation expected results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fixture_manager import read_annotations, read_dynamic_annotations
from runner import CheckResult


@dataclass
class EvalMetrics:
    fixture: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p = self.precision
        r = self.recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0


def _predict_for_rule(results: list[dict[str, Any]], rule_name: str) -> str:
    for item in results:
        if item.get("rule") == rule_name:
            status = str(item.get("status", "allow")).lower()
            if status == "deny":
                return "unsatisfied"
            if status == "error":
                return "unsatisfied"
            return "satisfied"
    return "satisfied"


def _normalize_expectation(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in {"allow", "satisfy", "satisfied"}:
        return "satisfied"
    if value in {"deny", "unsatisfied", "violation"}:
        return "unsatisfied"
    if value == "irrelevant":
        return "irrelevant"
    return value or "satisfied"


def _expected_for_annotation(annotation: dict[str, Any], step: int | None) -> str:
    expected_by_step = annotation.get("expected_by_step")
    if step is not None and isinstance(expected_by_step, dict):
        raw = expected_by_step.get(str(step))
        if isinstance(raw, str):
            return _normalize_expectation(raw)
    return _normalize_expectation(str(annotation.get("expected", "satisfied")))


def evaluate_fixture(fixture, result: CheckResult, step: int | None = None) -> EvalMetrics:
    metrics = EvalMetrics(fixture=fixture.name)
    if hasattr(fixture, "steps"):
        annotations = read_dynamic_annotations(fixture)
    else:
        annotations = read_annotations(fixture)
    for ann in annotations:
        expected = _expected_for_annotation(ann, step)
        predicted = _predict_for_rule(result.rule_results, ann.get("rule", ""))

        if expected == "irrelevant":
            continue
        if expected == "satisfied" and predicted == "satisfied":
            metrics.true_negatives += 1
        elif expected == "satisfied" and predicted == "unsatisfied":
            metrics.false_positives += 1
        elif expected == "unsatisfied" and predicted == "satisfied":
            metrics.false_negatives += 1
        elif expected == "unsatisfied" and predicted == "unsatisfied":
            metrics.true_positives += 1
    return metrics

def aggregate_metrics(metrics: list[EvalMetrics]) -> dict[str, float]:
    agg = EvalMetrics(fixture="aggregate")
    for m in metrics:
        agg.true_positives += m.true_positives
        agg.false_positives += m.false_positives
        agg.false_negatives += m.false_negatives
        agg.true_negatives += m.true_negatives

    return {
        "precision": agg.precision,
        "recall": agg.recall,
        "f1": agg.f1,
        "total_violation_gold": agg.true_positives + agg.false_negatives,
        "tp": agg.true_positives,
        "fp": agg.false_positives,
        "fn": agg.false_negatives,
        "tn": agg.true_negatives,
    }

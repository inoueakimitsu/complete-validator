"""Reporting helpers for harness output."""

from __future__ import annotations

from typing import Any


def print_summary(label: str, metrics: dict[str, float], timing: dict[str, float], call_counts: dict[str, int] | None = None) -> None:
    print(f"\n=== {label} ===")
    print(f"Precision: {metrics['precision']:.4f}")
    print(f"Recall:    {metrics['recall']:.4f}")
    print(f"F1:        {metrics['f1']:.4f}")
    print(f"TP: {metrics['tp']} FP: {metrics['fp']} FN: {metrics['fn']} TN: {metrics['tn']}")
    if timing:
        print(f"Wall clock time (s): {timing.get('wall_time', 0.0):.3f}")
        print(f"LLM calls: {timing.get('llm_calls', 0)}")
    if call_counts:
        print(f"Cache hit: {call_counts.get('cache_hit', 0)}")


def print_comparison(name_a: str, metrics_a: dict[str, float], name_b: str, metrics_b: dict[str, float]) -> None:
    print(f"\n=== {name_a} vs {name_b} ===")
    for key in ["precision", "recall", "f1"]:
        av = metrics_a[key]
        bv = metrics_b[key]
        sign = "+" if bv >= av else "-"
        delta = bv - av
        print(f"{key.upper():<9} {av: .4f} -> {bv: .4f} ({sign}{delta:.4f})")


def emit_summary(payload: dict[str, Any], path: str) -> None:
    import json
    from pathlib import Path

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"results written: {out}")

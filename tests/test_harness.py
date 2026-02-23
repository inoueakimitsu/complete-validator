"""E2E harness entrypoint for validator optimization experiments."""

from __future__ import annotations

import argparse
import ast
import json
import keyword
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from evaluator import aggregate_metrics, evaluate_fixture
from fixture_manager import FixtureManager
from reporter import emit_summary, print_comparison, print_summary
from runner import CheckResult, RunnerConfig


def _harness_rules_dir(root: Path) -> Path:
    return root / "tests" / "fixtures" / "harness_plugin"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validator harness")
    parser.add_argument(
        "--scenario",
        choices=["static", "dynamic", "regression"],
        default="static",
    )
    parser.add_argument("--config", nargs="+", help="config json path")
    parser.add_argument("--fixture", action="append", default=None, help="fixture filter")
    parser.add_argument("--recorded", action="store_true", help="use recorded responses")
    parser.add_argument(
        "--record",
        action="store_true",
        help="run live checks and write recorded_<config>.json for static fixtures",
    )
    parser.add_argument(
        "--sanitize-recordings",
        action="store_true",
        help="sanitize recorded payloads by removing raw stdout/stderr and detailed messages",
    )
    parser.add_argument("--show-results", dest="show_results", help="show results path")
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=120,
        help="stream timeout for dynamic fixtures",
    )
    parser.add_argument(
        "--max-fixpoint-iterations",
        type=int,
        default=3,
        help="maximum recheck iterations per dynamic step",
    )
    parser.add_argument(
        "--oscillation-limit",
        type=int,
        default=1,
        help="number of repeated signatures allowed before manual_review_required",
    )
    parser.add_argument(
        "--lock-unlock-hysteresis",
        type=int,
        default=2,
        help="consecutive deny count required to unlock lock_on_satisfy rules",
    )
    parser.add_argument(
        "--regression-max-drop",
        type=float,
        default=0.05,
        help="maximum allowed F1 drop in regression before failing",
    )
    parser.add_argument(
        "--regression-max-disruption-increase",
        type=float,
        default=0.10,
        help="maximum allowed disruption_rate increase in regression before failing",
    )
    parser.add_argument(
        "--regression-scenario",
        choices=["static", "dynamic"],
        default="static",
        help="scenario pair to compare in regression",
    )
    return parser.parse_args()


def resolve_default_configs(args: argparse.Namespace, root: Path) -> list[Path]:
    if args.config:
        return [Path(c) for c in args.config]
    return [root / "tests" / "configs" / "baseline.json"]


def _plugin_dir_for_mode(root: Path, mode: str) -> Path:
    optimized_dir = root / "tests" / "fixtures" / "harness_plugin_optimized"
    if mode == "optimized" and optimized_dir.exists():
        return optimized_dir
    return _harness_rules_dir(root)


def _make_check_env(config_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["RULE_VALIDATOR_CONFIG_PATH"] = str(config_path)
    return env


def _to_check_result(fixture_name: str, entries: list[dict], stream_id: str) -> CheckResult:
    rule_results = []
    for entry in entries:
        rule_results.append(
            {
                "rule": entry.get("rule", ""),
                "file": entry.get("file"),
                "status": entry.get("status", "allow"),
                "message": entry.get("message", ""),
            }
        )
    return CheckResult(
        fixture=fixture_name,
        run_id=stream_id,
        exit_code=0,
        stdout="",
        stderr="",
        elapsed_ms=0.0,
        rule_results=rule_results,
        raw={"entries": entries, "stream_id": stream_id},
    )


def _entries_signature(entries: list[dict]) -> str:
    compact: list[tuple[str, str, str]] = []
    for entry in entries:
        compact.append(
            (
                str(entry.get("rule", "")),
                str(entry.get("file", "")),
                str(entry.get("status", "allow")).lower(),
            )
        )
    compact.sort()
    return json.dumps(compact, ensure_ascii=False)


def _apply_lock_hysteresis(
    rule_results: list[dict],
    lockable_rules: set[str],
    locked_rules: set[str],
    deny_streaks: dict[str, int],
    unlock_hysteresis: int,
    lock_evidence_terms: dict[str, set[str]] | None = None,
) -> None:
    if not rule_results or not lockable_rules:
        return
    threshold = max(1, int(unlock_hysteresis))
    by_rule: dict[str, list[int]] = {}
    for idx, item in enumerate(rule_results):
        rule_name = str(item.get("rule", ""))
        by_rule.setdefault(rule_name, []).append(idx)

    for rule_name, indexes in by_rule.items():
        if rule_name not in lockable_rules:
            continue
        statuses = [str(rule_results[i].get("status", "allow")).lower() for i in indexes]
        has_allow = any(status == "allow" for status in statuses)
        has_deny = any(status == "deny" for status in statuses)

        if rule_name in locked_rules:
            if has_deny:
                next_streak = int(deny_streaks.get(rule_name, 0)) + 1
                deny_streaks[rule_name] = next_streak
                if next_streak < threshold:
                    for i in indexes:
                        rule_results[i]["status"] = "allow"
                else:
                    locked_rules.discard(rule_name)
                    deny_streaks[rule_name] = 0
                    if lock_evidence_terms is not None:
                        lock_evidence_terms.pop(rule_name, None)
            else:
                deny_streaks[rule_name] = 0
                for i in indexes:
                    rule_results[i]["status"] = "allow"
            continue

        if has_allow and not has_deny:
            locked_rules.add(rule_name)
            deny_streaks[rule_name] = 0
            if lock_evidence_terms is not None:
                lock_evidence_terms[rule_name] = _collect_lock_evidence_terms(
                    rule_name=rule_name,
                    rule_results=rule_results,
                    indexes=indexes,
                )


def _apply_lock_unlock_by_change(
    append_text: str,
    locked_rules: set[str],
    deny_streaks: dict[str, int],
    unlock_on_change_keywords: dict[str, list[str]],
    unlock_on_change_symbols: dict[str, list[str]],
    lock_evidence_terms: dict[str, set[str]] | None = None,
) -> None:
    if not locked_rules:
        return
    changed = (append_text or "").lower()
    if not changed:
        return
    changed_identifiers = _extract_changed_symbols(append_text or "")
    changed_terms = _extract_changed_terms(append_text or "")
    for rule_name in list(locked_rules):
        keywords = unlock_on_change_keywords.get(rule_name, [])
        symbols = unlock_on_change_symbols.get(rule_name, [])
        keyword_match = any(keyword in changed for keyword in keywords)
        symbol_match = any(symbol in changed_identifiers for symbol in symbols)
        evidence_terms = (
            {_normalize_semantic_term(term) for term in lock_evidence_terms.get(rule_name, set())}
            if isinstance(lock_evidence_terms, dict)
            else set()
        )
        evidence_match = bool(evidence_terms and evidence_terms.intersection(changed_terms))
        if keyword_match or symbol_match or evidence_match:
            locked_rules.discard(rule_name)
            deny_streaks[rule_name] = 0
            if isinstance(lock_evidence_terms, dict):
                lock_evidence_terms.pop(rule_name, None)


def _extract_changed_symbols(append_text: str) -> set[str]:
    symbols: set[str] = set()
    for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", append_text or ""):
        if token and not keyword.iskeyword(token):
            symbols.add(token)

    try:
        tree = ast.parse(append_text or "")
    except SyntaxError:
        return symbols

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            symbols.add(node.name)
        elif isinstance(node, ast.AsyncFunctionDef):
            symbols.add(node.name)
        elif isinstance(node, ast.ClassDef):
            symbols.add(node.name)
        elif isinstance(node, ast.Name):
            symbols.add(node.id)
        elif isinstance(node, ast.Attribute):
            symbols.add(node.attr)
    return symbols


SEMANTIC_EQUIVALENTS = {
    "authentication": "auth",
    "authenticate": "auth",
    "authorization": "auth",
    "authorise": "auth",
    "authorize": "auth",
    "login": "auth",
    "credentials": "token",
    "credential": "token",
    "tokens": "token",
}
SEMANTIC_STOPWORDS = {
    "the",
    "and",
    "with",
    "from",
    "into",
    "this",
    "that",
    "added",
    "requires",
    "meeting",
    "notes",
}


def _normalize_semantic_term(term: str) -> str:
    lowered = str(term or "").strip().lower()
    if not lowered:
        return ""
    return SEMANTIC_EQUIVALENTS.get(lowered, lowered)


def _extract_changed_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for token in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", text or ""):
        normalized = _normalize_semantic_term(token)
        if not normalized or normalized in SEMANTIC_STOPWORDS:
            continue
        terms.add(normalized)
    return terms


def _collect_lock_evidence_terms(
    rule_name: str,
    rule_results: list[dict],
    indexes: list[int],
) -> set[str]:
    terms: set[str] = set()
    terms.update(_extract_changed_terms(rule_name.replace("/", " ")))
    for idx in indexes:
        item = rule_results[idx]
        message = str(item.get("message", ""))
        file_path = str(item.get("file", ""))
        terms.update(_extract_changed_terms(message))
        terms.update(_extract_changed_terms(file_path.replace("/", " ")))
    return terms


def _sanitize_recorded_payload(payload: dict) -> dict:
    sanitized = dict(payload)
    sanitized["stdout"] = "[SANITIZED]"
    sanitized["stderr"] = "[SANITIZED]"

    sanitized_rules: list[dict] = []
    for item in payload.get("rule_results", []):
        if not isinstance(item, dict):
            continue
        sanitized_rules.append(
            {
                "rule": item.get("rule", ""),
                "status": item.get("status", "allow"),
                "file": item.get("file"),
                "message": "[SANITIZED]",
            }
        )
    sanitized["rule_results"] = sanitized_rules
    sanitized["raw"] = {"sanitized": True}
    return sanitized


def run_static(
    config_path: Path,
    fixture_filter: list[str] | None,
    runner_cfg: RunnerConfig,
    recorded: bool,
    record: bool = False,
    sanitize_recordings: bool = False,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    fm = FixtureManager(runner_cfg.root / "tests" / "fixtures")
    fixtures = fm.list_static_fixtures(fixture_filter)
    mode = config_path.stem
    plugin_dir = _plugin_dir_for_mode(runner_cfg.root, mode)

    results = []
    timing = {
        "mode": "recorded" if recorded else "live",
        "wall_time": 0.0,
        "wall_time_total": 0.0,
        "wall_time_live_check": 0.0,
        "wall_time_recorded_replay": 0.0,
        "llm_calls": 0,
    }
    all_rule_results = []

    from runner import run_check_once

    for fixture in fixtures:
        temp_repo: Path | None = None
        fixture_repo = fixture.repo_path
        if recorded:
            fixture_repo = fixture.path
        else:
            temp_repo = _init_static_repo(fixture)
            fixture_repo = temp_repo
        run_result = run_check_once(
            fixture_repo,
            plugin_dir=plugin_dir,
            config=runner_cfg,
            mode=mode,
            use_recorded=recorded,
        )
        elapsed_seconds = run_result.elapsed_ms / 1000.0
        timing["wall_time"] += elapsed_seconds
        timing["wall_time_total"] += elapsed_seconds
        if recorded:
            timing["wall_time_recorded_replay"] += elapsed_seconds
        else:
            timing["wall_time_live_check"] += elapsed_seconds
        timing["llm_calls"] += max(len(run_result.rule_results), 1)
        metrics = evaluate_fixture(fixture, run_result)
        results.append(metrics)
        all_rule_results.append(
            {
                "fixture": fixture.name,
                "rule_results": run_result.rule_results,
                "rule_count": len(run_result.rule_results),
                "exit_code": run_result.exit_code,
            },
        )
        if record:
            recorded_path = fixture.path / f"recorded_{mode}.json"
            recorded_payload = {
                "fixture": fixture.name,
                "mode": mode,
                "generated_at": int(time.time()),
                "exit_code": run_result.exit_code,
                "stdout": run_result.stdout,
                "stderr": run_result.stderr,
                "rule_results": run_result.rule_results,
                "raw": run_result.raw,
            }
            if sanitize_recordings:
                recorded_payload = _sanitize_recorded_payload(recorded_payload)
            recorded_path.write_text(
                json.dumps(recorded_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if temp_repo is not None:
            shutil.rmtree(temp_repo, ignore_errors=True)

    agg = aggregate_metrics(results)
    details = {
        "fixtures": all_rule_results,
        "metric": agg,
        "timing": timing,
    }
    return agg, details


def _wait_stream_complete(
    repo_dir: Path,
    stream_id: str,
    timeout_seconds: int,
) -> Path:
    status_path = (
        repo_dir
        / ".complete-validator"
        / "stream-results"
        / stream_id
        / "status.json"
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if status_path.exists():
            data = json.loads(status_path.read_text(encoding="utf-8"))
            if data.get("status") == "completed":
                return status_path
        time.sleep(0.2)
    _terminate_stream_worker(stream_id)
    raise TimeoutError(f"stream {stream_id} did not finish in {timeout_seconds}s")


def _terminate_stream_worker(stream_id: str) -> None:
    pattern = f"--stream-worker --stream-id {stream_id}"
    find_proc = subprocess.run(
        ["pgrep", "-f", "--", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    if find_proc.returncode != 0:
        return
    for line in find_proc.stdout.splitlines():
        pid = line.strip()
        if not pid.isdigit():
            continue
        child_proc = subprocess.run(
            ["pgrep", "-P", pid],
            capture_output=True,
            text=True,
            check=False,
        )
        if child_proc.returncode == 0:
            for child in child_proc.stdout.splitlines():
                child_pid = child.strip()
                if not child_pid.isdigit():
                    continue
                subprocess.run(
                    ["kill", child_pid],
                    capture_output=True,
                    text=True,
                    check=False,
                )
        subprocess.run(
            ["kill", pid],
            capture_output=True,
            text=True,
            check=False,
        )


def _run_stream_once(
    repo_dir: Path,
    runner_cfg: RunnerConfig,
    plugin_dir: Path,
    timeout_seconds: int,
) -> tuple[str, list[dict]]:
    cmd = [
        "python3",
        str(runner_cfg.check_script),
        "--stream",
        "--plugin-dir",
        str(plugin_dir),
    ]
    proc = subprocess.run(
        cmd,
        cwd=repo_dir,
        capture_output=True,
        text=True,
        env=_make_check_env(runner_cfg.config_path),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"stream start failed: {proc.stderr.strip() or proc.stdout.strip()}")

    stream_id = proc.stdout.strip().splitlines()[-1].strip()
    _wait_stream_complete(repo_dir, stream_id, timeout_seconds)

    results_dir = repo_dir / ".complete-validator" / "stream-results" / stream_id / "results"
    entries: list[dict] = []
    if results_dir.exists():
        for result_file in sorted(results_dir.glob("*.json")):
            data = json.loads(result_file.read_text(encoding="utf-8"))
            entries.append(
                {
                    "id": None,
                    "rule": data.get("rule_name", ""),
                    "file": data.get("file_path"),
                    "status": data.get("status", "allow"),
                    "message": data.get("message", ""),
                }
            )

    list_cmd = [
        "python3",
        str(runner_cfg.check_script),
        "--list-violations",
        stream_id,
        "--plugin-dir",
        str(plugin_dir),
    ]
    list_proc = subprocess.run(
        list_cmd,
        cwd=repo_dir,
        capture_output=True,
        text=True,
        env=_make_check_env(runner_cfg.config_path),
    )
    if list_proc.returncode != 0:
        raise RuntimeError(f"list-violations failed: {list_proc.stderr.strip()}")
    payload = json.loads(list_proc.stdout)
    pending_entries = payload.get("entries", [])
    for pending in pending_entries:
        for item in entries:
            if item.get("rule") == pending.get("rule") and item.get("file") == pending.get("target_file_path"):
                item["id"] = pending.get("id")
                item["status"] = "deny"
                break
    return stream_id, entries


def _claim_and_resolve_all(
    repo_dir: Path,
    runner_cfg: RunnerConfig,
    plugin_dir: Path,
    stream_id: str,
    entries: list[dict],
) -> None:
    for entry in entries:
        violation_id = entry.get("id")
        if not violation_id:
            continue
        claim_cmd = [
            "python3",
            str(runner_cfg.check_script),
            "--claim",
            stream_id,
            violation_id,
            "--plugin-dir",
            str(plugin_dir),
        ]
        claim_proc = subprocess.run(
            claim_cmd,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            env=_make_check_env(runner_cfg.config_path),
        )
        if claim_proc.returncode != 0:
            continue
        claim_payload = json.loads(claim_proc.stdout)
        resolve_cmd = [
            "python3",
            str(runner_cfg.check_script),
            "--resolve",
            stream_id,
            violation_id,
            "--claim-uuid",
            claim_payload.get("claim_uuid", ""),
            "--state-version",
            str(claim_payload.get("state_version", 0)),
            "--plugin-dir",
            str(plugin_dir),
        ]
        subprocess.run(
            resolve_cmd,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            env=_make_check_env(runner_cfg.config_path),
        )


def _init_fixture_repo(root: Path, fixture) -> Path:
    work_dir = Path(tempfile.mkdtemp(prefix="cv-harness-"))
    target = work_dir / fixture.target_file
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture.path / fixture.target_file, target)

    subprocess.run(["git", "init"], cwd=work_dir, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=validator-harness",
            "-c",
            "user.email=validator-harness@example.com",
            "add",
            ".",
        ],
        cwd=work_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=validator-harness",
            "-c",
            "user.email=validator-harness@example.com",
            "commit",
            "-m",
            "initial fixture state",
        ],
        cwd=work_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return work_dir


def _init_static_repo(fixture) -> Path:
    work_dir = Path(tempfile.mkdtemp(prefix="cv-harness-static-"))
    shutil.copytree(fixture.repo_path, work_dir, dirs_exist_ok=True)

    subprocess.run(["git", "init"], cwd=work_dir, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=validator-harness",
            "-c",
            "user.email=validator-harness@example.com",
            "add",
            ".",
        ],
        cwd=work_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=validator-harness",
            "-c",
            "user.email=validator-harness@example.com",
            "commit",
            "-m",
            "initial fixture state",
        ],
        cwd=work_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return work_dir


def run_dynamic(
    runner_cfg: RunnerConfig,
    fixture_filter: list[str] | None,
    wait_seconds: int,
    max_fixpoint_iterations: int = 3,
    oscillation_limit: int = 1,
    lock_unlock_hysteresis: int = 2,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    fm = FixtureManager(runner_cfg.root / "tests" / "fixtures")
    dynamic_fixtures = fm.list_dynamic_fixtures(fixture_filter)
    if not dynamic_fixtures:
        raise RuntimeError("no dynamic fixtures")

    mode = runner_cfg.config_path.stem
    plugin_dir = _plugin_dir_for_mode(runner_cfg.root, mode)
    metrics_list = []
    all_rule_results: list[dict] = []
    total_ms = 0.0

    iteration_cap = max(1, int(max_fixpoint_iterations))
    oscillation_cap = max(1, int(oscillation_limit))

    for fixture in dynamic_fixtures:
        work_dir = _init_fixture_repo(runner_cfg.root, fixture)
        start_ms = time.perf_counter()
        lockable_rules = {
            str(ann.get("rule"))
            for ann in fixture.annotations
            if isinstance(ann, dict) and ann.get("lock_on_satisfy")
        }
        unlock_on_change_keywords: dict[str, list[str]] = {}
        unlock_on_change_symbols: dict[str, list[str]] = {}
        for ann in fixture.annotations:
            if not isinstance(ann, dict):
                continue
            rule_name = str(ann.get("rule", ""))
            raw_keywords = ann.get("unlock_on_change_keywords", [])
            raw_symbols = ann.get("unlock_on_change_symbols", [])
            if not rule_name or not isinstance(raw_keywords, list):
                raw_keywords = []
            normalized_keywords = [str(item).strip().lower() for item in raw_keywords if str(item).strip()]
            if normalized_keywords:
                unlock_on_change_keywords[rule_name] = normalized_keywords
            if isinstance(raw_symbols, list):
                normalized_symbols = [str(item).strip() for item in raw_symbols if str(item).strip()]
                if normalized_symbols:
                    unlock_on_change_symbols[rule_name] = normalized_symbols
        locked_rules: set[str] = set()
        lock_deny_streaks: dict[str, int] = {}
        lock_evidence_terms: dict[str, set[str]] = {}
        try:
            target_path = work_dir / fixture.target_file
            for step_item in fixture.steps:
                append_text = str(step_item.get("append", ""))
                with target_path.open("a", encoding="utf-8") as handle:
                    handle.write(append_text)
                _apply_lock_unlock_by_change(
                    append_text=append_text,
                    locked_rules=locked_rules,
                    deny_streaks=lock_deny_streaks,
                    unlock_on_change_keywords=unlock_on_change_keywords,
                    unlock_on_change_symbols=unlock_on_change_symbols,
                    lock_evidence_terms=lock_evidence_terms,
                )

                stream_id, entries = _run_stream_once(work_dir, runner_cfg, plugin_dir, wait_seconds)
                _claim_and_resolve_all(work_dir, runner_cfg, plugin_dir, stream_id, entries)

                final_stream_id = stream_id
                final_entries = entries
                fixpoint_iterations = 1
                oscillation_hits = 0
                signatures_seen = {_entries_signature(final_entries)}
                manual_review_required = False
                while fixpoint_iterations < iteration_cap:
                    has_deny = any(str(e.get("status", "allow")).lower() == "deny" for e in final_entries)
                    if not has_deny:
                        break
                    next_stream_id, next_entries = _run_stream_once(work_dir, runner_cfg, plugin_dir, wait_seconds)
                    _claim_and_resolve_all(work_dir, runner_cfg, plugin_dir, next_stream_id, next_entries)
                    final_stream_id = next_stream_id
                    final_entries = next_entries
                    fixpoint_iterations += 1
                    signature = _entries_signature(final_entries)
                    if signature in signatures_seen:
                        oscillation_hits += 1
                        if oscillation_hits >= oscillation_cap:
                            manual_review_required = True
                            break
                    else:
                        signatures_seen.add(signature)

                step_no = int(step_item.get("step", 0))
                result = _to_check_result(fixture.name, final_entries, final_stream_id)

                _apply_lock_hysteresis(
                    rule_results=result.rule_results,
                    lockable_rules=lockable_rules,
                    locked_rules=locked_rules,
                    deny_streaks=lock_deny_streaks,
                    unlock_hysteresis=lock_unlock_hysteresis,
                    lock_evidence_terms=lock_evidence_terms,
                )

                metrics = evaluate_fixture(fixture, result, step=step_no)
                metrics_list.append(metrics)

                all_rule_results.append(
                    {
                        "fixture": fixture.name,
                        "step": step_no,
                        "stream_id": final_stream_id,
                        "fixpoint_iterations": fixpoint_iterations,
                        "manual_review_required": manual_review_required,
                        "oscillation_hits": oscillation_hits,
                        "locked_rules": sorted(locked_rules),
                        "lock_evidence_terms": {k: sorted(v) for k, v in lock_evidence_terms.items()},
                        "lock_deny_streaks": dict(lock_deny_streaks),
                        "rule_results": result.rule_results,
                    },
                )
            total_ms += (time.perf_counter() - start_ms) * 1000.0
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    agg = aggregate_metrics(metrics_list)
    details = {
        "fixtures": all_rule_results,
        "metric": agg,
        "timing": {
            "mode": "live",
            "wall_time": total_ms / 1000.0,
            "wall_time_total": total_ms / 1000.0,
            "wall_time_live_check": total_ms / 1000.0,
            "wall_time_recorded_replay": 0.0,
            "llm_calls": len(all_rule_results),
        },
    }
    return agg, details


def run_regression(
    root: Path,
    max_drop: float,
    scenario: str,
    max_disruption_increase: float,
) -> None:
    results_root = root / "tests" / "results"
    if not results_root.exists():
        raise RuntimeError("results directory not found")
    dirs = sorted([p for p in results_root.iterdir() if p.is_dir()], key=lambda p: p.name)
    if len(dirs) < 2:
        raise RuntimeError("not enough run results for regression")

    preferred_prev = results_root / f"{scenario}__baseline"
    preferred_latest = results_root / f"{scenario}__optimized"
    if preferred_prev.exists() and preferred_latest.exists():
        dirs = [preferred_prev, preferred_latest]
    else:
        dirs = [dirs[-2], dirs[-1]]

    def load_summary(d: Path) -> dict:
        summary_path = d / "summary.json"
        if not summary_path.exists():
            raise RuntimeError(f"summary missing: {summary_path}")
        return json.loads(summary_path.read_text(encoding="utf-8"))

    previous = load_summary(dirs[-2])
    latest = load_summary(dirs[-1])
    prev_metrics = previous.get("metrics", {})
    latest_metrics = latest.get("metrics", {})
    print(f"compare {dirs[-2].name} -> {dirs[-1].name}")
    print_comparison(
        dirs[-2].name,
        prev_metrics,
        dirs[-1].name,
        latest_metrics,
    )
    prev_f1 = float(prev_metrics.get("f1", 0.0))
    latest_f1 = float(latest_metrics.get("f1", 0.0))
    f1_drop = prev_f1 - latest_f1
    prev_disruption = float(prev_metrics.get("disruption_rate", 0.0))
    latest_disruption = float(latest_metrics.get("disruption_rate", 0.0))
    disruption_increase = latest_disruption - prev_disruption
    ok_f1 = f1_drop <= max_drop
    ok_disruption = disruption_increase <= max_disruption_increase
    ok = ok_f1 and ok_disruption
    emit_summary(
        {
            "scenario": "regression",
            "regression_scenario": scenario,
            "previous": prev_metrics,
            "latest": latest_metrics,
            "previous_dir": dirs[-2].name,
            "latest_dir": dirs[-1].name,
            "f1_drop": f1_drop,
            "max_allowed_drop": max_drop,
            "disruption_increase": disruption_increase,
            "max_allowed_disruption_increase": max_disruption_increase,
            "ok_f1": ok_f1,
            "ok_disruption": ok_disruption,
            "ok": ok,
        },
        str(results_root / f"regression_{scenario}.json"),
    )
    if not ok:
        reasons: list[str] = []
        if not ok_f1:
            reasons.append(
                f"F1 dropped by {f1_drop:.4f} (> {max_drop:.4f})"
            )
        if not ok_disruption:
            reasons.append(
                f"disruption increased by {disruption_increase:.4f} (> {max_disruption_increase:.4f})"
            )
        raise RuntimeError(f"regression failed: {'; '.join(reasons)}")


def print_and_persist(
    scenario: str,
    config_name: str,
    metrics: dict[str, float],
    timing: dict[str, float],
    details: dict[str, dict[str, float]],
    root: Path,
) -> None:
    print_summary(f"Scenario:{scenario} Config:{config_name}", metrics, timing)
    objective_proxies = {
        "c_monetary_proxy": {
            "llm_calls": timing.get("llm_calls", 0),
            "model": config_name,
        },
        "c_time_proxy": {
            "wall_time": timing.get("wall_time", 0.0),
            "mode": timing.get("mode", "unknown"),
        },
        "c_false_negative_proxy": {
            "fn": metrics.get("fn", 0),
            "recall": metrics.get("recall", 0.0),
            "f1": metrics.get("f1", 0.0),
        },
        "c_disruption_proxy": {
            "disruption_rate": metrics.get("disruption_rate", 0.0),
            "fp": metrics.get("fp", 0),
            "tn": metrics.get("tn", 0),
        },
    }
    output = {
        "scenario": scenario,
        "config": config_name,
        "metrics": metrics,
        "timing": timing,
        "objective_proxies": objective_proxies,
        "details": details,
    }
    out_dir = root / "tests" / "results" / f"{scenario}__{config_name}"
    emit_summary(output, str(out_dir / "summary.json"))


def persist_shadow_comparison(
    root: Path,
    scenario: str,
    current_name: str,
    current_metrics: dict[str, float],
    current_timing: dict[str, float],
    candidate_name: str,
    candidate_metrics: dict[str, float],
    candidate_timing: dict[str, float],
) -> None:
    f1_delta = float(candidate_metrics.get("f1", 0.0)) - float(current_metrics.get("f1", 0.0))
    disruption_delta = float(candidate_metrics.get("disruption_rate", 0.0)) - float(
        current_metrics.get("disruption_rate", 0.0)
    )
    wall_time_delta = float(candidate_timing.get("wall_time", 0.0)) - float(
        current_timing.get("wall_time", 0.0)
    )
    llm_calls_delta = int(candidate_timing.get("llm_calls", 0)) - int(current_timing.get("llm_calls", 0))
    payload = {
        "scenario": "shadow",
        "base_scenario": scenario,
        "current": {
            "config": current_name,
            "metrics": current_metrics,
            "timing": current_timing,
        },
        "candidate": {
            "config": candidate_name,
            "metrics": candidate_metrics,
            "timing": candidate_timing,
        },
        "delta": {
            "f1": f1_delta,
            "disruption_rate": disruption_delta,
            "wall_time": wall_time_delta,
            "llm_calls": llm_calls_delta,
        },
    }
    out_path = root / "tests" / "results" / f"shadow_{scenario}__{current_name}_vs_{candidate_name}.json"
    emit_summary(payload, str(out_path))


def evaluate_shadow_recommendation(
    current_metrics: dict[str, float],
    candidate_metrics: dict[str, float],
    current_timing: dict[str, float],
    candidate_timing: dict[str, float],
    *,
    max_f1_drop: float,
    max_disruption_increase: float,
) -> dict:
    f1_drop = float(current_metrics.get("f1", 0.0)) - float(candidate_metrics.get("f1", 0.0))
    disruption_increase = float(candidate_metrics.get("disruption_rate", 0.0)) - float(
        current_metrics.get("disruption_rate", 0.0)
    )
    wall_time_delta = float(candidate_timing.get("wall_time", 0.0)) - float(
        current_timing.get("wall_time", 0.0)
    )
    llm_calls_delta = int(candidate_timing.get("llm_calls", 0)) - int(current_timing.get("llm_calls", 0))

    reasons: list[str] = []
    guardrail_passed = True
    if f1_drop > float(max_f1_drop):
        guardrail_passed = False
        reasons.append(f"F1 dropped by {f1_drop:.4f} (> {float(max_f1_drop):.4f})")
    if disruption_increase > float(max_disruption_increase):
        guardrail_passed = False
        reasons.append(
            "disruption increased by "
            f"{disruption_increase:.4f} (> {float(max_disruption_increase):.4f})"
        )

    cost_improved = wall_time_delta < 0.0 or llm_calls_delta < 0
    if not cost_improved:
        reasons.append("no cost improvement: wall_time and llm_calls did not improve")

    return {
        "adopt_candidate": bool(guardrail_passed and cost_improved),
        "guardrail_passed": bool(guardrail_passed),
        "cost_improved": bool(cost_improved),
        "deltas": {
            "f1_drop": f1_drop,
            "disruption_increase": disruption_increase,
            "wall_time": wall_time_delta,
            "llm_calls": llm_calls_delta,
        },
        "thresholds": {
            "max_f1_drop": float(max_f1_drop),
            "max_disruption_increase": float(max_disruption_increase),
        },
        "reasons": reasons,
    }


def persist_shadow_recommendation(
    root: Path,
    scenario: str,
    current_name: str,
    current_metrics: dict[str, float],
    current_timing: dict[str, float],
    candidate_name: str,
    candidate_metrics: dict[str, float],
    candidate_timing: dict[str, float],
    *,
    max_f1_drop: float,
    max_disruption_increase: float,
) -> None:
    recommendation = evaluate_shadow_recommendation(
        current_metrics=current_metrics,
        candidate_metrics=candidate_metrics,
        current_timing=current_timing,
        candidate_timing=candidate_timing,
        max_f1_drop=max_f1_drop,
        max_disruption_increase=max_disruption_increase,
    )
    payload = {
        "scenario": "shadow_recommendation",
        "base_scenario": scenario,
        "current_config": current_name,
        "candidate_config": candidate_name,
        "recommendation": recommendation,
    }
    out_path = (
        root / "tests" / "results" / f"shadow_recommendation_{scenario}__{current_name}_vs_{candidate_name}.json"
    )
    emit_summary(payload, str(out_path))


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent

    if args.show_results:
        p = Path(args.show_results)
        if not p.exists():
            raise SystemExit(f"results not found: {p}")
        print(p.read_text(encoding="utf-8"))
        return

    if args.record and args.recorded:
        raise SystemExit("--record and --recorded cannot be used together")
    if args.scenario != "static" and args.recorded:
        raise SystemExit("--recorded is supported only for static scenario")
    if args.scenario != "static" and args.record:
        raise SystemExit("--record is supported only for static scenario")

    config_paths = resolve_default_configs(args, root)
    if args.scenario == "regression":
        run_regression(
            root,
            args.regression_max_drop,
            args.regression_scenario,
            args.regression_max_disruption_increase,
        )
        return

    if args.scenario == "dynamic":
        runner_cfg = RunnerConfig(
            config_path=config_paths[0],
            check_script=root / "scripts" / "check_style.py",
            root=root,
        )
        metrics, details = run_dynamic(
            runner_cfg,
            args.fixture,
            args.wait_seconds,
            max_fixpoint_iterations=args.max_fixpoint_iterations,
            oscillation_limit=args.oscillation_limit,
            lock_unlock_hysteresis=args.lock_unlock_hysteresis,
        )
        print_and_persist(
            scenario=args.scenario,
            config_name=config_paths[0].stem,
            metrics=metrics,
            timing=details.get("timing", {"wall_time": 0.0, "llm_calls": 0}),
            details=details,
            root=root,
        )
        return

    if len(config_paths) == 1:
        runner_cfg = RunnerConfig(
            config_path=config_paths[0],
            check_script=root / "scripts" / "check_style.py",
            root=root,
        )
        metrics, details = run_static(
            config_paths[0],
            args.fixture,
            runner_cfg,
            args.recorded,
            record=args.record,
            sanitize_recordings=args.sanitize_recordings,
        )
        timing = details.get("timing", {"wall_time": 0.0, "llm_calls": 0})
        print_and_persist(
            scenario=args.scenario,
            config_name=config_paths[0].stem,
            metrics=metrics,
            timing=timing,
            details=details,
            root=root,
        )
        return

    baseline_cfg = RunnerConfig(
        config_path=config_paths[0],
        check_script=root / "scripts" / "check_style.py",
        root=root,
    )
    optimized_cfg = RunnerConfig(
        config_path=config_paths[1],
        check_script=root / "scripts" / "check_style.py",
        root=root,
    )

    baseline, base_detail = run_static(
        config_paths[0],
        args.fixture,
        baseline_cfg,
        args.recorded,
        record=args.record,
        sanitize_recordings=args.sanitize_recordings,
    )
    optimized, opt_detail = run_static(
        config_paths[1],
        args.fixture,
        optimized_cfg,
        args.recorded,
        record=args.record,
        sanitize_recordings=args.sanitize_recordings,
    )
    print_comparison(config_paths[0].stem, baseline, config_paths[1].stem, optimized)

    print_and_persist(
        args.scenario,
        config_paths[0].stem,
        baseline,
        base_detail.get("timing", {}),
        base_detail,
        root,
    )
    print_and_persist(
        args.scenario,
        config_paths[1].stem,
        optimized,
        opt_detail.get("timing", {}),
        opt_detail,
        root,
    )
    persist_shadow_comparison(
        root=root,
        scenario=args.scenario,
        current_name=config_paths[0].stem,
        current_metrics=baseline,
        current_timing=base_detail.get("timing", {}),
        candidate_name=config_paths[1].stem,
        candidate_metrics=optimized,
        candidate_timing=opt_detail.get("timing", {}),
    )
    persist_shadow_recommendation(
        root=root,
        scenario=args.scenario,
        current_name=config_paths[0].stem,
        current_metrics=baseline,
        current_timing=base_detail.get("timing", {}),
        candidate_name=config_paths[1].stem,
        candidate_metrics=optimized,
        candidate_timing=opt_detail.get("timing", {}),
        max_f1_drop=args.regression_max_drop,
        max_disruption_increase=args.regression_max_disruption_increase,
    )


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, RuntimeError, TimeoutError) as exc:
        raise SystemExit(str(exc))

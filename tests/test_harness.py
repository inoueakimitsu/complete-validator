"""E2E harness entrypoint for validator optimization experiments."""

from __future__ import annotations

import argparse
import json
import os
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
    parser.add_argument("--show-results", dest="show_results", help="show results path")
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=120,
        help="stream timeout for dynamic fixtures",
    )
    parser.add_argument(
        "--regression-max-drop",
        type=float,
        default=0.05,
        help="maximum allowed F1 drop in regression before failing",
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


def run_static(
    config_path: Path,
    fixture_filter: list[str] | None,
    runner_cfg: RunnerConfig,
    recorded: bool,
    record: bool = False,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    fm = FixtureManager(runner_cfg.root / "tests" / "fixtures")
    fixtures = fm.list_static_fixtures(fixture_filter)
    mode = config_path.stem
    plugin_dir = _plugin_dir_for_mode(runner_cfg.root, mode)

    results = []
    timing = {"wall_time": 0.0, "llm_calls": 0}
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
        timing["wall_time"] += run_result.elapsed_ms / 1000.0
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
    raise TimeoutError(f"stream {stream_id} did not finish in {timeout_seconds}s")


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

    for fixture in dynamic_fixtures:
        work_dir = _init_fixture_repo(runner_cfg.root, fixture)
        start_ms = time.perf_counter()
        lockable_rules = {
            str(ann.get("rule"))
            for ann in fixture.annotations
            if isinstance(ann, dict) and ann.get("lock_on_satisfy")
        }
        locked_rules: set[str] = set()
        try:
            target_path = work_dir / fixture.target_file
            for step_item in fixture.steps:
                append_text = str(step_item.get("append", ""))
                with target_path.open("a", encoding="utf-8") as handle:
                    handle.write(append_text)

                stream_id, entries = _run_stream_once(work_dir, runner_cfg, plugin_dir, wait_seconds)
                step_no = int(step_item.get("step", 0))
                result = _to_check_result(fixture.name, entries, stream_id)

                for item in result.rule_results:
                    rule_name = str(item.get("rule", ""))
                    if rule_name in locked_rules:
                        item["status"] = "allow"
                for item in result.rule_results:
                    rule_name = str(item.get("rule", ""))
                    if rule_name in lockable_rules and str(item.get("status", "allow")).lower() == "allow":
                        locked_rules.add(rule_name)

                metrics = evaluate_fixture(fixture, result, step=step_no)
                metrics_list.append(metrics)

                all_rule_results.append(
                    {
                        "fixture": fixture.name,
                        "step": step_no,
                        "stream_id": stream_id,
                        "rule_results": result.rule_results,
                    },
                )
                _claim_and_resolve_all(work_dir, runner_cfg, plugin_dir, stream_id, entries)
            total_ms += (time.perf_counter() - start_ms) * 1000.0
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    agg = aggregate_metrics(metrics_list)
    details = {
        "fixtures": all_rule_results,
        "metric": agg,
        "timing": {"wall_time": total_ms / 1000.0, "llm_calls": len(all_rule_results)},
    }
    return agg, details


def run_regression(root: Path, max_drop: float, scenario: str) -> None:
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
    ok = f1_drop <= max_drop
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
            "ok": ok,
        },
        str(results_root / f"regression_{scenario}.json"),
    )
    if not ok:
        raise RuntimeError(
            f"regression failed: F1 dropped by {f1_drop:.4f} (> {max_drop:.4f})"
        )


def print_and_persist(
    scenario: str,
    config_name: str,
    metrics: dict[str, float],
    timing: dict[str, float],
    details: dict[str, dict[str, float]],
    root: Path,
) -> None:
    print_summary(f"Scenario:{scenario} Config:{config_name}", metrics, timing)
    output = {
        "scenario": scenario,
        "config": config_name,
        "metrics": metrics,
        "timing": timing,
        "details": details,
    }
    out_dir = root / "tests" / "results" / f"{scenario}__{config_name}"
    emit_summary(output, str(out_dir / "summary.json"))


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
        run_regression(root, args.regression_max_drop, args.regression_scenario)
        return

    if args.scenario == "dynamic":
        runner_cfg = RunnerConfig(
            config_path=config_paths[0],
            check_script=root / "scripts" / "check_style.py",
            root=root,
        )
        metrics, details = run_dynamic(runner_cfg, args.fixture, args.wait_seconds)
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
    )
    optimized, opt_detail = run_static(
        config_paths[1],
        args.fixture,
        optimized_cfg,
        args.recorded,
        record=args.record,
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


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, RuntimeError, TimeoutError) as exc:
        raise SystemExit(str(exc))

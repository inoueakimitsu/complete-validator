"""Execution helpers for check_style and recorded responses."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re


@dataclass
class CheckResult:
    fixture: str
    run_id: str
    exit_code: int
    stdout: str
    stderr: str
    elapsed_ms: float
    rule_results: list[dict[str, Any]]
    raw: dict[str, Any]


@dataclass
class RunnerConfig:
    config_path: Path
    check_script: Path
    root: Path


def _normalize_status(message: str) -> str:
    lower = message.lower()
    if "[action required]" in lower or "no violations found" in lower:
        return "allow"
    if "error" in lower and "denied" not in lower:
        return "error"
    if "violation" in lower and "deny" in lower:
        return "deny"
    return "allow"


def _parse_rule_results(stdout: str, stderr: str) -> list[dict[str, Any]]:
    merged = (stdout or "") + "\n" + (stderr or "")
    pattern = r"\[Rule:\s*(?P<rule>[^|\]]+)\s*\|\s*File:\s*(?P<file>[^\]]+)\]"
    matches = list(re.finditer(pattern, merged))
    if not matches:
        return []

    parsed: list[dict[str, Any]] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(merged)
        block = merged[start:end]
        block_lower = block.lower()
        has_no_violation = "no violations found." in block_lower
        has_action_required = "[action required]" in block_lower
        has_violation_cue = (
            "violation found" in block_lower
            or "violations found" in block_lower
            or "fix the violations above" in block_lower
        )
        status = "allow"
        if has_no_violation:
            status = "allow"
        elif has_action_required or has_violation_cue:
            status = "deny"
        parsed.append(
            {
                "rule": match.group("rule").strip(),
                "status": status,
                "file": match.group("file").strip(),
                "message": match.group(0),
            }
        )
    return parsed


def run_recorded_response(recorded_path: Path) -> tuple[int, str, str]:
    raw = json.loads(recorded_path.read_text(encoding="utf-8"))
    return int(raw.get("exit_code", 0)), raw.get("stdout", ""), raw.get("stderr", "")


def run_check_once(
    fixture_dir: Path,
    plugin_dir: Path,
    config: RunnerConfig,
    mode: str = "baseline",
    use_recorded: bool = False,
) -> CheckResult:
    start = time.perf_counter()
    run_id = f"{mode}__{int(time.time())}"
    recorded = fixture_dir / f"recorded_{mode}.json"

    if use_recorded:
        if not recorded.exists():
            raise FileNotFoundError(
                f"recorded response not found: {recorded}. "
                "recorded mode does not fall back to live execution."
            )
        exit_code, stdout, stderr = run_recorded_response(recorded)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        raw = json.loads(recorded.read_text(encoding="utf-8"))
        return CheckResult(
            fixture=str(fixture_dir),
            run_id=run_id,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            elapsed_ms=elapsed_ms,
            rule_results=raw.get("rule_results", []),
            raw=raw,
        )

    cmd = [
        "python3",
        str(config.check_script),
        "--full-scan",
        "--plugin-dir",
        str(plugin_dir),
    ]
    env = os.environ.copy()
    env["RULE_VALIDATOR_CONFIG_PATH"] = str(config.config_path)

    proc = subprocess.run(
        cmd,
        cwd=fixture_dir,
        capture_output=True,
        text=True,
        env=env,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    output = {
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "config_path": str(config.config_path),
    }
    rule_results = _parse_rule_results(stdout, stderr)

    if not rule_results:
        status = "allow" if proc.returncode == 0 else "error"
        rule_results = [{"rule": "global", "status": status, "message": stdout or stderr}]

    combined_output = f"{stdout}\n{stderr}"
    if "No tracked files found." in combined_output:
        raise RuntimeError(
            "harness execution produced 'No tracked files found.'; "
            "fixture repository initialization is invalid."
        )

    return CheckResult(
        fixture=str(fixture_dir),
        run_id=run_id,
        exit_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        elapsed_ms=elapsed_ms,
        rule_results=rule_results,
        raw=output,
    )

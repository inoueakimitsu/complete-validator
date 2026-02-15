#!/usr/bin/env python3
"""Style checker using Claude AI.

Checks files against rules defined in rules/*.md.
Supports two modes:
  - working (default): checks unstaged changes (for on-demand use)
  - staged (--staged):  checks staged changes (for commit hooks)

Always allows the commit — violations are reported via systemMessage
so the Claude Code agent can fix them.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path


def run_git(*args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def detect_project_dir() -> Path:
    """Detect the project directory using git rev-parse --show-toplevel."""
    toplevel = run_git("rev-parse", "--show-toplevel")
    if not toplevel:
        return Path.cwd()
    return Path(toplevel)


def get_diff(staged: bool) -> str:
    """Get the diff (staged or working)."""
    if staged:
        return run_git("diff", "--cached")
    return run_git("diff")


def get_changed_files(staged: bool) -> list[str]:
    """Get list of changed files (excluding deleted)."""
    args = ["diff", "--name-only", "--diff-filter=d"]
    if staged:
        args.insert(1, "--cached")
    output = run_git(*args)
    return output.splitlines() if output else []


def get_file_content(path: str, staged: bool) -> str:
    """Get file content (staged version or working copy)."""
    if staged:
        return run_git("show", f":{path}")
    return Path(path).read_text(encoding="utf-8")


def parse_frontmatter(content: str) -> tuple[dict | None, str]:
    """Parse YAML frontmatter from rule file content.

    Returns (frontmatter_dict, body) if frontmatter exists,
    or (None, content) if no frontmatter.
    """
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return None, content

    raw = match.group(1).strip()
    body = content[match.end():]

    frontmatter = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        key_value = line.split(":", 1)
        if len(key_value) != 2:
            continue
        key = key_value[0].strip()
        value = key_value[1].strip()
        try:
            frontmatter[key] = json.loads(value)
        except json.JSONDecodeError:
            frontmatter[key] = value

    return frontmatter, body


def load_rules_with_targets(project_dir: Path) -> tuple[list[tuple[str, list[str], str]], list[str]]:
    """Load rule files with their target patterns from frontmatter.

    Returns
    -------
    tuple[list[tuple[str, list[str], str]], list[str]]
        (rules, warnings) where rules is a list of (filename, patterns, body)
        and warnings is a list of warning messages for files without frontmatter.
    """
    rules_dir = project_dir / "rules"
    if not rules_dir.exists():
        return [], []

    rules = []
    warnings = []
    for md_file in sorted(rules_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(content)

        if frontmatter is None or "applies_to" not in frontmatter:
            warnings.append(
                f"ルールファイル {md_file.name} に `applies_to` フロントマターがありません。追記してください。"
            )
            continue

        patterns = frontmatter["applies_to"]
        if isinstance(patterns, str):
            patterns = [patterns]

        rules.append((md_file.name, patterns, body))

    return rules, warnings


def match_files_to_rules(
    rules: list[tuple[str, list[str], str]],
    changed_files: list[str],
) -> dict[str, list[tuple[str, str]]]:
    """Match changed files to applicable rules.

    Returns a dict mapping each file path to a list of (rule_name, rule_body).
    Only files that match at least one rule are included.
    """
    file_rules: dict[str, list[tuple[str, str]]] = {}
    for file_path in changed_files:
        filename = os.path.basename(file_path)
        for rule_name, patterns, body in rules:
            if any(fnmatch(filename, pat) for pat in patterns):
                file_rules.setdefault(file_path, []).append((rule_name, body))
    return file_rules


def compute_cache_key(diff: str, rules_content: str) -> str:
    """Compute SHA256 hash of diff + rules for caching."""
    content = diff + "\n---RULES---\n" + rules_content
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_cache(cache_path: Path) -> dict:
    """Load cache from disk."""
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_cache(cache_path: Path, cache: dict) -> None:
    """Save cache to disk."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def run_claude_check(prompt: str) -> str:
    """Run claude -p with the given prompt and return the response."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    result = subprocess.run(
        ["claude", "-p"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
    )
    if result.returncode != 0:
        return f"[Style check error] claude exited with code {result.returncode}: {result.stderr.strip()}"
    return result.stdout.strip()


def build_prompt(
    file_rules: dict[str, list[tuple[str, str]]],
    files: dict[str, str],
    diff: str,
) -> str:
    """Build the prompt for Claude rule checking."""
    # Group rules by pattern set for readable sections
    pattern_groups: dict[str, list[str]] = {}
    for file_path, rule_list in file_rules.items():
        ext = os.path.splitext(file_path)[1]
        key = f"*{ext}" if ext else os.path.basename(file_path)
        for rule_name, rule_body in rule_list:
            pattern_groups.setdefault(key, [])
            if rule_name not in pattern_groups[key]:
                pattern_groups[key].append(rule_name)

    # Collect all unique rule bodies keyed by rule name
    rule_bodies: dict[str, str] = {}
    for rule_list in file_rules.values():
        for rule_name, rule_body in rule_list:
            if rule_name not in rule_bodies:
                rule_bodies[rule_name] = rule_body

    parts = [
        "You are a reviewer. Check the following files against the applicable rules.",
        "Report ONLY actual violations found in the files. Be specific: state the file, line, and which rule is violated.",
        "If there are no violations, respond with exactly: 'No violations found.'",
        "",
    ]

    # Rules sections grouped by file pattern
    for pattern, rule_names in sorted(pattern_groups.items()):
        parts.append(f"=== RULES FOR {pattern} FILES ===")
        for rule_name in rule_names:
            parts.append(f"--- {rule_name} ---")
            parts.append(rule_bodies[rule_name])
            parts.append("")
        parts.append("")

    parts.append("=== CHANGED FILES ===")
    for path, content in files.items():
        parts.append(f"--- {path} ---")
        parts.append(content)
        parts.append("")

    parts.append("=== DIFF ===")
    parts.append(diff)

    return "\n".join(parts)


def output_result(decision: str, message: str = "") -> None:
    """Output hook result as JSON to stdout."""
    result = {"decision": decision}
    if message:
        result["systemMessage"] = message
    print(json.dumps(result))


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Style checker using Claude AI."
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Check staged changes (for commit hooks). Default: check working changes.",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Base directory for rules/ and cache. Default: auto-detect via git rev-parse --show-toplevel.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    staged = args.staged
    project_dir = args.project_dir if args.project_dir else detect_project_dir()
    cache_path = project_dir / ".complete-validator" / "cache.json"

    # Get diff
    diff = get_diff(staged)
    if not diff:
        sys.exit(0)

    # Get changed files
    changed_files = get_changed_files(staged)
    if not changed_files:
        sys.exit(0)

    # Load rules with frontmatter
    rules, warnings = load_rules_with_targets(project_dir)

    # Output warnings for rule files without frontmatter
    if warnings and not rules:
        output_result("allow", "[Style Check]\n" + "\n".join(warnings))
        sys.exit(0)

    if not rules:
        sys.exit(0)

    # Match files to rules
    file_rules = match_files_to_rules(rules, changed_files)
    if not file_rules:
        # No changed files match any rule patterns
        if warnings:
            output_result("allow", "[Style Check]\n" + "\n".join(warnings))
        sys.exit(0)

    # Compute all rules content for cache key
    all_rules_content = "\n\n---\n\n".join(body for _, _, body in rules)
    cache_key = compute_cache_key(diff, all_rules_content)
    cache = load_cache(cache_path)

    if cache_key in cache:
        cached_message = cache[cache_key]
        if cached_message:
            output_result("allow", cached_message)
        sys.exit(0)

    # Get file contents for matched files
    files: dict[str, str] = {}
    for file_path in file_rules:
        try:
            content = get_file_content(file_path, staged)
        except (OSError, UnicodeDecodeError):
            continue
        if content:
            files[file_path] = content

    if not files:
        sys.exit(0)

    # Build prompt and run Claude
    prompt = build_prompt(file_rules, files, diff)

    try:
        response = run_claude_check(prompt)
    except subprocess.TimeoutExpired:
        output_result("allow", "[Style check] Timed out waiting for Claude response.")
        sys.exit(0)
    except Exception as e:
        output_result("allow", f"[Style check] Error: {e}")
        sys.exit(0)

    # Cache and output result
    has_violations = "no violations found" not in response.lower()
    message = f"[Style Check Result]\n{response}"
    if warnings:
        message += "\n\n[Warning]\n" + "\n".join(warnings)
    if has_violations:
        message += "\n\n[Action Required]\nFix the violations above and retry the commit. Repeat until all violations are resolved."
    output_result("allow", message)

    cache[cache_key] = message
    save_cache(cache_path, cache)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        output_result("allow", f"[Style check] Unexpected error: {e}")
        sys.exit(0)

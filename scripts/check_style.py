#!/usr/bin/env python3
"""Style checker using Claude AI.

Checks files against rules defined in rules/*.md.
Supports two modes:
  - working (default): checks unstaged changes (for on-demand use)
  - staged (--staged):  checks staged changes (for commit hooks)

Violations are denied (commit blocked) so the agent must fix them.
False positives can be suppressed via .complete-validator/suppressions.md.
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


PROMPT_VERSION = "2"


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


def load_suppressions(project_dir: Path) -> str:
    """Load suppressions from .complete-validator/suppressions.md in the git toplevel.

    Returns the file content, or empty string if the file doesn't exist.
    """
    git_toplevel = run_git("rev-parse", "--show-toplevel")
    if not git_toplevel:
        return ""
    suppressions_path = Path(git_toplevel) / ".complete-validator" / "suppressions.md"
    if not suppressions_path.exists():
        return ""
    try:
        return suppressions_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def compute_cache_key(diff: str, rules_content: str, suppressions: str = "") -> str:
    """Compute SHA256 hash of prompt version + diff + rules + suppressions for caching."""
    content = PROMPT_VERSION + "\n---RULES---\n" + rules_content + "\n---DIFF---\n" + diff + "\n---SUPPRESSIONS---\n" + suppressions
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


def split_diff_by_file(diff: str) -> dict[str, str]:
    """Split a unified diff into per-file chunks.

    Parses on 'diff --git a/... b/...' boundaries.
    Returns a dict mapping file path to its diff chunk.
    Falls back to empty dict if parsing fails.
    """
    chunks: dict[str, str] = {}
    current_path: str | None = None
    current_lines: list[str] = []

    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            # Flush previous chunk
            if current_path is not None:
                chunks[current_path] = "".join(current_lines)
            # Extract b/ path: 'diff --git a/foo b/bar' -> 'bar'
            parts = line.strip().split(" b/", 1)
            current_path = parts[1] if len(parts) == 2 else None
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush last chunk
    if current_path is not None:
        chunks[current_path] = "".join(current_lines)

    return chunks


def extract_rule_headings(rule_body: str) -> list[str]:
    """Extract ## headings from a rule body for the checklist."""
    headings = []
    for line in rule_body.splitlines():
        if line.startswith("## "):
            headings.append(line[3:].strip())
    return headings


def build_prompt(
    file_rules: dict[str, list[tuple[str, str]]],
    files: dict[str, str],
    diff: str,
    suppressions: str = "",
) -> str:
    """Build the prompt for Claude rule checking.

    Uses a per-file interleaved structure:
      System instructions -> Rules Checklist -> per-file (rules, diff, full content) -> Suppressions -> Reminder
    """
    # Collect all unique rule headings for the checklist
    all_headings: list[str] = []
    seen_rules: set[str] = set()
    for rule_list in file_rules.values():
        for rule_name, rule_body in rule_list:
            if rule_name not in seen_rules:
                seen_rules.add(rule_name)
                all_headings.extend(extract_rule_headings(rule_body))

    # Split diff into per-file chunks
    diff_chunks = split_diff_by_file(diff)

    parts = [
        "You are a strict style reviewer. You MUST check every rule listed for each file. Do not skip any rule.",
        "The diff is the primary check target. The full file content is provided for context only.",
        "If you are uncertain whether something is a violation, report it with a note that it needs confirmation.",
        "Be specific: state the file, line, and which rule is violated.",
        "If there are no violations, respond with exactly: 'No violations found.'",
        "",
    ]

    # Rules Checklist
    if all_headings:
        parts.append("## Rules Checklist")
        parts.append("You must check each of the following rules for every applicable file:")
        for heading in all_headings:
            parts.append(f"- [ ] {heading}")
        parts.append("")

    # Per-file interleaved sections
    for file_path, rule_list in file_rules.items():
        if file_path not in files:
            continue

        parts.append(f"=== FILE: {file_path} ===")
        parts.append("")

        # Applicable rules for this file
        parts.append("--- Applicable Rules ---")
        for rule_name, rule_body in rule_list:
            parts.append(f"[{rule_name}]")
            parts.append(rule_body)
            parts.append("")

        # Diff for this file (primary check target)
        parts.append("--- Changes (primary check target) ---")
        file_diff = diff_chunks.get(file_path, "")
        if file_diff:
            parts.append(file_diff)
        else:
            parts.append("(no diff available for this file)")
        parts.append("")

        # Full content for context
        parts.append("--- Full Content (for context) ---")
        parts.append(files[file_path])
        parts.append("")

    # Suppressions
    if suppressions:
        parts.append("=== KNOWN SUPPRESSIONS ===")
        parts.append("以下は既知の例外です。これらに該当する場合は違反として報告しないでください。")
        parts.append(suppressions)
        parts.append("")

    # Reminder
    parts.append("## Reminder")
    parts.append("Confirm that you have checked every rule in the checklist above for each applicable file.")
    parts.append("Do not skip any rule. Report all violations found.")

    return "\n".join(parts)


def output_result(decision: str, message: str = "") -> None:
    """Output hook result as JSON to stdout.

    Uses the PreToolUse hookSpecificOutput format:
    - permissionDecision: "allow" or "deny"
    - additionalContext: injected into the agent's context
    """
    hook_output: dict = {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
    }
    if message:
        hook_output["additionalContext"] = message
    result = {"hookSpecificOutput": hook_output}
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

    # Load suppressions
    suppressions = load_suppressions(project_dir)

    # Compute all rules content for cache key
    all_rules_content = "\n\n---\n\n".join(body for _, _, body in rules)
    cache_key = compute_cache_key(diff, all_rules_content, suppressions)
    cache = load_cache(cache_path)

    if cache_key in cache:
        cached_message = cache[cache_key]
        if cached_message:
            cached_has_violations = "[action required]" in cached_message.lower()
            output_result("deny" if cached_has_violations else "allow", cached_message)
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
    prompt = build_prompt(file_rules, files, diff, suppressions)

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
        message += "\n\n[Action Required]\nFix the violations above and retry the commit.\nIf any violation is a false positive, add a description to .complete-validator/suppressions.md and retry.\nRepeat until all violations are resolved."
    output_result("deny" if has_violations else "allow", message)

    cache[cache_key] = message
    save_cache(cache_path, cache)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        output_result("allow", f"[Style check] Unexpected error: {e}")
        sys.exit(0)

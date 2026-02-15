#!/usr/bin/env python3
"""AI validator using Claude.

Validates files against rules defined in rules/*.md.
Supports three modes:
  - working (default): validates unstaged changes (for on-demand use)
  - staged (--staged):  validates staged changes (for commit hooks)
  - full-scan (--full-scan): validates all tracked files (for scanning existing code)

Runs claude -p per rule file in parallel for better detection accuracy.
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
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from fnmatch import fnmatch
from pathlib import Path


PROMPT_VERSION = "3"


def run_git(*args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


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


def get_all_tracked_files() -> list[str]:
    """Get all tracked files via git ls-files."""
    output = run_git("ls-files")
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


def load_rules_from_dir(rules_dir: Path) -> tuple[list[tuple[str, list[str], str]], list[str]]:
    """Load rule files with their target patterns from a single directory.

    Returns
    -------
    tuple[list[tuple[str, list[str], str]], list[str]]
        (rules, warnings) where rules is a list of (filename, patterns, body)
        and warnings is a list of warning messages for files without frontmatter.
    """
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


def find_project_rules_dirs() -> list[Path]:
    """CWD から上方向に .complete-validator/rules/ を探索します。

    見つかった全ディレクトリを近い順 (CWD 側が先) に返します。
    """
    dirs = []
    current = Path.cwd().resolve()
    while True:
        candidate = current / ".complete-validator" / "rules"
        if candidate.is_dir():
            dirs.append(candidate)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return dirs


def merge_rules(
    builtin_dir: Path | None,
    project_dirs: list[Path],
) -> tuple[list[tuple[str, list[str], str]], list[str]]:
    """組み込みルールとプロジェクト ルールをマージします。

    優先順位:
    1. CWD に最も近い .complete-validator/rules/ が最優先
    2. 親ディレクトリの .complete-validator/rules/ が次に優先
    3. プラグイン組み込み rules/ がベース (最低優先)

    同名ファイルは近い方が勝ちます (nearest wins)。
    """
    all_warnings: list[str] = []
    # Collect rule sources: nearest first, builtin last
    sources: list[Path] = list(project_dirs)
    if builtin_dir is not None:
        sources.append(builtin_dir)

    merged: dict[str, tuple[str, list[str], str]] = {}
    for rules_dir in reversed(sources):
        rules, warnings = load_rules_from_dir(rules_dir)
        all_warnings.extend(warnings)
        for name, patterns, body in rules:
            merged[name] = (name, patterns, body)

    return list(merged.values()), all_warnings


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


def files_for_rule(
    rule_name: str,
    rule_patterns: list[str],
    changed_files: list[str],
) -> list[str]:
    """Return changed files that match a rule's applies_to patterns."""
    matched = []
    for file_path in changed_files:
        filename = os.path.basename(file_path)
        if any(fnmatch(filename, pat) for pat in rule_patterns):
            matched.append(file_path)
    return matched


def load_suppressions(base_dir: Path) -> str:
    """Load suppressions from .complete-validator/suppressions.md.

    Parameters
    ----------
    base_dir : Path
        .complete-validator/suppressions.md を探すディレクトリです (通常は git toplevel)。

    Returns
    -------
    str
        ファイルの内容を返します。ファイルが存在しない場合は空文字列を返します。
    """
    suppressions_path = base_dir / ".complete-validator" / "suppressions.md"
    if not suppressions_path.exists():
        return ""
    try:
        return suppressions_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def compute_cache_key(rule_name: str, rule_body: str, diff_for_rule: str, suppressions: str = "", mode: str = "diff") -> str:
    """Compute SHA256 hash for per-rule caching."""
    content = (
        PROMPT_VERSION + ":" + mode
        + "\n---RULE_NAME---\n" + rule_name
        + "\n---RULE_BODY---\n" + rule_body
        + "\n---DIFF---\n" + diff_for_rule
        + "\n---SUPPRESSIONS---\n" + suppressions
    )
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
        return f"[Validator error] claude exited with code {result.returncode}: {result.stderr.strip()}"
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
    """Extract ## headings from a rule body for the checklist.

    Skips headings inside fenced code blocks (``` or ~~~).
    """
    headings = []
    in_code_block = False
    for line in rule_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            continue
        if not in_code_block and line.startswith("## "):
            headings.append(line[3:].strip())
    return headings


def build_prompt_for_rule(
    rule_name: str,
    rule_body: str,
    matched_files: list[str],
    files: dict[str, str],
    diff_chunks: dict[str, str],
    suppressions: str = "",
    full_scan: bool = False,
) -> str:
    """Build the prompt for checking a single rule file against its matched files."""
    headings = extract_rule_headings(rule_body)

    if full_scan:
        parts = [
            "You are a strict AI validator. You MUST check every rule listed for each file. Do not skip any rule.",
            "Check the entire file content against the rules. All code in each file is the check target.",
            "If you are uncertain whether something is a violation, report it with a note that it needs confirmation.",
            "Be specific: state the file, line, and which rule is violated.",
            "If there are no violations, respond with exactly: 'No violations found.'",
            "",
        ]
    else:
        parts = [
            "You are a strict AI validator. You MUST check every rule listed for each file. Do not skip any rule.",
            "The diff is the primary check target. The full file content is provided for context only.",
            "If you are uncertain whether something is a violation, report it with a note that it needs confirmation.",
            "Be specific: state the file, line, and which rule is violated.",
            "If there are no violations, respond with exactly: 'No violations found.'",
            "",
        ]

    # Rules Checklist
    if headings:
        parts.append("## Rules Checklist")
        parts.append("You must check each of the following rules for every applicable file:")
        for heading in headings:
            parts.append(f"- [ ] {heading}")
        parts.append("")

    # Rule content
    parts.append(f"=== RULE: {rule_name} ===")
    parts.append(rule_body)
    parts.append("")

    # Per-file sections
    for file_path in matched_files:
        if file_path not in files:
            continue

        parts.append(f"=== FILE: {file_path} ===")
        parts.append("")

        if full_scan:
            # Full-scan: file content is the primary check target
            parts.append("--- Full Content (primary check target) ---")
            parts.append(files[file_path])
            parts.append("")
        else:
            # Diff mode: diff is primary, full content for context
            parts.append("--- Changes (primary check target) ---")
            file_diff = diff_chunks.get(file_path, "")
            if file_diff:
                parts.append(file_diff)
            else:
                parts.append("(no diff available for this file)")
            parts.append("")

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


def check_single_rule(
    rule_name: str,
    rule_body: str,
    rule_patterns: list[str],
    changed_files: list[str],
    files: dict[str, str],
    diff_chunks: dict[str, str],
    suppressions: str,
    cache: dict,
    cache_path: Path,
    cache_lock: threading.Lock,
    full_scan: bool = False,
) -> tuple[str, str, str]:
    """Check a single rule file against its matched files.

    Returns (rule_name, status, message) where status is "deny", "allow", or "error".
    """
    matched = files_for_rule(rule_name, rule_patterns, changed_files)
    # Filter to files we actually have content for
    matched = [f for f in matched if f in files]
    if not matched:
        return rule_name, "skip", ""

    # Build cache key content
    if full_scan:
        # Use sorted file contents hash instead of diff
        contents_for_hash = "".join(files[f] for f in sorted(matched))
        cache_key = compute_cache_key(rule_name, rule_body, contents_for_hash, suppressions, mode="full-scan")
    else:
        diff_for_rule = "".join(diff_chunks.get(f, "") for f in matched)
        cache_key = compute_cache_key(rule_name, rule_body, diff_for_rule, suppressions)

    # Cache check
    with cache_lock:
        if cache_key in cache:
            cached = cache[cache_key]
            has_violations = "[action required]" in cached.lower()
            return rule_name, "deny" if has_violations else "allow", cached

    # Build prompt and run Claude
    prompt = build_prompt_for_rule(
        rule_name, rule_body, matched, files, diff_chunks, suppressions, full_scan=full_scan,
    )

    try:
        response = run_claude_check(prompt)
    except subprocess.TimeoutExpired:
        return rule_name, "error", f"[{rule_name}] Timed out waiting for Claude response."
    except Exception as e:
        return rule_name, "error", f"[{rule_name}] Error: {e}"

    # Determine result
    has_violations = "no violations found" not in response.lower()
    message = f"[Rule: {rule_name}]\n{response}"
    if has_violations:
        message += "\n\n[Action Required]\nFix the violations above and retry the commit.\nIf any violation is a false positive, add a description to .complete-validator/suppressions.md and retry."

    # Save to cache
    with cache_lock:
        cache[cache_key] = message
        save_cache(cache_path, cache)

    return rule_name, "deny" if has_violations else "allow", message


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
        description="AI validator using Claude."
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--staged",
        action="store_true",
        help="Check staged changes (for commit hooks). Default: check working changes.",
    )
    mode_group.add_argument(
        "--full-scan",
        action="store_true",
        help="Check all tracked files regardless of diff (for scanning existing code).",
    )
    parser.add_argument(
        "--plugin-dir",
        type=Path,
        default=None,
        help="Plugin directory containing built-in rules/.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    staged = args.staged
    full_scan = args.full_scan
    plugin_dir = args.plugin_dir

    # Cache is stored at git toplevel
    git_toplevel = run_git("rev-parse", "--show-toplevel")
    cache_dir = Path(git_toplevel) if git_toplevel else Path.cwd()
    cache_path = cache_dir / ".complete-validator" / "cache.json"

    if full_scan:
        # Full-scan mode: check all tracked files
        target_files = get_all_tracked_files()
        if not target_files:
            print("No tracked files found.", file=sys.stderr)
            sys.exit(0)
        diff_chunks: dict[str, str] = {}
    else:
        # Diff-based mode (working or staged)
        diff = get_diff(staged)
        if not diff:
            sys.exit(0)
        target_files = get_changed_files(staged)
        if not target_files:
            sys.exit(0)
        diff_chunks = split_diff_by_file(diff)

    # Load rules: parent directory search + built-in
    project_dirs = find_project_rules_dirs()
    builtin_dir = plugin_dir / "rules" if plugin_dir else None
    rules, warnings = merge_rules(builtin_dir, project_dirs)

    # Output warnings for rule files without frontmatter
    if warnings and not rules:
        if full_scan:
            print("[Validator]\n" + "\n".join(warnings), file=sys.stderr)
        else:
            output_result("allow", "[Validator]\n" + "\n".join(warnings))
        sys.exit(0)

    if not rules:
        sys.exit(0)

    # Match files to rules (used only for early exit check)
    file_rules = match_files_to_rules(rules, target_files)
    if not file_rules:
        # No files match any rule patterns
        if warnings:
            if full_scan:
                print("[Validator]\n" + "\n".join(warnings), file=sys.stderr)
            else:
                output_result("allow", "[Validator]\n" + "\n".join(warnings))
        if full_scan:
            print("No files match any rule patterns.")
        sys.exit(0)

    # Load suppressions (always from git toplevel)
    suppressions = load_suppressions(cache_dir)

    # Load cache
    cache = load_cache(cache_path)

    # Get file contents for matched files
    files: dict[str, str] = {}
    for file_path in file_rules:
        try:
            if full_scan:
                content = Path(file_path).read_text(encoding="utf-8")
            else:
                content = get_file_content(file_path, staged)
        except (OSError, UnicodeDecodeError):
            continue
        if content:
            files[file_path] = content

    if not files:
        sys.exit(0)

    # Run checks per rule file in parallel
    deadline = time.monotonic() + (3600 if full_scan else 110)  # hook timeout is 120s; full-scan has no hook
    results: list[tuple[str, str, str]] = []
    cache_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=len(rules)) as executor:
        futures = {}
        for rule_name, rule_patterns, rule_body in rules:
            future = executor.submit(
                check_single_rule,
                rule_name, rule_body, rule_patterns,
                target_files, files, diff_chunks,
                suppressions, cache, cache_path, cache_lock,
                full_scan=full_scan,
            )
            futures[future] = rule_name

        for future in as_completed(futures):
            remaining = deadline - time.monotonic()
            timeout = max(10, remaining)
            try:
                result = future.result(timeout=timeout)
                results.append(result)
            except Exception as e:
                rule_name = futures[future]
                results.append((rule_name, "error", f"[{rule_name}] Error: {e}"))

    # Sort results by rule name for stable output
    results.sort(key=lambda r: r[0])

    # Aggregate results
    deny_messages = []
    allow_messages = []
    error_messages = []

    for rule_name, status, message in results:
        if status == "skip":
            continue
        elif status == "deny":
            deny_messages.append(message)
        elif status == "error":
            error_messages.append(message)
        else:
            allow_messages.append(message)

    # Build final output
    all_messages = deny_messages + allow_messages
    if error_messages:
        all_messages.append("\n[Warning]\n" + "\n".join(error_messages))
    if warnings:
        all_messages.append("\n[Warning]\n" + "\n".join(warnings))

    if not all_messages:
        if full_scan:
            print("No violations found.")
        sys.exit(0)

    message = "[Validator Result]\n" + "\n\n".join(all_messages)

    if full_scan:
        # Full-scan: plain text output + exit code
        if deny_messages:
            message += "\n\n[Action Required]\nFix the violations above.\nIf any violation is a false positive, add a description to .complete-validator/suppressions.md and re-run."
            print(message, file=sys.stderr)
            sys.exit(1)
        else:
            print(message)
            sys.exit(0)
    else:
        # Hook mode: JSON output
        if deny_messages:
            message += "\n\n[Action Required]\nFix the violations above and retry the commit.\nIf any violation is a false positive, add a description to .complete-validator/suppressions.md and retry.\nRepeat until all violations are resolved."
            output_result("deny", message)
        else:
            output_result("allow", message)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        output_result("allow", f"[Validator] Unexpected error: {e}")
        sys.exit(0)

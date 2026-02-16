#!/usr/bin/env python3
"""AI validator using Claude.

Validates files against rules defined in rules/*.md.
Supports four modes:
  - working (default): validates unstaged changes (for on-demand use)
  - staged (--staged):  validates staged changes (for commit hooks)
  - full-scan (--full-scan): validates all tracked files (for scanning existing code)
  - stream (--stream):  background per-file validation with polling results

Runs claude -p per rule file in parallel for better detection accuracy.
Violations are denied (commit blocked) so the agent must fix them.
False positives can be suppressed via .complete-validator/suppressions.md.
"""

import argparse
import hashlib
import json
import os
import random
import re
import string
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path


# v3: ルール ファイル単位の分割並列実行に変更しています。v2 は全ルール一括、v1 はファイル単位でした。
PROMPT_VERSION = "3"

# (rule_filename, glob_patterns, body) のリストです。
RuleList = list[tuple[str, list[str], str]]

# claude -p の応答待ち上限です。ルール 1 つあたりの処理時間に余裕を持たせた値です。
CLAUDE_TIMEOUT_SECONDS = 580
# フル スキャンは hook 外で実行するため、ルール数 × ファイル数に応じて十分長く設定しています。
FULL_SCAN_DEADLINE_SECONDS = 3600
# hook タイムアウト (600 秒) の 10 秒前に打ち切り、結果出力の時間を確保します。
HOOK_DEADLINE_SECONDS = 590
# deadline 超過後でもキャッシュ ヒット済み Future を回収するための最低待機時間です。
MIN_FUTURE_TIMEOUT_SECONDS = 10
# ストリーム モードの結果ディレクトリを保持する最大数です。
MAX_STREAM_RESULTS_DIRS = 5
# ストリーム モードの deadline (秒) です。hook 外で実行するため長めに設定しています。
STREAM_DEADLINE_SECONDS = 3600


@dataclass
class CacheStore:
    """Per-rule cache backed by a JSON file on disk.

    Parameters
    ----------
    path: Path
        キャッシュ JSON ファイルのパスです。
    """

    path: Path
    _data: dict = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def load(self) -> None:
        """Load cache contents from disk into memory.

        Silently starts with an empty cache if the file is missing or corrupt.
        """
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def get(self, key: str) -> str | None:
        """Return the cached value for *key*, or ``None`` on miss.

        Parameters
        ----------
        key: str
            キャッシュ キー (SHA256 ハッシュ) です。

        Returns
        -------
        str | None
            キャッシュされた値、またはミス時は ``None`` です。
        """
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: str) -> None:
        """Store *value* under *key* and persist to disk.

        Parameters
        ----------
        key: str
            キャッシュ キー (SHA256 ハッシュ) です。
        value: str
            キャッシュする値 (バリデーション結果) です。
        """
        with self._lock:
            self._data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


@dataclass
class StreamStatusTracker:
    """Tracks stream mode progress and writes status.json.

    Parameters
    ----------
    results_dir: Path
        ストリーム結果ディレクトリのパスです。
    total_units: int
        チェック対象のユニット (ルール × ファイル ペア) の総数です。
    """

    results_dir: Path
    total_units: int
    _completed: int = 0
    _summary: dict = field(default_factory=lambda: {"allow": 0, "deny": 0, "error": 0, "pending": 0})
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"))

    def __post_init__(self) -> None:
        """Initialize pending count and write initial status."""
        self._summary["pending"] = self.total_units
        self._write_status("running")

    def update(self, status: str) -> None:
        """Record completion of one unit and update status.json.

        Parameters
        ----------
        status: str
            ユニットの結果 (``"allow"``、``"deny"``、``"error"``) です。
        """
        with self._lock:
            self._completed += 1
            self._summary[status] = self._summary.get(status, 0) + 1
            self._summary["pending"] = self.total_units - self._completed
            overall = "completed" if self._completed >= self.total_units else "running"
            self._write_status(overall)

    def mark_completed(self) -> None:
        """Mark the stream as completed."""
        self._write_status("completed")

    def _write_status(self, overall_status: str) -> None:
        """Write status.json to the results directory.

        Parameters
        ----------
        overall_status: str
            全体のステータス (``"running"``、``"completed"``) です。
        """
        status_data = {
            "stream_id": self.results_dir.name,
            "total_units": self.total_units,
            "completed_units": self._completed,
            "status": overall_status,
            "started_at": self._started_at,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "summary": dict(self._summary),
        }
        status_path = self.results_dir / "status.json"
        status_path.write_text(
            json.dumps(status_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def generate_stream_id() -> str:
    """Generate a unique stream ID (timestamp + random suffix).

    Returns
    -------
    str
        ``YYYYMMDD-HHMMSS-<random6>`` 形式の ID です。
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{timestamp}-{suffix}"


def cleanup_old_stream_results(base_dir: Path) -> None:
    """Keep only the latest stream result directories.

    Parameters
    ----------
    base_dir: Path
        ``.complete-validator/stream-results/`` ディレクトリのパスです。
    """
    if not base_dir.exists():
        return
    dirs = sorted(
        [d for d in base_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    for old_dir in dirs[MAX_STREAM_RESULTS_DIRS:]:
        import shutil
        shutil.rmtree(old_dir, ignore_errors=True)


def write_result_file(
    results_dir: Path,
    rule_name: str,
    file_path: str,
    status: str,
    message: str,
    cache_hit: bool,
) -> None:
    """Write a single result file for a (rule, file) pair.

    Parameters
    ----------
    results_dir: Path
        ストリーム結果ディレクトリのパスです。
    rule_name: str
        ルール名です。
    file_path: str
        チェック対象のファイル パスです。
    status: str
        結果ステータス (``"allow"``、``"deny"``、``"error"``) です。
    message: str
        詳細メッセージです。
    cache_hit: bool
        キャッシュ ヒットしたかどうかです。
    """
    # ルール名とファイル パスからファイル名を生成します。
    path_hash = hashlib.sha256(file_path.encode("utf-8")).hexdigest()[:12]
    safe_rule = rule_name.replace("/", "__").replace("\\", "__").replace(".md", "")
    result_filename = f"{safe_rule}__{path_hash}.json"

    result_data = {
        "rule_name": rule_name,
        "file_path": file_path,
        "status": status,
        "message": message,
        "cache_hit": cache_hit,
    }
    out_dir = results_dir / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / result_filename).write_text(
        json.dumps(result_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_git(*args: str) -> str:
    """Run a git command and return stripped stdout.

    Parameters
    ----------
    *args: str
        ``git`` に渡すサブコマンドとオプションです。

    Returns
    -------
    str
        標準出力の内容 (前後の空白を除去) です。
    """
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def get_diff(staged: bool) -> str:
    """Get the unified diff (staged or working).

    Parameters
    ----------
    staged: bool
        ``True`` なら ``git diff --cached``、``False`` なら ``git diff`` を実行します。

    Returns
    -------
    str
        diff の出力です。差分がなければ空文字列です。
    """
    if staged:
        return run_git("diff", "--cached")
    return run_git("diff")


def get_changed_files(staged: bool) -> list[str]:
    """Get list of changed file paths (excluding deleted files).

    Parameters
    ----------
    staged: bool
        ``True`` なら staged な変更、``False`` なら working な変更を対象にします。

    Returns
    -------
    list[str]
        変更されたファイル パスのリストです。
    """
    args = ["diff", "--name-only", "--diff-filter=d"]
    if staged:
        args.insert(1, "--cached")
    output = run_git(*args)
    return output.splitlines() if output else []


def get_all_tracked_files() -> list[str]:
    """Get all tracked file paths via ``git ls-files``.

    Returns
    -------
    list[str]
        tracked ファイル パスのリストです。
    """
    output = run_git("ls-files")
    return output.splitlines() if output else []


def get_file_content(file_path: str, staged: bool) -> str:
    """Get file content (staged version or working copy).

    Parameters
    ----------
    file_path: str
        ファイル パスです。
    staged: bool
        ``True`` なら ``git show :<path>`` で staged 版を取得します。

    Returns
    -------
    str
        ファイルの内容です。
    """
    if staged:
        return run_git("show", f":{file_path}")
    return Path(file_path).read_text(encoding="utf-8")


def parse_frontmatter(content: str) -> tuple[dict | None, str]:
    """Parse YAML frontmatter from rule file content.

    Parameters
    ----------
    content: str
        ルール ファイルの全文です。

    Returns
    -------
    tuple[dict | None, str]
        ``(frontmatter_dict, body)``。フロント マターがなければ ``(None, content)``。
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


def load_rules_from_dir(rules_dir: Path) -> tuple[RuleList, list[str]]:
    """Load rule files with their target patterns from a single directory.

    Parameters
    ----------
    rules_dir: Path
        ルール ファイルを含むディレクトリです。

    Returns
    -------
    tuple[RuleList, list[str]]
        (rules, warnings) where rules is a list of (filename, patterns, body)
        and warnings is a list of warning messages for files without frontmatter.
    """
    if not rules_dir.exists():
        return [], []

    rules = []
    warnings = []
    for md_file in sorted(rules_dir.rglob("*.md")):
        file_content = md_file.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(file_content)

        if frontmatter is None or "applies_to" not in frontmatter:
            warnings.append(
                f"ルール ファイル {md_file.name} に `applies_to` フロント マターがありません。追記してください。"
            )
            continue

        patterns = frontmatter["applies_to"]
        if isinstance(patterns, str):
            patterns = [patterns]

        # ディレクトリ相対パスをルール名として使用します (例: readable_code/02_naming.md)。
        relative_name = str(md_file.relative_to(rules_dir))
        rules.append((relative_name, patterns, body))

    return rules, warnings


def find_project_rules_dirs() -> list[Path]:
    """CWD から上方向に .complete-validator/rules/ を探索します。

    Returns
    -------
    list[Path]
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
) -> tuple[RuleList, list[str]]:
    """組み込みルールとプロジェクト ルールをマージします。

    Parameters
    ----------
    builtin_dir: Path | None
        プラグイン組み込み ``rules/`` ディレクトリです。``None`` なら組み込みルールはありません。
    project_dirs: list[Path]
        プロジェクト側の ``rules/`` ディレクトリ (近い順) です。

    Returns
    -------
    tuple[RuleList, list[str]]
        ``(merged_rules, warnings)``。同名ファイルは近い方が勝ちます (nearest wins)。
    """
    all_warnings: list[str] = []
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


def files_matching_patterns(
    patterns: list[str],
    file_paths: list[str],
) -> list[str]:
    """Return file paths whose basename matches any of the glob patterns.

    Parameters
    ----------
    patterns: list[str]
        glob パターンのリストです (例: ``["*.py", "*.md"]``)。
    file_paths: list[str]
        マッチ対象のファイル パスのリストです。

    Returns
    -------
    list[str]
        パターンに一致したファイル パスのリストです。
    """
    matched = []
    for file_path in file_paths:
        filename = os.path.basename(file_path)
        if any(fnmatch(filename, pat) for pat in patterns):
            matched.append(file_path)
    return matched


def any_file_matches_rules(rules: RuleList, file_paths: list[str]) -> bool:
    """Return whether any file matches at least one rule's applies_to patterns.

    Parameters
    ----------
    rules: RuleList
        ルールのリストです。
    file_paths: list[str]
        マッチ対象のファイル パスのリストです。

    Returns
    -------
    bool
        1 つ以上のファイルがいずれかのルールに一致すれば ``True`` です。
    """
    for file_path in file_paths:
        filename = os.path.basename(file_path)
        for _rule_name, patterns, _body in rules:
            if any(fnmatch(filename, pat) for pat in patterns):
                return True
    return False


def load_suppressions(base_dir: Path) -> str:
    """Load suppressions from .complete-validator/suppressions.md.

    Parameters
    ----------
    base_dir: Path
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


def compute_cache_key(
    rule_name: str,
    rule_body: str,
    diff_for_rule: str,
    suppressions: str = "",
    mode: str = "diff",
    per_file: bool = False,
    file_path: str = "",
) -> str:
    """Compute SHA256 hash for caching.

    Parameters
    ----------
    rule_name: str
        ルール ファイル名です。
    rule_body: str
        ルール本文です。
    diff_for_rule: str
        該当ファイルの diff またはファイル内容です。
    suppressions: str
        suppressions の内容です。
    mode: str
        ``"diff"``、``"full-scan"``、``"stream"`` のいずれかです。
    per_file: bool
        ``True`` なら per-file 粒度のキャッシュです。ストリーム モード用です。
    file_path: str
        per_file が ``True`` の場合のファイル パスです。

    Returns
    -------
    str
        SHA256 ハッシュ文字列です。
    """
    granularity = "per-file" if per_file else "per-rule"
    cache_key_material = (
        PROMPT_VERSION + ":" + mode + ":" + granularity
        + "\n---RULE_NAME---\n" + rule_name
        + "\n---FILE_PATH---\n" + file_path
        + "\n---RULE_BODY---\n" + rule_body
        + "\n---DIFF---\n" + diff_for_rule
        + "\n---SUPPRESSIONS---\n" + suppressions
    )
    return hashlib.sha256(cache_key_material.encode("utf-8")).hexdigest()


def run_claude_check(prompt: str) -> str:
    """Run ``claude -p`` with the given prompt and return the response.

    Parameters
    ----------
    prompt: str
        Claude に送信するプロンプトです。

    Returns
    -------
    str
        Claude の応答テキストです。
    """
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    result = subprocess.run(
        ["claude", "-p"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT_SECONDS,
        env=env,
    )
    if result.returncode != 0:
        return f"[Validator error] claude exited with code {result.returncode}: {result.stderr.strip()}"
    return result.stdout.strip()


def split_diff_by_file(diff: str) -> dict[str, str]:
    """Split a unified diff into per-file chunks.

    Parameters
    ----------
    diff: str
        ``git diff`` の出力 (unified diff 形式) です。

    Returns
    -------
    dict[str, str]
        ファイル パスをキー、そのファイルの diff チャンクを値とする辞書です。
    """
    chunks: dict[str, str] = {}
    current_path: str | None = None
    current_lines: list[str] = []

    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_path is not None:
                chunks[current_path] = "".join(current_lines)
            # Extract b/ path: 'diff --git a/foo b/bar' -> 'bar'
            header_parts = line.strip().split(" b/", 1)
            current_path = header_parts[1] if len(header_parts) == 2 else None
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_path is not None:
        chunks[current_path] = "".join(current_lines)

    return chunks


def extract_rule_headings(rule_body: str) -> list[str]:
    """Extract ``##`` headings from a rule body for the checklist.

    Parameters
    ----------
    rule_body: str
        ルール ファイルの本文 (フロント マター除去済み) です。

    Returns
    -------
    list[str]
        見出しテキストのリストです。コード ブロック内の見出しはスキップします。
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
    """Build the prompt for checking a single rule file against its matched files.

    Parameters
    ----------
    rule_name: str
        ルール ファイル名です。
    rule_body: str
        ルール本文です。
    matched_files: list[str]
        このルールに一致するファイル パスのリストです。
    files: dict[str, str]
        ファイル パスをキー、ファイル内容を値とする辞書です。
    diff_chunks: dict[str, str]
        ファイル パスをキー、diff チャンクを値とする辞書です。
    suppressions: str
        suppressions の内容です。
    full_scan: bool
        ``True`` ならフル スキャン モードです。

    Returns
    -------
    str
        構築されたプロンプト文字列です。
    """
    headings = extract_rule_headings(rule_body)

    scope_instruction = (
        "Check the entire file content against the rules. All code in each file is the check target."
        if full_scan
        else "The diff is the primary check target. The full file content is provided for context only."
    )
    parts = [
        "You are a strict AI validator. You MUST check every rule listed for each file. Do not skip any rule.",
        scope_instruction,
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
            parts.append("--- Full Content (primary check target) ---")
            parts.append(files[file_path])
            parts.append("")
        else:
            parts.append("--- Changes (primary check target) ---")
            file_diff = diff_chunks.get(file_path, "")
            parts.append(file_diff if file_diff else "(no diff available for this file)")
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


def build_prompt_for_single_file(
    rule_name: str,
    rule_body: str,
    file_path: str,
    file_content: str,
    file_diff: str,
    suppressions: str = "",
    full_scan: bool = False,
) -> str:
    """Build the prompt for checking a single rule against a single file.

    Parameters
    ----------
    rule_name: str
        ルール ファイル名です。
    rule_body: str
        ルール本文です。
    file_path: str
        チェック対象のファイル パスです。
    file_content: str
        ファイルの全文です。
    file_diff: str
        ファイルの diff チャンクです。
    suppressions: str
        suppressions の内容です。
    full_scan: bool
        ``True`` ならフル スキャン モードです。

    Returns
    -------
    str
        構築されたプロンプト文字列です。
    """
    headings = extract_rule_headings(rule_body)

    scope_instruction = (
        "Check the entire file content against the rules. All code in the file is the check target."
        if full_scan
        else "The diff is the primary check target. The full file content is provided for context only."
    )
    parts = [
        "You are a strict AI validator. You MUST check every rule listed for the file. Do not skip any rule.",
        scope_instruction,
        "If you are uncertain whether something is a violation, report it with a note that it needs confirmation.",
        "Be specific: state the file, line, and which rule is violated.",
        "If there are no violations, respond with exactly: 'No violations found.'",
        "",
    ]

    if headings:
        parts.append("## Rules Checklist")
        parts.append("You must check each of the following rules:")
        for heading in headings:
            parts.append(f"- [ ] {heading}")
        parts.append("")

    parts.append(f"=== RULE: {rule_name} ===")
    parts.append(rule_body)
    parts.append("")

    parts.append(f"=== FILE: {file_path} ===")
    parts.append("")

    if full_scan:
        parts.append("--- Full Content (primary check target) ---")
        parts.append(file_content)
        parts.append("")
    else:
        parts.append("--- Changes (primary check target) ---")
        parts.append(file_diff if file_diff else "(no diff available for this file)")
        parts.append("")
        parts.append("--- Full Content (for context) ---")
        parts.append(file_content)
        parts.append("")

    if suppressions:
        parts.append("=== KNOWN SUPPRESSIONS ===")
        parts.append("以下は既知の例外です。これらに該当する場合は違反として報告しないでください。")
        parts.append(suppressions)
        parts.append("")

    parts.append("## Reminder")
    parts.append("Confirm that you have checked every rule in the checklist above.")
    parts.append("Do not skip any rule. Report all violations found.")

    return "\n".join(parts)


def check_single_rule_single_file(
    rule_name: str,
    rule_body: str,
    file_path: str,
    file_content: str,
    file_diff: str,
    suppressions: str,
    cache: CacheStore,
    full_scan: bool = False,
) -> tuple[str, str, str, str, bool]:
    """Check a single rule against a single file.

    Parameters
    ----------
    rule_name: str
        ルール ファイル名です。
    rule_body: str
        ルール本文です。
    file_path: str
        チェック対象のファイル パスです。
    file_content: str
        ファイルの全文です。
    file_diff: str
        ファイルの diff チャンクです。
    suppressions: str
        suppressions の内容です。
    cache: CacheStore
        キャッシュ ストアです。
    full_scan: bool
        ``True`` ならフル スキャン モードです。

    Returns
    -------
    tuple[str, str, str, str, bool]
        ``(rule_name, file_path, status, message, cache_hit)`` です。
    """
    mode = "full-scan" if full_scan else "stream"
    diff_or_content = file_content if full_scan else file_diff
    cache_key = compute_cache_key(
        rule_name, rule_body, diff_or_content, suppressions,
        mode=mode, per_file=True, file_path=file_path,
    )

    cached = cache.get(cache_key)
    if cached is not None:
        is_clean = "[action required]" not in cached.lower()
        status = "allow" if is_clean else "deny"
        return rule_name, file_path, status, cached, True

    prompt = build_prompt_for_single_file(
        rule_name, rule_body, file_path, file_content, file_diff,
        suppressions, full_scan=full_scan,
    )

    try:
        response = run_claude_check(prompt)
    except subprocess.TimeoutExpired:
        return rule_name, file_path, "error", f"[{rule_name}:{file_path}] Timed out.", False
    except Exception as e:
        return rule_name, file_path, "error", f"[{rule_name}:{file_path}] Error: {e}", False

    is_clean = "no violations found" in response.lower()
    message = f"[Rule: {rule_name} | File: {file_path}]\n{response}"
    if not is_clean:
        message += "\n\n[Action Required]\nFix the violations above.\nIf any violation is a false positive, add a description to .complete-validator/suppressions.md."

    cache.put(cache_key, message)
    status = "allow" if is_clean else "deny"
    return rule_name, file_path, status, message, False


def check_single_rule(
    rule_name: str,
    rule_body: str,
    rule_patterns: list[str],
    changed_files: list[str],
    files: dict[str, str],
    diff_chunks: dict[str, str],
    suppressions: str,
    cache: CacheStore,
    full_scan: bool = False,
) -> tuple[str, str, str]:
    """Check a single rule file against its matched files.

    Parameters
    ----------
    rule_name: str
        ルール ファイル名です。
    rule_body: str
        ルール本文です。
    rule_patterns: list[str]
        ``applies_to`` glob パターンのリストです。
    changed_files: list[str]
        チェック対象のファイル パスのリストです。
    files: dict[str, str]
        ファイル パスをキー、ファイル内容を値とする辞書です。
    diff_chunks: dict[str, str]
        ファイル パスをキー、diff チャンクを値とする辞書です。
    suppressions: str
        suppressions の内容です。
    cache: CacheStore
        キャッシュ ストアです。
    full_scan: bool
        ``True`` ならフル スキャン モードです。

    Returns
    -------
    tuple[str, str, str]
        ``(rule_name, status, message)``。status は ``"deny"``、``"allow"``、``"skip"``、``"error"`` のいずれかです。
    """
    matched = files_matching_patterns(rule_patterns, changed_files)
    matched = [file_path for file_path in matched if file_path in files]
    if not matched:
        return rule_name, "skip", ""

    # Per-file cache preflight: ストリーム モードで蓄積された per-file キャッシュを確認します。
    # 全マッチ ファイルが per-file キャッシュでヒットすれば、claude -p を実行せず集約して即返却します。
    if not full_scan:
        per_file_results: list[tuple[str, str]] = []
        all_hit = True
        for fp in matched:
            pf_diff = diff_chunks.get(fp, "")
            pf_key = compute_cache_key(
                rule_name, rule_body, pf_diff, suppressions,
                mode="stream", per_file=True, file_path=fp,
            )
            pf_cached = cache.get(pf_key)
            if pf_cached is None:
                all_hit = False
                break
            pf_is_clean = "[action required]" not in pf_cached.lower()
            per_file_results.append(("allow" if pf_is_clean else "deny", pf_cached))

        if all_hit and per_file_results:
            has_deny = any(s == "deny" for s, _ in per_file_results)
            aggregated = "\n\n".join(msg for _, msg in per_file_results)
            return rule_name, "deny" if has_deny else "allow", aggregated

    # Build cache key
    if full_scan:
        contents_for_hash = "".join(files[file_path] for file_path in sorted(matched))
        cache_key = compute_cache_key(rule_name, rule_body, contents_for_hash, suppressions, mode="full-scan")
    else:
        diff_for_rule = "".join(diff_chunks.get(file_path, "") for file_path in matched)
        cache_key = compute_cache_key(rule_name, rule_body, diff_for_rule, suppressions)

    # Cache check
    cached = cache.get(cache_key)
    if cached is not None:
        is_clean = "[action required]" not in cached.lower()
        return rule_name, "allow" if is_clean else "deny", cached

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
    is_clean = "no violations found" in response.lower()
    message = f"[Rule: {rule_name}]\n{response}"
    if not is_clean:
        message += "\n\n[Action Required]\nFix the violations above and retry the commit.\nIf any violation is a false positive, add a description to .complete-validator/suppressions.md and retry."

    cache.put(cache_key, message)

    return rule_name, "allow" if is_clean else "deny", message


def output_result(decision: str, message: str = "") -> None:
    """Output hook result as JSON to stdout.

    Parameters
    ----------
    decision: str
        ``"allow"`` または ``"deny"`` です。
    message: str
        エージェントのコンテキストに注入する追加情報です。
    """
    hook_output: dict = {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
    }
    if message:
        hook_output["additionalContext"] = message
    print(json.dumps({"hookSpecificOutput": hook_output}))


def emit_warnings(warnings: list[str], full_scan: bool) -> None:
    """Output rule-loading warnings in the appropriate format.

    Parameters
    ----------
    warnings: list[str]
        警告メッセージのリストです。
    full_scan: bool
        ``True`` なら stderr へ出力、``False`` なら hook JSON で出力します。
    """
    text = "[Validator]\n" + "\n".join(warnings)
    if full_scan:
        print(text, file=sys.stderr)
    else:
        output_result("allow", text)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns
    -------
    argparse.Namespace
        パース済みの引数です。
    """
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
    # ストリーム モード
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Start stream mode: fork a background worker and print stream-id.",
    )
    parser.add_argument(
        "--stream-worker",
        action="store_true",
        help="Internal: run as a stream worker process.",
    )
    parser.add_argument(
        "--stream-id",
        type=str,
        default=None,
        help="Internal: stream ID for the worker process.",
    )
    return parser.parse_args()


def resolve_target_files(
    staged: bool,
    full_scan: bool,
) -> tuple[list[str], dict[str, str]]:
    """Determine target files and diff chunks based on the execution mode.

    Parameters
    ----------
    staged: bool
        staged モードかどうかです。
    full_scan: bool
        フル スキャン モードかどうかです。

    Returns
    -------
    tuple[list[str], dict[str, str]]
        ``(target_files, diff_chunks)``。フル スキャン時は diff_chunks は空辞書です。
        ファイルがない場合はどちらも空です。
    """
    if full_scan:
        target_files = get_all_tracked_files()
        if not target_files:
            print("No tracked files found.", file=sys.stderr)
        return target_files, {}

    diff = get_diff(staged)
    if not diff:
        return [], {}
    target_files = get_changed_files(staged)
    if not target_files:
        return [], {}
    return target_files, split_diff_by_file(diff)


def load_file_contents(
    file_paths: list[str],
    staged: bool,
    full_scan: bool,
) -> dict[str, str]:
    """Load file contents for the given paths.

    Parameters
    ----------
    file_paths: list[str]
        読み込むファイル パスのリストです。
    staged: bool
        ``True`` なら staged 版を取得します。
    full_scan: bool
        ``True`` なら作業ツリーから直接読み込みます。

    Returns
    -------
    dict[str, str]
        ファイル パスをキー、内容を値とする辞書です。読み込めなかったファイルは除外されます。
    """
    contents: dict[str, str] = {}
    for file_path in file_paths:
        try:
            if full_scan:
                file_content = Path(file_path).read_text(encoding="utf-8")
            else:
                file_content = get_file_content(file_path, staged)
        except (OSError, UnicodeDecodeError):
            continue
        if file_content:
            contents[file_path] = file_content
    return contents


def run_parallel_checks(
    rules: RuleList,
    target_files: list[str],
    files: dict[str, str],
    diff_chunks: dict[str, str],
    suppressions: str,
    cache: CacheStore,
    full_scan: bool,
) -> list[tuple[str, str, str]]:
    """Run rule checks in parallel and collect results.

    Parameters
    ----------
    rules: RuleList
        チェックするルールのリストです。
    target_files: list[str]
        チェック対象のファイル パスのリストです。
    files: dict[str, str]
        ファイル パスをキー、内容を値とする辞書です。
    diff_chunks: dict[str, str]
        ファイル パスをキー、diff チャンクを値とする辞書です。
    suppressions: str
        suppressions の内容です。
    cache: CacheStore
        キャッシュ ストアです。
    full_scan: bool
        ``True`` ならフル スキャン モードです。

    Returns
    -------
    list[tuple[str, str, str]]
        ``(rule_name, status, message)`` のリスト (ルール名でソート済み) です。
    """
    deadline = time.monotonic() + (FULL_SCAN_DEADLINE_SECONDS if full_scan else HOOK_DEADLINE_SECONDS)
    results: list[tuple[str, str, str]] = []

    with ThreadPoolExecutor(max_workers=len(rules)) as executor:
        futures = {}
        for rule_name, rule_patterns, rule_body in rules:
            future = executor.submit(
                check_single_rule,
                rule_name, rule_body, rule_patterns,
                target_files, files, diff_chunks,
                suppressions, cache,
                full_scan=full_scan,
            )
            futures[future] = rule_name

        for future in as_completed(futures):
            remaining_seconds = deadline - time.monotonic()
            timeout_seconds = max(MIN_FUTURE_TIMEOUT_SECONDS, remaining_seconds)
            try:
                result = future.result(timeout=timeout_seconds)
                results.append(result)
            except Exception as e:
                failed_rule_name = futures[future]
                results.append((failed_rule_name, "error", f"[{failed_rule_name}] Error: {e}"))

    # ルール名順でソートし、実行ごとの出力を安定させます。
    results.sort(key=lambda r: r[0])
    return results


def run_stream_checks(
    rules: RuleList,
    target_files: list[str],
    files: dict[str, str],
    diff_chunks: dict[str, str],
    suppressions: str,
    cache: CacheStore,
    results_dir: Path,
    full_scan: bool = False,
    log_file: Path | None = None,
) -> None:
    """Run per-file rule checks in parallel and write results to disk.

    Parameters
    ----------
    rules: RuleList
        チェックするルールのリストです。
    target_files: list[str]
        チェック対象のファイル パスのリストです。
    files: dict[str, str]
        ファイル パスをキー、内容を値とする辞書です。
    diff_chunks: dict[str, str]
        ファイル パスをキー、diff チャンクを値とする辞書です。
    suppressions: str
        suppressions の内容です。
    cache: CacheStore
        キャッシュ ストアです。
    results_dir: Path
        ストリーム結果ディレクトリのパスです。
    full_scan: bool
        ``True`` ならフル スキャン モードです。
    log_file: Path | None
        ワーカー ログのパスです。
    """
    def log(msg: str) -> None:
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

    # (rule_name, rule_body, file_path) のペアを列挙します。
    units: list[tuple[str, str, str]] = []
    for rule_name, rule_patterns, rule_body in rules:
        matched = files_matching_patterns(rule_patterns, target_files)
        matched = [fp for fp in matched if fp in files]
        for fp in matched:
            units.append((rule_name, rule_body, fp))

    if not units:
        log("No rule-file units to check.")
        tracker = StreamStatusTracker(results_dir=results_dir, total_units=0)
        tracker.mark_completed()
        return

    tracker = StreamStatusTracker(results_dir=results_dir, total_units=len(units))
    log(f"Starting {len(units)} units.")
    deadline = time.monotonic() + STREAM_DEADLINE_SECONDS

    with ThreadPoolExecutor(max_workers=min(len(units), 16)) as executor:
        futures = {}
        for rule_name, rule_body, fp in units:
            future = executor.submit(
                check_single_rule_single_file,
                rule_name, rule_body, fp,
                files[fp], diff_chunks.get(fp, ""),
                suppressions, cache,
                full_scan=full_scan,
            )
            futures[future] = (rule_name, fp)

        for future in as_completed(futures):
            remaining = deadline - time.monotonic()
            timeout = max(MIN_FUTURE_TIMEOUT_SECONDS, remaining)
            try:
                r_rule, r_file, r_status, r_message, r_cache_hit = future.result(timeout=timeout)
                write_result_file(results_dir, r_rule, r_file, r_status, r_message, r_cache_hit)
                tracker.update(r_status)
                log(f"[{r_status}] {r_rule} | {r_file} (cache={r_cache_hit})")
            except Exception as e:
                failed_rule, failed_file = futures[future]
                write_result_file(results_dir, failed_rule, failed_file, "error", str(e), False)
                tracker.update("error")
                log(f"[error] {failed_rule} | {failed_file}: {e}")

    tracker.mark_completed()
    log("Stream completed.")


def format_and_output(
    results: list[tuple[str, str, str]],
    warnings: list[str],
    full_scan: bool,
) -> None:
    """Aggregate check results and output in the appropriate format.

    Parameters
    ----------
    results: list[tuple[str, str, str]]
        ``(rule_name, status, message)`` のリストです。
    warnings: list[str]
        ルール読み込み時の警告メッセージです。
    full_scan: bool
        ``True`` なら plain text + exit code、``False`` なら hook JSON で出力します。
    """
    deny_messages = []
    allow_messages = []
    error_messages = []

    for _rule_name, status, message in results:
        if status == "skip":
            continue
        elif status == "deny":
            deny_messages.append(message)
        elif status == "error":
            error_messages.append(message)
        else:
            allow_messages.append(message)

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
        if deny_messages:
            message += "\n\n[Action Required]\nFix the violations above.\nIf any violation is a false positive, add a description to .complete-validator/suppressions.md and re-run."
            print(message, file=sys.stderr)
            sys.exit(1)
        else:
            print(message)
            sys.exit(0)
    else:
        if deny_messages:
            message += "\n\n[Action Required]\nFix the violations above and retry the commit.\nIf any violation is a false positive, add a description to .complete-validator/suppressions.md and retry.\nRepeat until all violations are resolved."
            output_result("deny", message)
        else:
            output_result("allow", message)


def main_stream(args: argparse.Namespace) -> None:
    """Start stream mode: fork a background worker and print stream-id.

    Parameters
    ----------
    args: argparse.Namespace
        パース済みの引数です。
    """
    stream_id = generate_stream_id()
    git_toplevel = run_git("rev-parse", "--show-toplevel")
    cache_dir = Path(git_toplevel) if git_toplevel else Path.cwd()
    results_base = cache_dir / ".complete-validator" / "stream-results"
    results_base.mkdir(parents=True, exist_ok=True)
    results_dir = results_base / stream_id
    results_dir.mkdir(parents=True, exist_ok=True)

    cleanup_old_stream_results(results_base)

    # ワーカー プロセスを起動します。
    worker_cmd = [
        sys.executable, __file__,
        "--stream-worker",
        "--stream-id", stream_id,
    ]
    if args.staged:
        worker_cmd.append("--staged")
    if args.full_scan:
        worker_cmd.append("--full-scan")
    if args.plugin_dir:
        worker_cmd.extend(["--plugin-dir", str(args.plugin_dir)])

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    log_file = results_dir / "worker.log"
    with open(log_file, "w", encoding="utf-8") as lf:
        subprocess.Popen(
            worker_cmd,
            stdout=lf,
            stderr=lf,
            start_new_session=True,
            env=env,
        )

    print(stream_id)
    sys.exit(0)


def main_stream_worker(args: argparse.Namespace) -> None:
    """Run as a stream worker process (invoked by main_stream).

    Parameters
    ----------
    args: argparse.Namespace
        パース済みの引数です。
    """
    staged = args.staged
    full_scan = args.full_scan
    stream_id = args.stream_id

    git_toplevel = run_git("rev-parse", "--show-toplevel")
    cache_dir = Path(git_toplevel) if git_toplevel else Path.cwd()
    results_dir = cache_dir / ".complete-validator" / "stream-results" / stream_id
    results_dir.mkdir(parents=True, exist_ok=True)
    log_file = results_dir / "worker.log"

    target_files, diff_chunks = resolve_target_files(staged, full_scan)
    if not target_files:
        tracker = StreamStatusTracker(results_dir=results_dir, total_units=0)
        tracker.mark_completed()
        return

    project_dirs = find_project_rules_dirs()
    builtin_dir = args.plugin_dir / "rules" if args.plugin_dir else None
    rules, _warnings = merge_rules(builtin_dir, project_dirs)
    if not rules:
        tracker = StreamStatusTracker(results_dir=results_dir, total_units=0)
        tracker.mark_completed()
        return

    if not any_file_matches_rules(rules, target_files):
        tracker = StreamStatusTracker(results_dir=results_dir, total_units=0)
        tracker.mark_completed()
        return

    suppressions = load_suppressions(cache_dir)
    cache = CacheStore(path=cache_dir / ".complete-validator" / "cache.json")
    cache.load()

    matched_target_files = [
        fp for fp in target_files
        if any(
            any(fnmatch(os.path.basename(fp), pat) for pat in patterns)
            for _name, patterns, _body in rules
        )
    ]
    files = load_file_contents(matched_target_files, staged, full_scan)
    if not files:
        tracker = StreamStatusTracker(results_dir=results_dir, total_units=0)
        tracker.mark_completed()
        return

    run_stream_checks(
        rules, target_files, files, diff_chunks,
        suppressions, cache, results_dir,
        full_scan=full_scan, log_file=log_file,
    )


def main() -> None:
    """Run the AI validator: parse args, load rules, and check files."""
    args = parse_args()

    # ストリーム モード: バックグラウンド ワーカーを起動して stream-id を出力します。
    if args.stream:
        main_stream(args)
        return

    # ストリーム ワーカー モード: バックグラウンドで per-file チェックを実行します。
    if args.stream_worker:
        main_stream_worker(args)
        return

    staged = args.staged
    full_scan = args.full_scan

    git_toplevel = run_git("rev-parse", "--show-toplevel")
    cache_dir = Path(git_toplevel) if git_toplevel else Path.cwd()

    # Resolve target files
    target_files, diff_chunks = resolve_target_files(staged, full_scan)
    if not target_files:
        sys.exit(0)

    # Load rules
    project_dirs = find_project_rules_dirs()
    builtin_dir = args.plugin_dir / "rules" if args.plugin_dir else None
    rules, warnings = merge_rules(builtin_dir, project_dirs)

    if warnings and not rules:
        emit_warnings(warnings, full_scan)
        sys.exit(0)

    if not rules:
        sys.exit(0)

    # Early exit if no files match any rule
    if not any_file_matches_rules(rules, target_files):
        if warnings:
            emit_warnings(warnings, full_scan)
        if full_scan:
            print("No files match any rule patterns.")
        sys.exit(0)

    # Load file contents
    suppressions = load_suppressions(cache_dir)
    cache = CacheStore(path=cache_dir / ".complete-validator" / "cache.json")
    cache.load()

    # いずれかのルールにマッチするファイルだけ内容を読み込みます。
    matched_target_files = [
        file_path for file_path in target_files
        if any(
            any(fnmatch(os.path.basename(file_path), pat) for pat in patterns)
            for _name, patterns, _body in rules
        )
    ]
    files = load_file_contents(matched_target_files, staged, full_scan)

    if not files:
        sys.exit(0)

    # Run checks and output results
    results = run_parallel_checks(
        rules, target_files, files, diff_chunks, suppressions, cache, full_scan,
    )
    format_and_output(results, warnings, full_scan)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        output_result("allow", f"[Validator] Unexpected error: {e}")
        sys.exit(0)

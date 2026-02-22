#!/usr/bin/env python3
"""Claude を使用した AI バリデーターです。

rules/*.md に定義されたルールに基づいてファイルを検証します。
4 つのモードをサポートしています:
  - working (デフォルト): unstaged な変更を検証します (オンデマンド用)
  - staged (--staged): staged な変更を検証します (commit hook 用)
  - full-scan (--full-scan): 全 tracked ファイルを検証します (既存コードのスキャン用)
  - stream (--stream): バックグラウンドで per-file 検証を実行し、結果をポーリングします

検出精度向上のため、(ルール ファイル, 対象ファイル) ペアごとに claude -p を並列実行します。
違反があれば deny (commit ブロック) し、エージェントが修正する必要があります。
偽陽性は .complete-validator/suppressions.md で抑制できます。
"""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import string
import subprocess
import sys
import threading
import time
from enum import Enum
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from uuid import uuid4


# v4: 全モードで per-file 単位 (1 ルール × 1 ファイル) の並列実行に統一しています。
# v3 は hook がルール単位、ストリームが per-file でした。v2 は全ルール一括、v1 はファイル単位でした。
PROMPT_VERSION = "4"
VIOLATION_STATUS_SCHEMA_VERSION = "1"
DEFAULT_LEASE_TTL_SECONDS = 300
DEFAULT_LEASE_GRACE_PERIOD_SECONDS = 30


class ViolationStatus(str, Enum):
    """永続的な violation 処理状態の enum."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    MANUAL_REVIEW = "manual_review"
    STALE = "stale"

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
# claude -p の同時起動数のデフォルト上限です。.complete-validator/config.json で上書きできます。
DEFAULT_MAX_WORKERS = 4
# claude -p で使用するデフォルト モデルです。.complete-validator/config.json で上書きできます。
DEFAULT_MODEL = "sonnet"
# キャッシュ TTL のデフォルト (秒) です。既定は 7 日です。
DEFAULT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


def load_config(config_dir: Path) -> dict:
    """.complete-validator/config.json または RULE_VALIDATOR_CONFIG_PATH から設定を読み込みます。

    Parameters
    ----------
    config_dir: Path
        ``.complete-validator/`` を探すディレクトリです (通常は git toplevel)。

    Returns
    -------
    dict
        設定の辞書です。ファイルが存在しない場合は空辞書を返します。
    """
    explicit_path = os.environ.get("RULE_VALIDATOR_CONFIG_PATH")
    if explicit_path:
        config_path = Path(explicit_path)
    else:
        config_path = config_dir / ".complete-validator" / "config.json"

    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def get_max_workers(config: dict) -> int:
    """config から max_workers を取得します。未設定時は DEFAULT_MAX_WORKERS を返します。

    Parameters
    ----------
    config: dict
        ``load_config()`` で読み込んだ設定の辞書です。

    Returns
    -------
    int
        claude -p の同時起動数の上限です。
    """
    value = config.get("max_workers", DEFAULT_MAX_WORKERS)
    if isinstance(value, int) and value > 0:
        return value
    return DEFAULT_MAX_WORKERS


def get_default_model(config: dict) -> str:
    """config から default_model を取得します。未設定時は DEFAULT_MODEL を返します。

    Parameters
    ----------
    config: dict
        ``load_config()`` で読み込んだ設定の辞書です。

    Returns
    -------
    str
        ``claude -p`` で使用するモデル名です。
    """
    value = config.get("default_model")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_MODEL


def get_cache_ttl_seconds(config: dict) -> int:
    """config から cache_ttl_seconds を取得します。未設定時は DEFAULT_CACHE_TTL_SECONDS を返します。

    Parameters
    ----------
    config: dict
        ``load_config()`` で読み込んだ設定の辞書です。

    Returns
    -------
    int
        キャッシュ TTL (秒) です。
    """
    value = config.get("cache_ttl_seconds", DEFAULT_CACHE_TTL_SECONDS)
    if isinstance(value, int) and value > 0:
        return value
    return DEFAULT_CACHE_TTL_SECONDS


@dataclass
class CacheStore:
    """JSON ファイルに永続化されるキャッシュ ストアです。

    Parameters
    ----------
    path: Path
        キャッシュ JSON ファイルのパスです。
    """

    path: Path
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    _data: dict = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _current_ts(self) -> float:
        return time.time()

    def _is_expired(self, entry: dict, now_ts: float) -> bool:
        expires_at = entry.get("expires_at")
        if expires_at is None:
            return False
        try:
            return float(expires_at) <= now_ts
        except (TypeError, ValueError):
            return False

    def _make_entry(self, value: str, now_ts: float) -> dict:
        return {
            "value": value,
            "cached_at": now_ts,
            "expires_at": now_ts + self.ttl_seconds,
        }

    def _persist_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> None:
        """ディスクからキャッシュ内容をメモリーに読み込みます。

        ファイルが存在しないか破損している場合は空のキャッシュで開始します。
        """
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._data = {}
            return

        if not isinstance(raw, dict):
            self._data = {}
            return

        now_ts = self._current_ts()
        normalized: dict[str, dict] = {}
        changed = False
        for key, value in raw.items():
            if isinstance(value, str):
                normalized[key] = self._make_entry(value, now_ts)
                changed = True
                continue
            if not isinstance(value, dict):
                changed = True
                continue
            if "value" not in value:
                changed = True
                continue
            entry_value = value.get("value", "")
            if not isinstance(entry_value, str):
                entry_value = str(entry_value)
                changed = True
            entry = dict(value)
            entry["value"] = entry_value
            if self._is_expired(entry, now_ts):
                changed = True
                continue
            if "cached_at" not in entry:
                entry["cached_at"] = now_ts
                changed = True
            if "expires_at" not in entry:
                entry["expires_at"] = now_ts + self.ttl_seconds
                changed = True
            normalized[key] = entry

        self._data = normalized
        if changed:
            with self._lock:
                self._persist_locked()

    def get(self, key: str) -> str | None:
        """*key* に対応するキャッシュ値を返します。ミス時は ``None`` を返します。

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
            entry = self._data.get(key)
            if not isinstance(entry, dict):
                return None
            now_ts = self._current_ts()
            if self._is_expired(entry, now_ts):
                self._data.pop(key, None)
                self._persist_locked()
                return None
            value = entry.get("value")
            return value if isinstance(value, str) else None

    def put(self, key: str, value: str) -> None:
        """*key* に *value* を格納し、ディスクに永続化します。

        Parameters
        ----------
        key: str
            キャッシュ キー (SHA256 ハッシュ) です。
        value: str
            キャッシュする値 (バリデーション結果) です。
        """
        with self._lock:
            now_ts = self._current_ts()
            self._data[key] = self._make_entry(value, now_ts)
            self._persist_locked()


@dataclass
class StreamStatusTracker:
    """ストリーム モードの進捗を追跡し、status.json に書き出します。

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
        """pending カウントを初期化し、初期ステータスを書き出します。"""
        self._summary["pending"] = self.total_units
        self._write_status("running")

    def update(self, status: str) -> None:
        """1 ユニットの完了を記録し、status.json を更新します。

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
        """ストリームを完了状態にします。"""
        self._write_status("completed")

    def _write_status(self, overall_status: str) -> None:
        """結果ディレクトリに status.json を書き出します。

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
    """一意のストリーム ID (タイムスタンプ + ランダム サフィックス) を生成します。

    Returns
    -------
    str
        ``YYYYMMDD-HHMMSS-<random6>`` 形式の ID です。
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{timestamp}-{suffix}"


def cleanup_old_stream_results(base_dir: Path) -> None:
    """最新のストリーム結果ディレクトリのみを保持します。

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
        shutil.rmtree(old_dir, ignore_errors=True)


def _repository_root() -> Path:
    git_toplevel = run_git("rev-parse", "--show-toplevel")
    return Path(git_toplevel) if git_toplevel else Path.cwd()


def _safe_filename(name: str) -> str:
    return (
        name.replace("/", "__")
        .replace("\\", "__")
        .replace(":", "_")
        .replace(" ", "_")
    )


def _now_timestamp() -> float:
    return time.time()


def _now_iso8601() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _normalize_target_path(root: Path, file_path: str) -> str:
    try:
        rel = os.path.relpath(file_path, root)
    except ValueError:
        rel = file_path
    return rel.replace(os.sep, "/")


def _severity_priority(severity: str) -> int:
    normalized = (severity or "").strip().lower()
    if normalized == "critical":
        return 0
    if normalized == "high":
        return 100
    if normalized == "medium":
        return 200
    if normalized == "low":
        return 300
    if normalized == "info":
        return 400
    return 500


def _build_violation_id(rule_id: str, canonical_file_path: str) -> str:
    return hashlib.sha256(f"{rule_id}\n{canonical_file_path}".encode("utf-8")).hexdigest()


def _violations_dir(root: Path) -> tuple[Path, Path]:
    base = root / ".complete-validator" / "violations"
    return base / "results", base / "queue"


def _queue_state_path(queue_dir: Path, violation_id: str, status: ViolationStatus, priority: int) -> Path:
    safe_priority = max(0, min(999, int(priority)))
    filename = f"{safe_priority:03d}__{status.value}__{violation_id}.state.json"
    return queue_dir / filename


def _write_json_atomically(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "wb") as handle:
        handle.write(
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def _replace_state_file(state_path: Path, next_state_path: Path, state: dict) -> bool:
    """既存ステートを排他で遷移します。

    Parameters
    ----------
    state_path: Path
        現在の状態ファイルパスです。
    next_state_path: Path
        遷移後の状態ファイルパスです。
    state: dict
        書き込むステート内容です。

    Returns
    -------
    bool
        遷移が成功した場合 True。
    """
    lock_token = state_path.with_name(f".{state_path.name}.{uuid4().hex}.lock")
    try:
        os.replace(state_path, lock_token)
    except FileNotFoundError:
        return False

    try:
        _write_json_atomically(lock_token, state)
        os.replace(lock_token, next_state_path)
        return True
    except Exception:
        # 片側で失敗した場合は復旧を試みる。
        try:
            os.replace(lock_token, state_path)
        except OSError:
            pass
        return False


def _read_json_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _is_violation_state_file(path: Path) -> tuple[ViolationStatus, int, str] | None:
    match = re.match(
        r"^(?P<priority>\d{3})__(?P<status>[a-z_]+)__(?P<id>[0-9a-f]{64})\.state\.json$",
        path.name,
    )
    if not match:
        return None
    try:
        status = ViolationStatus(match.group("status"))
    except ValueError:
        return None
    return status, int(match.group("priority")), match.group("id")


def _list_queue_states(
    queue_dir: Path,
    stream_id: str | None = None,
    violation_id: str | None = None,
    statuses: set[ViolationStatus] | None = None,
) -> list[tuple[Path, dict, int, ViolationStatus]]:
    if not queue_dir.exists():
        return []

    states: list[tuple[Path, dict, int, ViolationStatus]] = []
    status_filter = statuses if statuses is not None else None

    for path in sorted(queue_dir.iterdir()):
        if not path.is_file():
            continue
        parsed = _is_violation_state_file(path)
        if not parsed:
            continue
        file_status, priority, _id = parsed
        if violation_id is not None and _id != violation_id:
            continue
        data = _read_json_file(path)
        if not isinstance(data, dict):
            continue
        if data.get("id") and _id != data.get("id"):
            continue
        if stream_id is not None and data.get("run_id") != stream_id:
            continue
        if status_filter is not None and file_status not in status_filter:
            continue
        states.append((path, data, priority, file_status))

    states.sort(
        key=lambda item: (
            item[2],
            _severity_priority(item[1].get("severity", "")),
            item[1].get("detected_at", ""),
            item[0].name,
        )
    )
    return states


def _is_lease_expired(state: dict, now_ts: float) -> bool:
    lease_value = state.get("lease_expires_at")
    if lease_value is None:
        return False
    try:
        lease_ts = float(lease_value)
    except (TypeError, ValueError):
        return False
    return lease_ts <= now_ts - DEFAULT_LEASE_GRACE_PERIOD_SECONDS


def _collect_orphan_in_progress_for_file(
    queue_dir: Path,
    target_file_path: str,
    exclude_path: Path,
    now_ts: float,
) -> list[tuple[Path, dict, int]]:
    locked: list[tuple[Path, dict, int]] = []
    for path, data, priority, status in _list_queue_states(queue_dir, statuses={ViolationStatus.IN_PROGRESS}):
        if path == exclude_path:
            continue
        if data.get("target_file_path") != target_file_path:
            continue
        if _is_lease_expired(data, now_ts):
            continue
        locked.append((path, data, priority))
    return locked


def _force_expired_to_pending(queue_dir: Path, now_ts: float) -> int:
    changed = 0
    for path, data, priority, _status in _list_queue_states(
        queue_dir,
        statuses={ViolationStatus.IN_PROGRESS},
    ):
        if not _is_lease_expired(data, now_ts):
            continue
        next_state = dict(data)
        next_state["status"] = ViolationStatus.PENDING.value
        next_state["state_version"] = int(data.get("state_version", 0)) + 1
        next_state["lease_expires_at"] = None
        next_state["claimed_at"] = None
        next_state["claim_uuid"] = None
        next_state["owner"] = None
        next_state["updated_at"] = _now_iso8601()
        target_priority = _severity_priority(data.get("severity", ""))
        new_path = _queue_state_path(queue_dir, data.get("id", ""), ViolationStatus.PENDING, target_priority)
        if _replace_state_file(path, new_path, next_state):
            changed += 1
    return changed


def _list_violations_for_queue(
    stream_id: str,
    statuses: set[ViolationStatus] | None = None,
    include_unassigned: bool = False,
) -> list[dict]:
    root = _repository_root()
    _, queue_dir = _violations_dir(root)
    now_ts = _now_timestamp()
    _force_expired_to_pending(queue_dir, now_ts)

    status_filter = (
        statuses
        if statuses is not None
        else {ViolationStatus.PENDING, ViolationStatus.IN_PROGRESS}
    )
    collected = []
    for path, data, priority, status in _list_queue_states(
        queue_dir,
        stream_id=stream_id,
        statuses=status_filter,
    ):
        if not include_unassigned and data.get("id") is None:
            continue
        collected.append({
            "path": str(path),
            "id": data.get("id"),
            "rule": data.get("rule"),
            "target_file_path": data.get("target_file_path"),
            "status": status.value,
            "severity": data.get("severity", "medium"),
            "priority": priority,
            "state_version": data.get("state_version", 0),
            "owner": data.get("owner"),
            "claim_uuid": data.get("claim_uuid"),
            "run_id": data.get("run_id"),
            "detected_at": data.get("detected_at"),
            "lease_expires_at": data.get("lease_expires_at"),
            "source": str(data.get("source", "")),
        })
    return collected


def _active_in_progress_for_violation(
    queue_dir: Path,
    violation_id: str,
    now_ts: float,
) -> list[tuple[Path, dict, int, ViolationStatus]]:
    active: list[tuple[Path, dict, int, ViolationStatus]] = []
    for path, state, priority, status in _list_queue_states(
        queue_dir,
        violation_id=violation_id,
        statuses={ViolationStatus.IN_PROGRESS},
    ):
        if status != ViolationStatus.IN_PROGRESS:
            continue
        if _is_lease_expired(state, now_ts):
            continue
        active.append((path, state, priority, status))
    return active


def upsert_queue_state_from_stream_result(
    stream_id: str,
    base_dir: Path,
    rule_name: str,
    file_path: str,
    status: str,
    message: str,
    model: str,
    cache_hit: bool,
) -> None:
    """ストリーム結果から queue state を永続化/更新します。"""
    _, queue_dir = _violations_dir(base_dir)
    canonical_path = _normalize_target_path(base_dir, file_path)
    violation_id = _build_violation_id(rule_name, canonical_path)
    now_ts = _now_timestamp()
    _force_expired_to_pending(queue_dir, now_ts)

    active_claims = _active_in_progress_for_violation(queue_dir, violation_id, now_ts)
    if active_claims:
        # 進行中処理中の状態がある場合、再 claim の可能性を避けるため
        # 書き換えを行わない。次回再検知で解放されるまで保留。
        return

    current_status: ViolationStatus = ViolationStatus.RESOLVED
    severity = "medium"

    if status == "deny":
        current_status = ViolationStatus.PENDING
        severity = "high"
    elif status == "error":
        current_status = ViolationStatus.MANUAL_REVIEW
        severity = "high"

    normalized_message = message.strip() if message else ""
    state_data = {
        "schema_version": VIOLATION_STATUS_SCHEMA_VERSION,
        "id": violation_id,
        "rule": rule_name,
        "target_file_path": canonical_path,
        "status": current_status.value,
        "severity": severity,
        "violations": [{"detail": normalized_message, "location_hint": ""}],
        "run_id": stream_id,
        "detected_at": _now_iso8601(),
        "checker_model": model,
        "context_level": "diff_only",
        "cache_hit": cache_hit,
        "state_version": 0,
        "lease_expires_at": None,
        "claimed_at": None,
        "claim_uuid": None,
        "owner": None,
        "source": {
            "stream_id": stream_id,
            "model": model,
            "cache_hit": cache_hit,
            "updated_via": "run_stream_checks",
        },
    }

    existing_states = _list_queue_states(
        queue_dir,
        violation_id=violation_id,
    )

    state_version = 0
    if existing_states:
        # 最も新しい既存状態のバージョンを継続的に上げる。
        state_version = max(
            int(data.get("state_version", 0))
            for _, data, _, _ in existing_states
        )

    priority = _severity_priority(severity)
    state_path = _queue_state_path(queue_dir, violation_id, current_status, priority)
    state_data["state_version"] = state_version + 1
    state_data["updated_at"] = _now_iso8601()

    if existing_states:
        old_state_path, _old_data, _, _ = existing_states[0]
        if not _replace_state_file(old_state_path, state_path, state_data):
            return None
        for old_state_path, _old_data, _, _ in existing_states[1:]:
            if old_state_path == state_path:
                continue
            try:
                old_state_path.unlink()
            except FileNotFoundError:
                pass
    else:
        _write_json_atomically(state_path, state_data)

    return state_data


def _hash_violation_fingerprint(
    rule_id: str,
    severity: str,
    location_hint: str,
    detail: str,
    detector_version: str,
) -> str:
    material = f"{rule_id}|{severity}|{location_hint}|{detail}|{detector_version}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def write_violations_result_append(
    root: Path,
    stream_id: str,
    rule_name: str,
    file_path: str,
    status: str,
    message: str,
    cache_hit: bool,
    model: str,
) -> None:
    results_dir, _ = _violations_dir(root)
    results_dir.mkdir(parents=True, exist_ok=True)

    canonical_path = _normalize_target_path(root, file_path)
    violation_id = _build_violation_id(rule_name, canonical_path)
    severity = "high" if status in {"deny", "error"} else "medium"
    fingerprint = _hash_violation_fingerprint(
        rule_name,
        severity,
        canonical_path,
        message.strip(),
        model,
    )

    payload = {
        "schema_version": VIOLATION_STATUS_SCHEMA_VERSION,
        "run_id": stream_id,
        "id": violation_id,
        "rule": rule_name,
        "file": canonical_path,
        "status": "pending" if status in {"deny", "error"} else "resolved",
        "severity": severity,
        "violations": [
            {
                "detail": message.strip(),
                "location_hint": canonical_path,
                "fingerprint": fingerprint,
            }
        ],
        "checker_model": model,
        "context_level": "diff_only",
        "cache_hit": cache_hit,
        "detected_at": _now_iso8601(),
    }
    record_path = (
        results_dir
        / f"{violation_id}__{stream_id}__{int(time.time_ns())}.json"
    )
    _write_json_atomically(record_path, payload)


def write_result_file(
    results_dir: Path,
    rule_name: str,
    file_path: str,
    status: str,
    message: str,
    cache_hit: bool,
) -> None:
    """(ルール, ファイル) ペアの結果ファイルを 1 つ書き出します。

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
    """git コマンドを実行し、前後の空白を除去した stdout を返します。

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
    """unified diff を取得します (staged または working)。

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
    """変更されたファイル パスのリストを取得します (削除されたファイルを除く)。

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
    """``git ls-files`` で全 tracked ファイル パスを取得します。

    Returns
    -------
    list[str]
        tracked ファイル パスのリストです。
    """
    output = run_git("ls-files")
    return output.splitlines() if output else []


def get_file_content(file_path: str, staged: bool) -> str:
    """ファイルの内容を取得します (staged 版またはワーキング コピー)。

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
    """ルール ファイルの内容から YAML フロント マターをパースします。

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
    """単一ディレクトリからルール ファイルとその対象パターンを読み込みます。

    Parameters
    ----------
    rules_dir: Path
        ルール ファイルを含むディレクトリです。

    Returns
    -------
    tuple[RuleList, list[str]]
        (rules, warnings)。rules は (filename, patterns, body) のリスト、
        warnings はフロント マターのないファイルの警告メッセージ リストです。
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
    """basename がいずれかの glob パターンに一致するファイル パスを返します。

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
    """いずれかのファイルがルールの applies_to パターンに一致するかを返します。

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
    """.complete-validator/suppressions.md から suppressions を読み込みます。

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
    """キャッシュ用の SHA256 ハッシュを計算します。

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


def run_claude_check(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """指定されたプロンプトで ``claude -p`` を実行し、応答を返します。

    Parameters
    ----------
    prompt: str
        Claude に送信するプロンプトです。
    model: str
        使用するモデル名です。

    Returns
    -------
    str
        Claude の応答テキストです。
    """
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    cmd = ["claude", "-p", "--model", model]
    result = subprocess.run(
        cmd,
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
    """unified diff をファイルごとのチャンクに分割します。

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
            # b/ パスを抽出します: 'diff --git a/foo b/bar' -> 'bar'
            header_parts = line.strip().split(" b/", 1)
            current_path = header_parts[1] if len(header_parts) == 2 else None
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_path is not None:
        chunks[current_path] = "".join(current_lines)

    return chunks


def extract_rule_headings(rule_body: str) -> list[str]:
    """チェックリスト用にルール本文から ``##`` 見出しを抽出します。

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


def build_prompt_for_single_file(
    rule_name: str,
    rule_body: str,
    file_path: str,
    file_content: str,
    file_diff: str,
    suppressions: str = "",
    full_scan: bool = False,
) -> str:
    """1 つのルールを 1 つのファイルに対してチェックするためのプロンプトを構築します。

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
    model: str = DEFAULT_MODEL,
) -> tuple[str, str, str, str, bool]:
    """1 つのルールを 1 つのファイルに対してチェックします。

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
    model: str
        ``claude -p`` で使用するモデル名です。

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
        response = run_claude_check(prompt, model=model)
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


def output_result(decision: str, message: str = "") -> None:
    """hook の結果を JSON として stdout に出力します。

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
    """ルール読み込み時の警告を適切な形式で出力します。

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
    """コマンドライン引数をパースします。

    Returns
    -------
    argparse.Namespace
        パース済みの引数です。
    """
    parser = argparse.ArgumentParser(
        description="Claude を使用した AI バリデーターです。"
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--staged",
        action="store_true",
        help="staged な変更をチェックします (commit hook 用)。デフォルト: working な変更をチェックします。",
    )
    mode_group.add_argument(
        "--full-scan",
        action="store_true",
        help="diff に関係なく全 tracked ファイルをチェックします (既存コードのスキャン用)。",
    )
    parser.add_argument(
        "--plugin-dir",
        type=Path,
        default=None,
        help="組み込み rules/ を含むプラグイン ディレクトリです。",
    )
    # ストリーム モード
    parser.add_argument(
        "--stream",
        action="store_true",
        help="ストリーム モードを開始します: バックグラウンド ワーカーを起動し stream-id を出力します。",
    )
    parser.add_argument(
        "--stream-worker",
        action="store_true",
        help="内部用: ストリーム ワーカー プロセスとして実行します。",
    )
    parser.add_argument(
        "--stream-id",
        type=str,
        default=None,
        help="内部用: ワーカー プロセスのストリーム ID です。",
    )
    parser.add_argument(
        "--list-violations",
        metavar="STREAM_ID",
        type=str,
        default=None,
        help="指定した stream-id の未処理 violation を JSON で出力します。",
    )
    parser.add_argument(
        "--claim",
        metavar=("STREAM_ID", "VIOLATION_ID"),
        nargs=2,
        default=None,
        help="violation を claim して排他制御に入ります。<stream-id> <violation-id> を指定します。",
    )
    parser.add_argument(
        "--resolve",
        metavar=("STREAM_ID", "VIOLATION_ID"),
        nargs=2,
        default=None,
        help="violation を resolved に更新します。<stream-id> <violation-id> を指定します。",
    )
    parser.add_argument(
        "--heartbeat",
        metavar=("STREAM_ID", "VIOLATION_ID"),
        nargs=2,
        default=None,
        help="claim 済み violation の lease を延長します。<stream-id> <violation-id> を指定します。",
    )
    parser.add_argument(
        "--claim-uuid",
        type=str,
        default=None,
        help="--resolve/--heartbeat 時の CAS 用 claim_uuid。",
    )
    parser.add_argument(
        "--state-version",
        type=int,
        default=None,
        help="--resolve/--heartbeat 時の CAS 用 state_version。",
    )
    parser.add_argument(
        "--owner",
        type=str,
        default=None,
        help="--claim 時の owner 表示名。",
    )
    parser.add_argument(
        "--lease-ttl",
        type=int,
        default=DEFAULT_LEASE_TTL_SECONDS,
        help="--claim 時の lease 秒数。",
    )
    parser.add_argument(
        "--heartbeat-lease-ttl",
        type=int,
        default=None,
        help="--heartbeat 時に更新する lease 秒数。未指定時は現行 lease_ttl を再利用します。",
    )
    return parser.parse_args()


def resolve_target_files(
    staged: bool,
    full_scan: bool,
) -> tuple[list[str], dict[str, str]]:
    """実行モードに基づいてチェック対象ファイルと diff チャンクを決定します。

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
    """指定されたパスのファイル内容を読み込みます。

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
    max_workers: int = DEFAULT_MAX_WORKERS,
    model: str = DEFAULT_MODEL,
) -> list[tuple[str, str, str]]:
    """per-file 単位でルール チェックを並列実行し、結果を収集します。

    ストリーム モードと同じ per-file 単位 (1 ルール × 1 ファイル) で ``claude -p`` を
    実行します。同時起動数は ``max_workers`` で制限されます。

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
    max_workers: int
        ``claude -p`` の同時起動数の上限です。
    model: str
        ``claude -p`` で使用するモデル名です。

    Returns
    -------
    list[tuple[str, str, str]]
        ``(rule_name, status, message)`` のリスト (ルール名でソート済み) です。
    """
    deadline = time.monotonic() + (FULL_SCAN_DEADLINE_SECONDS if full_scan else HOOK_DEADLINE_SECONDS)

    # (rule_name, rule_body, file_path) のペアを列挙します。
    units: list[tuple[str, str, str]] = []
    for rule_name, rule_patterns, rule_body in rules:
        matched = files_matching_patterns(rule_patterns, target_files)
        matched = [fp for fp in matched if fp in files]
        for fp in matched:
            units.append((rule_name, rule_body, fp))

    if not units:
        return []

    # per-file 結果を収集します。
    per_file_results: list[tuple[str, str, str, str, bool]] = []

    with ThreadPoolExecutor(max_workers=min(len(units), max_workers)) as executor:
        futures = {}
        for rule_name, rule_body, fp in units:
            future = executor.submit(
                check_single_rule_single_file,
                rule_name, rule_body, fp,
                files[fp], diff_chunks.get(fp, ""),
                suppressions, cache,
                full_scan=full_scan,
                model=model,
            )
            futures[future] = (rule_name, fp)

        for future in as_completed(futures):
            remaining_seconds = deadline - time.monotonic()
            timeout_seconds = max(MIN_FUTURE_TIMEOUT_SECONDS, remaining_seconds)
            try:
                result = future.result(timeout=timeout_seconds)
                per_file_results.append(result)
            except Exception as e:
                failed_rule, failed_file = futures[future]
                per_file_results.append((failed_rule, failed_file, "error", f"[{failed_rule}:{failed_file}] Error: {e}", False))

    # ルール名ごとに集約します。
    by_rule: dict[str, list[tuple[str, str, str, bool]]] = defaultdict(list)
    for rule_name, file_path, status, message, cache_hit in per_file_results:
        by_rule[rule_name].append((file_path, status, message, cache_hit))

    results: list[tuple[str, str, str]] = []
    for rule_name in sorted(by_rule.keys()):
        file_results = by_rule[rule_name]
        has_deny = any(s == "deny" for _, s, _, _ in file_results)
        has_error = any(s == "error" for _, s, _, _ in file_results)
        aggregated = "\n\n".join(msg for _, _, msg, _ in file_results if msg)
        if has_deny:
            results.append((rule_name, "deny", aggregated))
        elif has_error:
            results.append((rule_name, "error", aggregated))
        elif aggregated:
            results.append((rule_name, "allow", aggregated))
        else:
            results.append((rule_name, "skip", ""))

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
    max_workers: int = DEFAULT_MAX_WORKERS,
    model: str = DEFAULT_MODEL,
    stream_id: str = "",
) -> None:
    """per-file 単位でルール チェックを並列実行し、結果をディスクに書き出します。

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
    max_workers: int
        ``claude -p`` の同時起動数の上限です。
    model: str
        ``claude -p`` で使用するモデル名です。
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

    with ThreadPoolExecutor(max_workers=min(len(units), max_workers)) as executor:
        futures = {}
        for rule_name, rule_body, fp in units:
            future = executor.submit(
                check_single_rule_single_file,
                rule_name, rule_body, fp,
                files[fp], diff_chunks.get(fp, ""),
                suppressions, cache,
                full_scan=full_scan,
                model=model,
            )
            futures[future] = (rule_name, fp)

        for future in as_completed(futures):
            remaining = deadline - time.monotonic()
            timeout = max(MIN_FUTURE_TIMEOUT_SECONDS, remaining)
            try:
                r_rule, r_file, r_status, r_message, r_cache_hit = future.result(timeout=timeout)
                write_result_file(results_dir, r_rule, r_file, r_status, r_message, r_cache_hit)
                upsert_queue_state_from_stream_result(
                    stream_id=stream_id,
                    base_dir=results_dir.parent.parent,
                    rule_name=r_rule,
                    file_path=r_file,
                    status=r_status,
                    message=r_message,
                    model=model,
                    cache_hit=r_cache_hit,
                )
                write_violations_result_append(
                    root=results_dir.parent.parent,
                    stream_id=stream_id,
                    rule_name=r_rule,
                    file_path=r_file,
                    status=r_status,
                    message=r_message,
                    cache_hit=r_cache_hit,
                    model=model,
                )
                tracker.update(r_status)
                log(f"[{r_status}] {r_rule} | {r_file} (cache={r_cache_hit})")
            except Exception as e:
                failed_rule, failed_file = futures[future]
                write_result_file(results_dir, failed_rule, failed_file, "error", str(e), False)
                upsert_queue_state_from_stream_result(
                    stream_id=stream_id,
                    base_dir=results_dir.parent.parent,
                    rule_name=failed_rule,
                    file_path=failed_file,
                    status="error",
                    message=str(e),
                    model=model,
                    cache_hit=False,
                )
                write_violations_result_append(
                    root=results_dir.parent.parent,
                    stream_id=stream_id,
                    rule_name=failed_rule,
                    file_path=failed_file,
                    status="error",
                    message=str(e),
                    cache_hit=False,
                    model=model,
                )
                tracker.update("error")
                log(f"[error] {failed_rule} | {failed_file}: {e}")

    tracker.mark_completed()
    log("Stream completed.")


def handle_list_violations(args: argparse.Namespace) -> None:
    """未処理/進行中の violation を表示します。"""
    stream_id = args.list_violations
    if not stream_id:
        print(json.dumps({"ok": False, "error": "stream-id is required"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    entries = _list_violations_for_queue(stream_id)
    payload = {
        "ok": True,
        "stream_id": stream_id,
        "count": len(entries),
        "entries": entries,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(0)


def handle_claim(args: argparse.Namespace) -> None:
    """violation を claim します。"""
    stream_id, violation_id = args.claim
    if not stream_id or not violation_id:
        print(json.dumps({"ok": False, "error": "--claim requires <stream-id> <violation-id>"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    host_name = os.environ.get("HOSTNAME")
    if not host_name and hasattr(os, "uname"):
        host_name = os.uname().nodename
    owner = args.owner or f"{os.getpid()}@{host_name or 'local'}"
    lease_ttl = args.lease_ttl or DEFAULT_LEASE_TTL_SECONDS
    if lease_ttl <= 0:
        lease_ttl = DEFAULT_LEASE_TTL_SECONDS

    root = _repository_root()
    _, queue_dir = _violations_dir(root)
    if not queue_dir.exists():
        print(json.dumps({"ok": False, "error": "queue directory not found"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    now_ts = _now_timestamp()
    _force_expired_to_pending(queue_dir, now_ts)

    candidates = _list_queue_states(
        queue_dir,
        stream_id=stream_id,
        violation_id=violation_id,
        statuses={ViolationStatus.PENDING},
    )
    if not candidates:
        print(json.dumps({"ok": False, "error": "target violation not found or already claimed"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    state_path, state, priority, _status = sorted(candidates, key=lambda item: item[2])[0]
    next_state = dict(state)
    next_state["status"] = ViolationStatus.IN_PROGRESS.value
    next_state["owner"] = owner
    next_state["claim_uuid"] = uuid4().hex
    next_state["state_version"] = int(state.get("state_version", 0)) + 1
    next_state["claimed_at"] = now_ts
    next_state["lease_ttl"] = lease_ttl
    next_state["lease_expires_at"] = now_ts + lease_ttl
    next_state["updated_at"] = _now_iso8601()

    target_file_path = state.get("target_file_path", "")
    conflict_locks = _collect_orphan_in_progress_for_file(queue_dir, target_file_path, state_path, now_ts)
    if conflict_locks:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "target file is locked by another claim",
                    "conflicting_claims": [
                        lock_state.get("claim_uuid") for _, lock_state, _ in conflict_locks
                    ],
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    new_state_path = _queue_state_path(
        queue_dir,
        violation_id,
        ViolationStatus.IN_PROGRESS,
        priority,
    )
    if not _replace_state_file(state_path, new_state_path, next_state):
        print(
            json.dumps(
                {"ok": False, "error": "failed to claim due concurrent update"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    payload = {
        "ok": True,
        "stream_id": stream_id,
        "violation_id": violation_id,
        "status": ViolationStatus.IN_PROGRESS.value,
        "state_version": next_state.get("state_version", 0),
        "claim_uuid": next_state.get("claim_uuid"),
        "owner": owner,
        "lease_expires_at": next_state.get("lease_expires_at"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(0)


def handle_resolve(args: argparse.Namespace) -> None:
    """violation を resolved に更新します。"""
    stream_id, violation_id = args.resolve
    if not stream_id or not violation_id:
        print(json.dumps({"ok": False, "error": "--resolve requires <stream-id> <violation-id>"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    root = _repository_root()
    _, queue_dir = _violations_dir(root)
    if not queue_dir.exists():
        print(json.dumps({"ok": False, "error": "queue directory not found"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    now_ts = _now_timestamp()
    _force_expired_to_pending(queue_dir, now_ts)

    candidates = _list_queue_states(
        queue_dir,
        stream_id=stream_id,
        violation_id=violation_id,
    )
    if not candidates:
        print(json.dumps({"ok": False, "error": "target violation not found"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    state_path, state, priority, status = candidates[0]
    if status == ViolationStatus.RESOLVED:
        print(
            json.dumps(
                {"ok": True, "stream_id": stream_id, "violation_id": violation_id, "status": status.value},
                ensure_ascii=False,
            )
        )
        sys.exit(0)

    if status != ViolationStatus.IN_PROGRESS:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"cannot resolve with status {status.value}",
                    "status": status.value,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    if args.claim_uuid and state.get("claim_uuid") != args.claim_uuid:
        print(
            json.dumps(
                {"ok": False, "error": "claim_uuid mismatch"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    if args.state_version is not None and state.get("state_version") != args.state_version:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "state_version mismatch",
                    "expected": args.state_version,
                    "actual": state.get("state_version"),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    next_state = dict(state)
    next_state["status"] = ViolationStatus.RESOLVED.value
    next_state["state_version"] = int(state.get("state_version", 0)) + 1
    next_state["resolved_at"] = now_ts
    next_state["owner"] = None
    next_state["claim_uuid"] = None
    next_state["lease_expires_at"] = None
    next_state["claimed_at"] = None
    next_state["updated_at"] = _now_iso8601()

    new_state_path = _queue_state_path(
        queue_dir,
        violation_id,
        ViolationStatus.RESOLVED,
        priority,
    )
    if not _replace_state_file(state_path, new_state_path, next_state):
        print(
            json.dumps(
                {"ok": False, "error": "failed to resolve due concurrent update"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        json.dumps(
            {
                "ok": True,
                "stream_id": stream_id,
                "violation_id": violation_id,
                "status": ViolationStatus.RESOLVED.value,
                "state_version": next_state.get("state_version", 0),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    sys.exit(0)


def handle_heartbeat(args: argparse.Namespace) -> None:
    """claim 済み violation の lease を延長します。"""
    stream_id, violation_id = args.heartbeat
    if not stream_id or not violation_id:
        print(
            json.dumps(
                {"ok": False, "error": "--heartbeat requires <stream-id> <violation-id>"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.claim_uuid:
        print(
            json.dumps(
                {"ok": False, "error": "--heartbeat requires --claim-uuid"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    root = _repository_root()
    _, queue_dir = _violations_dir(root)
    if not queue_dir.exists():
        print(json.dumps({"ok": False, "error": "queue directory not found"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    now_ts = _now_timestamp()
    _force_expired_to_pending(queue_dir, now_ts)

    candidates = _list_queue_states(
        queue_dir,
        stream_id=stream_id,
        violation_id=violation_id,
        statuses={ViolationStatus.IN_PROGRESS},
    )
    if not candidates:
        print(
            json.dumps(
                {"ok": False, "error": "target in_progress violation not found"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    state_path, state, priority, _status = candidates[0]
    if state.get("claim_uuid") != args.claim_uuid:
        print(
            json.dumps({"ok": False, "error": "claim_uuid mismatch"}, ensure_ascii=False),
            file=sys.stderr,
        )
        sys.exit(1)
    if args.state_version is not None and state.get("state_version") != args.state_version:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "state_version mismatch",
                    "expected": args.state_version,
                    "actual": state.get("state_version"),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    if _is_lease_expired(state, now_ts):
        print(
            json.dumps({"ok": False, "error": "lease already expired"}, ensure_ascii=False),
            file=sys.stderr,
        )
        sys.exit(1)

    current_ttl = state.get("lease_ttl")
    if isinstance(current_ttl, int) and current_ttl > 0:
        lease_ttl = current_ttl
    else:
        lease_ttl = DEFAULT_LEASE_TTL_SECONDS
    if args.heartbeat_lease_ttl is not None and args.heartbeat_lease_ttl > 0:
        lease_ttl = args.heartbeat_lease_ttl

    next_state = dict(state)
    next_state["lease_ttl"] = lease_ttl
    next_state["lease_expires_at"] = now_ts + lease_ttl
    next_state["state_version"] = int(state.get("state_version", 0)) + 1
    next_state["updated_at"] = _now_iso8601()

    target_path = _queue_state_path(queue_dir, violation_id, ViolationStatus.IN_PROGRESS, priority)
    if not _replace_state_file(state_path, target_path, next_state):
        print(
            json.dumps({"ok": False, "error": "failed to heartbeat due concurrent update"}, ensure_ascii=False),
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        json.dumps(
            {
                "ok": True,
                "stream_id": stream_id,
                "violation_id": violation_id,
                "status": ViolationStatus.IN_PROGRESS.value,
                "state_version": next_state.get("state_version", 0),
                "claim_uuid": next_state.get("claim_uuid"),
                "lease_ttl": lease_ttl,
                "lease_expires_at": next_state.get("lease_expires_at"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    sys.exit(0)


def format_and_output(
    results: list[tuple[str, str, str]],
    warnings: list[str],
    full_scan: bool,
) -> None:
    """チェック結果を集約し、適切な形式で出力します。

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
    """ストリーム モードを開始します: バックグラウンド ワーカーを起動し、stream-id を出力します。

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
    """ストリーム ワーカー プロセスとして実行します (main_stream から起動)。

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

    config = load_config(cache_dir)
    suppressions = load_suppressions(cache_dir)
    cache = CacheStore(
        path=cache_dir / ".complete-validator" / "cache.json",
        ttl_seconds=get_cache_ttl_seconds(config),
    )
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

    max_workers = get_max_workers(config)
    default_model = get_default_model(config)
    run_stream_checks(
        rules, target_files, files, diff_chunks,
        suppressions, cache, results_dir,
        full_scan=full_scan, log_file=log_file,
        max_workers=max_workers,
        model=default_model,
        stream_id=stream_id,
    )


def main() -> None:
    """AI バリデーターを実行します: 引数パース、ルール読み込み、ファイル チェックを行います。"""
    args = parse_args()

    if args.list_violations is not None:
        handle_list_violations(args)
        return
    if args.claim is not None:
        handle_claim(args)
        return
    if args.resolve is not None:
        handle_resolve(args)
        return
    if args.heartbeat is not None:
        handle_heartbeat(args)
        return

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

    # チェック対象ファイルを解決します。
    target_files, diff_chunks = resolve_target_files(staged, full_scan)
    if not target_files:
        sys.exit(0)

    # ルールを読み込みます。
    project_dirs = find_project_rules_dirs()
    builtin_dir = args.plugin_dir / "rules" if args.plugin_dir else None
    rules, warnings = merge_rules(builtin_dir, project_dirs)

    if warnings and not rules:
        emit_warnings(warnings, full_scan)
        sys.exit(0)

    if not rules:
        sys.exit(0)

    # どのルールにもマッチしないなら終了します。
    if not any_file_matches_rules(rules, target_files):
        if warnings:
            emit_warnings(warnings, full_scan)
        if full_scan:
            print("No files match any rule patterns.")
        sys.exit(0)

    # ファイル内容を読み込みます。
    config = load_config(cache_dir)
    suppressions = load_suppressions(cache_dir)
    cache = CacheStore(
        path=cache_dir / ".complete-validator" / "cache.json",
        ttl_seconds=get_cache_ttl_seconds(config),
    )
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

    # チェックを実行し結果を出力します。
    max_workers = get_max_workers(config)
    default_model = get_default_model(config)
    results = run_parallel_checks(
        rules, target_files, files, diff_chunks, suppressions, cache, full_scan,
        max_workers=max_workers,
        model=default_model,
    )
    format_and_output(results, warnings, full_scan)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        output_result("allow", f"[Validator] Unexpected error: {e}")
        sys.exit(0)

"""
Codex Limb - ~/.codex/sessions/**/*.jsonl 감시 (OpenAI Codex CLI)

전략: pick_strategy() → watchdog(이벤트) | polling(mtime, 5초 간격)
파싱 대상 두 종류 이벤트:
  1. event_msg / token_count → 가중 토큰 FeedData
       normalized = output_tokens × 1.0 + reasoning_output_tokens × 0.5 (raw)
  2. response_item / custom_tool_call(apply_patch) → V4A diff churn FeedData
       line_diff = added + removed
경로: ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl
"""

import json
import queue
import threading
from datetime import datetime
from pathlib import Path

from interface import BaseLimb, FeedData
from limbs.polling_mixin import PollingMixin, pick_strategy

CODEX_DIR = Path.home() / ".codex"


# ── 가중 토큰 ──────────────────────────────────────────────────────── #

def _normalize(output_tokens: int, reasoning_tokens: int) -> float:
    return output_tokens * 1.0 + reasoning_tokens * 0.5


# ── V4A diff churn ────────────────────────────────────────────────── #

def _parse_v4a_diff(diff_text: str) -> int:
    """V4A diff 텍스트의 +/- 줄 churn(added + removed) 카운트.

    헤더(`*** ...`)와 컨텍스트 마커(`@@ ...`)는 제외.
    """
    if not diff_text:
        return 0
    added = 0
    removed = 0
    for line in diff_text.splitlines():
        if line.startswith("***") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added + removed


# ── 메타데이터 추출 ────────────────────────────────────────────────── #

def _parse_iso(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now()


def _read_meta(path: str) -> dict:
    """파일 앞부분에서 dir/session/model_name 추출.

    session_meta(첫 줄)와 turn_context(이른 줄)를 둘 다 본다.
    """
    meta = {"dir": "", "session": "", "model_name": ""}
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                if i > 50:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                t = obj.get("type")
                payload = obj.get("payload")
                if not isinstance(payload, dict):
                    continue
                if t == "session_meta":
                    cwd = payload.get("cwd", "")
                    if cwd:
                        meta["dir"] = Path(cwd).name
                    sid = payload.get("id", "")
                    if sid:
                        meta["session"] = sid
                elif t == "turn_context":
                    model = payload.get("model")
                    if model:
                        meta["model_name"] = model
                if meta["dir"] and meta["session"] and meta["model_name"]:
                    break
    except OSError:
        pass
    return meta


# ── 본체 파싱 ──────────────────────────────────────────────────────── #

def _parse_offset(path: str, offset: int, meta: dict) -> tuple[list[FeedData], int]:
    """offset부터 신규 바이트를 읽어 이벤트별 FeedData 리스트 반환."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
            new_offset = f.tell()
    except OSError:
        return [], offset

    feeds: list[FeedData] = []
    for raw in data.splitlines():
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue
        t = obj.get("type")
        pt = payload.get("type")
        ts = obj.get("timestamp", "")

        if t == "event_msg" and pt == "token_count":
            info = payload.get("info")
            if not info:
                continue
            usage = info.get("last_token_usage", {})
            output = usage.get("output_tokens", 0)
            reasoning = usage.get("reasoning_output_tokens", 0)
            total = usage.get("total_tokens", 0)
            if output + reasoning <= 0:
                continue
            feeds.append(FeedData(
                dir=meta.get("dir", ""),
                agent_name="codex",
                total_token=total,
                normalized=_normalize(output, reasoning),
                created_at=_parse_iso(ts),
                model_name=meta.get("model_name", ""),
                session=meta.get("session", ""),
                line_diff=0,
            ))
            continue

        if t == "response_item" and pt == "custom_tool_call" and payload.get("name") == "apply_patch":
            churn = _parse_v4a_diff(payload.get("input", ""))
            if churn <= 0:
                continue
            feeds.append(FeedData(
                dir=meta.get("dir", ""),
                agent_name="codex",
                total_token=0,
                normalized=0.0,
                created_at=_parse_iso(ts),
                model_name=meta.get("model_name", ""),
                session=meta.get("session", ""),
                line_diff=churn,
            ))

    return feeds, new_offset


# ── watchdog 핸들러 ────────────────────────────────────────────────── #

def _make_watchdog_handler(feed_queue: queue.Queue):
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._offsets: dict[str, int] = {}
            self._meta: dict[str, dict] = {}

        def on_modified(self, event):
            if event.is_directory:
                return
            path = event.src_path
            if not (path.endswith(".json") or path.endswith(".jsonl")):
                return
            if path not in self._meta:
                self._meta[path] = _read_meta(path)
            feeds, new_offset = _parse_offset(path, self._offsets.get(path, 0), self._meta[path])
            self._offsets[path] = new_offset
            for feed in feeds:
                feed_queue.put(feed)

    return _Handler()


# ── Limb ───────────────────────────────────────────────────────────── #

class CodexLimb(BaseLimb, PollingMixin):
    def __init__(self):
        super().__init__()
        self._meta_cache: dict[str, dict] = {}

    @property
    def name(self) -> str:
        return "codex"

    def is_available(self) -> bool:
        return CODEX_DIR.exists()

    def watch(self, feed_queue: queue.Queue, stop_event: threading.Event) -> None:
        if pick_strategy() == "watchdog":
            self._watchdog_watch(feed_queue, stop_event)
        else:
            self._poll_watch(feed_queue, stop_event)

    def _watchdog_watch(self, feed_queue: queue.Queue, stop_event: threading.Event) -> None:
        from watchdog.observers import Observer

        handler = _make_watchdog_handler(feed_queue)
        observer = Observer()
        observer.schedule(handler, str(CODEX_DIR), recursive=True)
        observer.start()
        stop_event.wait()
        observer.stop()
        observer.join()

    # PollingMixin 구현 ────────────────────────────────────────────── #

    def _iter_target_files(self):
        sessions = CODEX_DIR / "sessions"
        target = sessions if sessions.exists() else CODEX_DIR
        return target.rglob("*.jsonl")

    def _parse_from_offset(self, path: str, offset: int) -> tuple[list[FeedData], int]:
        if path not in self._meta_cache:
            self._meta_cache[path] = _read_meta(path)
        return _parse_offset(path, offset, self._meta_cache[path])

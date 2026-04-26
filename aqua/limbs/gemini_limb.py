"""
Gemini Limb - ~/.gemini/ 감시 (Gemini CLI)

전략: pick_strategy() → watchdog(이벤트) | polling(mtime, 5초 간격)
파싱: JSONL의 type=="gemini" 메시지에서
      tokens.output + tokens.thoughts * 0.05
경로: ~/.gemini/**/*.jsonl 또는 ~/.config/gemini/**/*.jsonl
"""

import json
import queue
import re
import threading
from datetime import datetime
from pathlib import Path

from interface import BaseLimb, FeedData
from limbs.polling_mixin import PollingMixin, pick_strategy

_GEMINI_CANDIDATES = [
    Path.home() / ".gemini",
    Path.home() / ".config" / "gemini",
]


# ── 공통 유틸 ──────────────────────────────────────────────────────── #

def _resolve_dir() -> Path | None:
    for candidate in _GEMINI_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _project_name(path: str) -> str:
    path_obj = Path(path)

    # ~/.gemini/tmp/<project>/chats/session-*.jsonl -> <project>
    if path_obj.parent.name == "chats" and path_obj.parent.parent.name:
        return path_obj.parent.parent.name

    return path_obj.stem


def _path_to_project_dir(raw_path: str) -> str:
    path_obj = Path(raw_path)
    if path_obj.suffix:
        return str(path_obj.parent)
    return str(path_obj)


def _project_dir_from_payload(path: str, payload: dict) -> str:
    for tool_call in payload.get("toolCalls", []):
        result_display = tool_call.get("resultDisplay")
        if isinstance(result_display, dict):
            file_path = result_display.get("filePath")
            if isinstance(file_path, str) and file_path.startswith("/"):
                return _path_to_project_dir(file_path)

        for result in tool_call.get("result", []):
            if not isinstance(result, dict):
                continue
            response = result.get("functionResponse", {}).get("response", {})
            output = response.get("output")
            if not isinstance(output, str):
                continue
            match = re.search(r"(/Users/[^\s:\"']+)", output)
            if match:
                return _path_to_project_dir(match.group(1))

    return _project_name(path)


def _weighted_tokens(payload: dict) -> int:
    token_info = payload.get("tokens", {})
    weighted = token_info.get("output", 0) + (token_info.get("thoughts", 0) * 0.05)
    return int(round(weighted))


def _line_diff(payload: dict) -> int:
    total = 0
    for tool_call in payload.get("toolCalls", []):
        result_display = tool_call.get("resultDisplay")
        if not isinstance(result_display, dict):
            continue
        diff_stat = result_display.get("diffStat")
        if not isinstance(diff_stat, dict):
            continue
        total += diff_stat.get("model_added_lines", 0)
        total += diff_stat.get("model_removed_lines", 0)
    return total


def _parse_created_at(payload: dict) -> datetime:
    timestamp = payload.get("timestamp")
    if not timestamp:
        return datetime.now()
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()


def _parse_offset(path: str, offset: int, seen_ids: set[str]) -> tuple[list[dict], int]:
    """offset부터 읽어 신규 gemini 응답 payload 목록과 새 offset을 반환."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
            new_offset = f.tell()
    except OSError:
        return [], offset

    ordered_ids: list[str] = []
    latest_by_id: dict[str, dict] = {}
    for line in data.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        if payload.get("type") != "gemini":
            continue

        message_id = payload.get("id")
        if not message_id or message_id in seen_ids:
            continue

        if message_id not in latest_by_id:
            ordered_ids.append(message_id)
        latest_by_id[message_id] = payload

    events: list[dict] = []
    for message_id in ordered_ids:
        payload = latest_by_id[message_id]
        total_token = _weighted_tokens(payload)
        if total_token <= 0:
            continue
        seen_ids.add(message_id)
        events.append(payload)

    return events, new_offset


def _make_feed(path: str, payload: dict) -> FeedData:
    weighted_tokens = _weighted_tokens(payload)
    return FeedData(
        dir=_project_dir_from_payload(path, payload),
        agent_name="gemini",
        total_token=weighted_tokens,
        normalized=float(weighted_tokens),
        created_at=_parse_created_at(payload),
        model_name=payload.get("model", ""),
        session=Path(path).stem,
        line_diff=_line_diff(payload),
    )


# ── watchdog 핸들러 팩토리 ─────────────────────────────────────────── #

def _make_watchdog_handler(feed_queue: queue.Queue):
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._offsets: dict[str, int] = {}
            self._seen_ids: dict[str, set[str]] = {}

        def on_modified(self, event):
            if event.is_directory or not event.src_path.endswith(".jsonl"):
                return
            path = event.src_path
            seen_ids = self._seen_ids.setdefault(path, set())
            payloads, new_offset = _parse_offset(path, self._offsets.get(path, 0), seen_ids)
            self._offsets[path] = new_offset
            for payload in payloads:
                feed_queue.put(_make_feed(path, payload))

    return _Handler()


# ── Limb ───────────────────────────────────────────────────────────── #

class GeminiLimb(BaseLimb, PollingMixin):
    def __init__(self):
        self._seen_ids_by_path: dict[str, set[str]] = {}

    @property
    def name(self) -> str:
        return "gemini"

    def is_available(self) -> bool:
        return _resolve_dir() is not None

    def watch(self, feed_queue: queue.Queue, stop_event: threading.Event) -> None:
        if pick_strategy() == "watchdog":
            self._watchdog_watch(feed_queue, stop_event)
        else:
            self._poll_watch(feed_queue, stop_event)

    def _watchdog_watch(self, feed_queue: queue.Queue, stop_event: threading.Event) -> None:
        from watchdog.observers import Observer

        target = _resolve_dir()
        if target is None:
            return
        handler = _make_watchdog_handler(feed_queue)
        observer = Observer()
        observer.schedule(handler, str(target), recursive=True)
        observer.start()
        stop_event.wait()
        observer.stop()
        observer.join()

    # PollingMixin 구현 ────────────────────────────────────────────── #

    def _iter_target_files(self):
        target = _resolve_dir()
        return target.rglob("*.jsonl") if target else []

    def _parse_from_offset(self, path: str, offset: int) -> tuple[list[FeedData], int]:
        seen_ids = self._seen_ids_by_path.setdefault(path, set())
        payloads, new_offset = _parse_offset(path, offset, seen_ids)
        return [_make_feed(path, payload) for payload in payloads], new_offset

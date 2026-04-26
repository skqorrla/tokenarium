"""
Gemini Limb - ~/.gemini/ 감시 (Gemini CLI)

전략: pick_strategy() → watchdog(이벤트) | polling(mtime, 5초 간격)
파싱: usageMetadata.totalTokenCount
경로: ~/.gemini/ 없으면 ~/.config/gemini/ 시도
"""

import hashlib
import json
import queue
import threading
from datetime import datetime
from pathlib import Path

from interface import BaseLimb, FeedData
from limbs.polling_mixin import PollingMixin, pick_strategy

_GEMINI_CANDIDATES = [
    Path.home() / ".gemini",
    Path.home() / ".config" / "gemini",
]
_MAX_TOKENS = 100_000


# ── 공통 유틸 ──────────────────────────────────────────────────────── #

def _resolve_dir() -> Path | None:
    for candidate in _GEMINI_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _project_id(path: str) -> str:
    return hashlib.sha256(path.encode()).hexdigest()[:8]


def _normalize(tokens: int) -> float:
    return min(tokens / _MAX_TOKENS, 1.0)


def _parse_offset(path: str, offset: int) -> tuple[int, int]:
    """offset부터 읽어 (증분 토큰 합계, 새 offset) 반환"""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
            new_offset = f.tell()
    except OSError:
        return 0, offset

    tokens = 0
    for line in data.splitlines():
        try:
            meta = json.loads(line).get("usageMetadata", {})
            tokens += meta.get("totalTokenCount", 0)
        except json.JSONDecodeError:
            continue
    return tokens, new_offset


def _make_feed(path: str, tokens: int) -> FeedData:
    return FeedData(
        project_id=_project_id(path),
        project_name=Path(path).stem,
        raw_value=float(tokens),
        normalized=_normalize(tokens),
        source="gemini",
        timestamp=datetime.now(),
    )


# ── watchdog 핸들러 팩토리 ─────────────────────────────────────────── #

def _make_watchdog_handler(feed_queue: queue.Queue):
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._offsets: dict[str, int] = {}

        def on_modified(self, event):
            if event.is_directory or not event.src_path.endswith(".json"):
                return
            path = event.src_path
            tokens, new_offset = _parse_offset(path, self._offsets.get(path, 0))
            self._offsets[path] = new_offset
            if tokens > 0:
                feed_queue.put(_make_feed(path, tokens))

    return _Handler()


# ── Limb ───────────────────────────────────────────────────────────── #

class GeminiLimb(BaseLimb, PollingMixin):
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
        return target.rglob("*.json") if target else []

    def _parse_from_offset(self, path: str, offset: int) -> tuple[list[FeedData], int]:
        tokens, new_offset = _parse_offset(path, offset)
        if tokens <= 0:
            return [], new_offset
        return [_make_feed(path, tokens)], new_offset

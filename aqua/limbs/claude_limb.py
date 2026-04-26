"""
Claude Limb - ~/.claude/projects/**/*.jsonl 감시

전략: pick_strategy() → watchdog(이벤트) | polling(mtime, 5초 간격)
파싱: byte offset 기반 증분 읽기 (JSONL usage 필드)
프로젝트 식별: 경로 내 -home-...-<name> 폴더명 파싱
"""

import hashlib
import json
import queue
import threading
from datetime import datetime
from pathlib import Path

from interface import BaseLimb, FeedData
from limbs.polling_mixin import PollingMixin, pick_strategy

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
_MAX_TOKENS = 100_000


# ── 공통 유틸 ──────────────────────────────────────────────────────── #

def _project_name(path: str) -> str:
    # ~/.claude/projects/-home-user-Project-myapp/xxx.jsonl → "myapp"
    return Path(path).parent.name.rsplit("-", 1)[-1]


def _project_id(path: str) -> str:
    return hashlib.sha256(Path(path).parent.name.encode()).hexdigest()[:8]


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
            obj = json.loads(line)
            usage = obj.get("message", {}).get("usage", {})
            tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        except json.JSONDecodeError:
            continue
    return tokens, new_offset


def _make_feed(path: str, tokens: int) -> FeedData:
    return FeedData(
        project_id=_project_id(path),
        project_name=_project_name(path),
        raw_value=float(tokens),
        normalized=_normalize(tokens),
        source="claude",
        timestamp=datetime.now(),
    )


# ── watchdog 핸들러 팩토리 ─────────────────────────────────────────── #

def _make_watchdog_handler(feed_queue: queue.Queue):
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._offsets: dict[str, int] = {}

        def on_modified(self, event):
            if event.is_directory or not event.src_path.endswith(".jsonl"):
                return
            path = event.src_path
            tokens, new_offset = _parse_offset(path, self._offsets.get(path, 0))
            self._offsets[path] = new_offset
            if tokens > 0:
                feed_queue.put(_make_feed(path, tokens))

    return _Handler()


# ── Limb ───────────────────────────────────────────────────────────── #

class ClaudeLimb(BaseLimb, PollingMixin):
    @property
    def name(self) -> str:
        return "claude"

    def is_available(self) -> bool:
        return CLAUDE_PROJECTS_DIR.exists()

    def watch(self, feed_queue: queue.Queue, stop_event: threading.Event) -> None:
        if pick_strategy() == "watchdog":
            self._watchdog_watch(feed_queue, stop_event)
        else:
            self._poll_watch(feed_queue, stop_event)

    def _watchdog_watch(self, feed_queue: queue.Queue, stop_event: threading.Event) -> None:
        from watchdog.observers import Observer

        handler = _make_watchdog_handler(feed_queue)
        observer = Observer()
        observer.schedule(handler, str(CLAUDE_PROJECTS_DIR), recursive=True)
        observer.start()
        stop_event.wait()
        observer.stop()
        observer.join()

    # PollingMixin 구현 ────────────────────────────────────────────── #

    def _iter_target_files(self):
        return CLAUDE_PROJECTS_DIR.rglob("*.jsonl")

    def _parse_from_offset(self, path: str, offset: int) -> tuple[list[FeedData], int]:
        tokens, new_offset = _parse_offset(path, offset)
        if tokens <= 0:
            return [], new_offset
        return [_make_feed(path, tokens)], new_offset

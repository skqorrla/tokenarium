"""
Codex Limb - ~/.codex/sessions/**/*.jsonl 감시 (OpenAI Codex CLI)

전략: pick_strategy() → watchdog(이벤트) | polling(mtime, 5초 간격)
파싱: type=="event_msg" AND payload.type=="token_count" 인 줄에서
      payload.info.last_token_usage.input_tokens + output_tokens (콜 단위)
경로: ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl
"""

import json
import queue
import threading
from pathlib import Path

from interface import BaseLimb, FeedData
from limbs.polling_mixin import PollingMixin, pick_strategy

CODEX_DIR = Path.home() / ".codex"
_MAX_TOKENS = 100_000


# ── 공통 유틸 ──────────────────────────────────────────────────────── #

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
            if obj.get("type") != "event_msg":
                continue
            payload = obj.get("payload", {})
            if payload.get("type") != "token_count":
                continue
            usage = payload.get("info", {}).get("last_token_usage", {})
            tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        except json.JSONDecodeError:
            continue
    return tokens, new_offset


def _make_feed(path: str, tokens: int) -> FeedData:
    return FeedData(
        dir=Path(path).stem,
        agent_name="codex",
        total_token=tokens,
        normalized=_normalize(tokens),
        session=Path(path).stem,
    )


# ── watchdog 핸들러 팩토리 ─────────────────────────────────────────── #

def _make_watchdog_handler(feed_queue: queue.Queue):
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._offsets: dict[str, int] = {}

        def on_modified(self, event):
            if event.is_directory:
                return
            path = event.src_path
            if not (path.endswith(".json") or path.endswith(".jsonl")):
                return
            tokens, new_offset = _parse_offset(path, self._offsets.get(path, 0))
            self._offsets[path] = new_offset
            if tokens > 0:
                feed_queue.put(_make_feed(path, tokens))

    return _Handler()


# ── Limb ───────────────────────────────────────────────────────────── #

class CodexLimb(BaseLimb, PollingMixin):
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
        tokens, new_offset = _parse_offset(path, offset)
        if tokens <= 0:
            return [], new_offset
        return [_make_feed(path, tokens)], new_offset

"""
PollingMixin - watchdog 불가 시 mtime 기반 폴링 fallback

pick_strategy() 우선순위:
  1. "watchdog" : watchdog 라이브러리 설치됨 (이벤트 기반, < 1초)
  2. "polling"  : mtime + byte offset 기반 (POLL_INTERVAL초 간격)

TODO: Linux/WSL 환경에서 inotify 직접 호출 전략 추가 가능
      ctypes로 IN_MODIFY 이벤트 수신 → polling sleep 제거
"""

import os
import queue
import threading


def pick_strategy() -> str:
    try:
        from watchdog.observers import Observer  # noqa: F401
        return "watchdog"
    except ImportError:
        return "polling"


class PollingMixin:
    POLL_INTERVAL = 5  # seconds

    def _iter_target_files(self):
        """폴링 대상 파일 경로 목록 반환 (각 Limb가 구현)"""
        raise NotImplementedError

    def _parse_from_offset(self, path: str, offset: int) -> tuple[list, int]:
        """offset부터 신규 줄 파싱 → (FeedData 리스트, 새 offset) 반환 (각 Limb가 구현)"""
        raise NotImplementedError

    def _poll_watch(self, feed_queue: queue.Queue, stop_event: threading.Event) -> None:
        state: dict[str, tuple[float, int]] = {}  # {path: (mtime, offset)}
        while not stop_event.is_set():
            for path in self._iter_target_files():
                path = str(path)
                try:
                    mtime = os.stat(path).st_mtime
                except FileNotFoundError:
                    continue
                prev_mtime, prev_offset = state.get(path, (0.0, 0))
                if mtime != prev_mtime:
                    feeds, new_offset = self._parse_from_offset(path, prev_offset)
                    state[path] = (mtime, new_offset)
                    for feed in feeds:
                        feed_queue.put(feed)
            stop_event.wait(timeout=self.POLL_INTERVAL)

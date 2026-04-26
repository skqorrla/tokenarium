"""
Git Limb - 프로젝트 .git/COMMIT_EDITMSG 감시

커밋 1회 = COMMIT_EDITMSG on_modified 이벤트 1회.
전략: pick_strategy() → watchdog(이벤트) | polling(mtime, 5초 간격)
폴링: PollingMixin 미사용. COMMIT_EDITMSG mtime 비교로 단독 구현.
"""

import os
import queue
import threading
from pathlib import Path

from interface import BaseLimb, FeedData
from limbs.polling_mixin import pick_strategy

_MAX_COMMITS = 50  # 정규화 기준 최대 커밋 수


# ── 공통 유틸 ──────────────────────────────────────────────────────── #

def _make_feed(project_path: Path, commit_count: int) -> FeedData:
    return FeedData(
        dir=project_path.name,
        agent_name="git",
        total_token=0,
        normalized=min(commit_count / _MAX_COMMITS, 1.0),
        line_diff=commit_count,
    )


# ── watchdog 핸들러 팩토리 ─────────────────────────────────────────── #

def _make_watchdog_handler(feed_queue: queue.Queue, project_path: Path):
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._commit_count = 0

        def on_modified(self, event):
            if event.is_directory or not event.src_path.endswith("COMMIT_EDITMSG"):
                return
            self._commit_count += 1
            feed_queue.put(_make_feed(project_path, self._commit_count))

    return _Handler()


# ── 프로젝트별 감시 함수 ───────────────────────────────────────────── #

def _watchdog_single(
    project_path: Path,
    feed_queue: queue.Queue,
    stop_event: threading.Event,
) -> None:
    from watchdog.observers import Observer

    git_dir = project_path / ".git"
    if not git_dir.exists():
        return
    handler = _make_watchdog_handler(feed_queue, project_path)
    observer = Observer()
    observer.schedule(handler, str(git_dir), recursive=False)
    observer.start()
    stop_event.wait()
    observer.stop()
    observer.join()


def _poll_single(
    project_path: Path,
    feed_queue: queue.Queue,
    stop_event: threading.Event,
    poll_interval: int,
) -> None:
    """COMMIT_EDITMSG mtime 변화로 커밋 감지 (폴링 fallback)"""
    commit_msg = project_path / ".git" / "COMMIT_EDITMSG"
    if not commit_msg.exists():
        return

    prev_mtime = os.stat(commit_msg).st_mtime
    commit_count = 0

    while not stop_event.is_set():
        stop_event.wait(timeout=poll_interval)
        try:
            mtime = os.stat(commit_msg).st_mtime
        except FileNotFoundError:
            continue
        if mtime != prev_mtime:
            prev_mtime = mtime
            commit_count += 1
            feed_queue.put(_make_feed(project_path, commit_count))


# ── Limb ───────────────────────────────────────────────────────────── #

class GitLimb(BaseLimb):
    """
    GIT_WATCH_DIRS 목록의 프로젝트를 감시.
    목록이 비어 있으면 현재 작업 디렉토리만 감시.
    """

    POLL_INTERVAL = 5  # seconds

    def __init__(self, watch_dirs: list[Path] | None = None):
        self._watch_dirs = watch_dirs or [Path.cwd()]

    @property
    def name(self) -> str:
        return "git"

    def is_available(self) -> bool:
        return any((d / ".git").exists() for d in self._watch_dirs)

    def watch(self, feed_queue: queue.Queue, stop_event: threading.Event) -> None:
        strategy = pick_strategy()
        target_fn = _watchdog_single if strategy == "watchdog" else _poll_single

        threads = []
        for d in self._watch_dirs:
            extra = {} if strategy == "watchdog" else {"poll_interval": self.POLL_INTERVAL}
            t = threading.Thread(
                target=target_fn,
                kwargs={"project_path": d, "feed_queue": feed_queue,
                        "stop_event": stop_event, **extra},
                daemon=True,
            )
            t.start()
            threads.append(t)
        stop_event.wait()

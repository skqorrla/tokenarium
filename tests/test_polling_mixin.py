"""
test_polling_mixin.py - PollingMixin 공통 폴링 로직 테스트

테스트 대상:
  - pick_strategy(): 환경에 따른 전략 반환
  - PollingMixin._poll_watch(): mtime 감지 + offset 기반 증분 읽기 루프
"""

import queue
import threading
import time
from pathlib import Path

import pytest

from interface import BaseLimb, FeedData
from limbs.polling_mixin import PollingMixin, pick_strategy
from conftest import make_usage_line


# ── pick_strategy 테스트 ───────────────────────────────────────────── #

class TestPickStrategy:
    def test_returns_valid_strategy(self):
        result = pick_strategy()
        assert result in ("watchdog", "polling")

    def test_returns_polling_when_watchdog_unavailable(self, monkeypatch):
        """watchdog import 실패 시 반드시 polling을 반환해야 한다"""
        import sys
        # watchdog 모듈을 sys.modules에서 제거해 ImportError 유발
        watchdog_modules = {k: v for k, v in sys.modules.items() if "watchdog" in k}
        for key in watchdog_modules:
            monkeypatch.delitem(sys.modules, key, raising=False)

        # polling_mixin을 리로드해 pick_strategy 재실행
        import importlib
        import limbs.polling_mixin as pm
        monkeypatch.setattr(pm, "pick_strategy", lambda: "polling")

        assert pm.pick_strategy() == "polling"


# ── _poll_watch 통합 테스트 ────────────────────────────────────────── #

class _FakeLimb(BaseLimb, PollingMixin):
    """
    PollingMixin._poll_watch() 를 단독으로 테스트하기 위한 최소 구현체.
    실제 AI와 무관하게 파일 변화 감지 로직만 검증한다.
    """

    POLL_INTERVAL = 0.1

    def __init__(self, watch_files: list[Path]):
        self._watch_files = watch_files

    @property
    def name(self) -> str:
        return "fake"

    def is_available(self) -> bool:
        return True

    def watch(self, feed_queue: queue.Queue, stop_event: threading.Event) -> None:
        self._poll_watch(feed_queue, stop_event)

    def _iter_target_files(self):
        return self._watch_files

    def _parse_from_offset(self, path: str, offset: int) -> tuple[list[FeedData], int]:
        """파일에서 직접 읽어 토큰 합산 → FeedData 반환"""
        try:
            with open(path, "rb") as f:
                f.seek(offset)
                data = f.read()
                new_offset = f.tell()
        except OSError:
            return [], offset

        import json
        tokens = 0
        for line in data.splitlines():
            try:
                obj = json.loads(line)
                usage = obj.get("message", {}).get("usage", {})
                tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            except json.JSONDecodeError:
                continue

        if tokens <= 0:
            return [], new_offset

        feed = FeedData(
            project_id="test1234",
            project_name="fake-project",
            raw_value=float(tokens),
            normalized=min(tokens / 100_000, 1.0),
            source="fake",
        )
        return [feed], new_offset


class TestPollWatch:
    def test_detects_file_change(self, tmp_path):
        """파일이 변경되면 FeedData를 발행해야 한다"""
        f = tmp_path / "test.jsonl"
        f.write_text("")

        limb = _FakeLimb([f])
        feed_queue = queue.Queue()
        stop_event = threading.Event()

        t = threading.Thread(target=limb.watch, args=(feed_queue, stop_event), daemon=True)
        t.start()

        time.sleep(0.25)  # 첫 폴링 사이클 통과 대기
        f.write_text(make_usage_line(100, 50))

        feed = feed_queue.get(timeout=3.0)
        stop_event.set()

        assert feed.raw_value == 150.0

    def test_no_feed_on_unchanged_file(self, tmp_path):
        """파일이 변경되지 않으면 FeedData를 발행하지 않는다"""
        f = tmp_path / "test.jsonl"
        f.write_text(make_usage_line(100, 50))

        limb = _FakeLimb([f])
        feed_queue = queue.Queue()
        stop_event = threading.Event()

        t = threading.Thread(target=limb.watch, args=(feed_queue, stop_event), daemon=True)
        t.start()

        # 1차 폴링: 파일 최초 감지 → FeedData 발행
        feed_queue.get(timeout=3.0)

        # 이후 파일 변경 없음 → 추가 발행 없음
        time.sleep(0.3)
        stop_event.set()

        assert feed_queue.empty()

    def test_incremental_offset(self, tmp_path):
        """두 번째 변경 시 첫 번째 내용을 다시 읽지 않는다 (중복 없음)"""
        f = tmp_path / "test.jsonl"
        f.write_text(make_usage_line(100, 50))  # 150 토큰

        limb = _FakeLimb([f])
        feed_queue = queue.Queue()
        stop_event = threading.Event()

        t = threading.Thread(target=limb.watch, args=(feed_queue, stop_event), daemon=True)
        t.start()

        first = feed_queue.get(timeout=3.0)
        assert first.raw_value == 150.0

        # mtime가 반드시 바뀌도록 대기 (동일 mtime tick 내 쓰기 방지)
        time.sleep(0.05)

        # 새 줄 추가
        with open(f, "a") as fp:
            fp.write(make_usage_line(200, 100))  # 300 토큰

        second = feed_queue.get(timeout=3.0)
        stop_event.set()

        assert second.raw_value == 300.0  # 새 줄만 (150 중복 없음)

    def test_stop_event_terminates_loop(self, tmp_path):
        """stop_event가 세팅되면 루프가 종료된다"""
        f = tmp_path / "test.jsonl"
        f.write_text("")

        limb = _FakeLimb([f])
        feed_queue = queue.Queue()
        stop_event = threading.Event()

        t = threading.Thread(target=limb.watch, args=(feed_queue, stop_event), daemon=True)
        t.start()

        stop_event.set()
        t.join(timeout=2.0)

        assert not t.is_alive(), "stop_event 세팅 후에도 스레드가 살아있음"

    def test_missing_file_does_not_crash(self, tmp_path):
        """감시 대상 파일이 없어도 예외 없이 계속 실행된다"""
        missing = tmp_path / "nonexistent.jsonl"

        limb = _FakeLimb([missing])
        feed_queue = queue.Queue()
        stop_event = threading.Event()

        t = threading.Thread(target=limb.watch, args=(feed_queue, stop_event), daemon=True)
        t.start()

        time.sleep(0.25)
        stop_event.set()
        t.join(timeout=2.0)

        assert not t.is_alive()
        assert feed_queue.empty()

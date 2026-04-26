"""
Orchestrator - Limb 생명주기 관리 + FeedData 수집 및 라우팅

동작 방식:
  1. 등록된 Limb들을 각각 독립 daemon 스레드에서 실행
  2. 각 Limb는 watch() 안에서 pick_strategy()에 따라 watchdog 또는 polling으로 FeedData 생성
  3. FeedData는 thread-safe Queue를 통해 메인 스레드로 전달
  4. Limb 스레드가 예외로 종료되면 MAX_RETRIES 내에서 자동 재시작
  5. 메인 루프는 Queue에서 FeedData를 꺼내 DataStore 저장 + Renderer 갱신 콜백 호출
"""

import queue
import threading
import time

from interface import BaseLimb, FeedData  # watch() 추상 메서드 계약 준수

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


class Orchestrator:
    def __init__(self, store, on_feed=None):
        self._limbs: list[BaseLimb] = []
        self._threads: dict[str, threading.Thread] = {}
        self._retry_counts: dict[str, int] = {}
        self._feed_queue: queue.Queue[FeedData] = queue.Queue()
        self._store = store
        self._on_feed = on_feed  # Renderer 갱신 콜백
        self._stop_event = threading.Event()

    # ── Limb 등록 ──────────────────────────────────────────────────── #

    def register(self, limb: BaseLimb) -> None:
        if limb.is_available():
            self._limbs.append(limb)
            print(f"[Orchestrator] registered: {limb.name}")
        else:
            print(f"[Orchestrator] skipped (unavailable): {limb.name}")

    # ── Limb 스레드 실행 ───────────────────────────────────────────── #

    def start(self) -> None:
        for limb in self._limbs:
            self._retry_counts[limb.name] = 0
            self._launch_limb(limb)

    def _launch_limb(self, limb: BaseLimb) -> None:
        t = threading.Thread(
            target=self._watch_loop,
            args=(limb,),
            name=f"limb-{limb.name}",
            daemon=True,
        )
        self._threads[limb.name] = t
        t.start()

    def _watch_loop(self, limb: BaseLimb) -> None:
        """각 Limb의 감시 루프. 예외 발생 시 MAX_RETRIES까지 자동 재시작."""
        while not self._stop_event.is_set():
            try:
                limb.watch(self._feed_queue, self._stop_event)
            except Exception as exc:
                limb.on_error(exc)
                self._retry_counts[limb.name] += 1
                if self._retry_counts[limb.name] > MAX_RETRIES:
                    print(f"[Orchestrator] {limb.name} exceeded max retries. disabled.")
                    return
                print(f"[Orchestrator] {limb.name} restarting in {RETRY_DELAY}s "
                      f"(retry {self._retry_counts[limb.name]}/{MAX_RETRIES})")
                time.sleep(RETRY_DELAY)

    # ── 메인 루프: Queue → DataStore → Renderer ────────────────────── #

    def run_dispatch_loop(self) -> None:
        """메인 스레드에서 호출. FeedData를 소비해 저장 + 렌더 알림."""
        while not self._stop_event.is_set():
            try:
                feed: FeedData = self._feed_queue.get(timeout=1.0)
                self._store.save_feed(feed)
                self._store.update_fish_state(feed.project_id, feed.normalized)
                if self._on_feed:
                    self._on_feed(feed)
            except queue.Empty:
                continue

    # ── 종료 ───────────────────────────────────────────────────────── #

    def stop(self) -> None:
        self._stop_event.set()

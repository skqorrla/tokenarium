"""
main.py - 컴포넌트 초기화 및 전체 루프 연결

담당: 배선(wiring)만. 비즈니스 로직 없음.

스텁 처리 전략:
  - AquariumRenderer 미구현 시 → print 콜백으로 대체, 경고 출력
"""

import signal
import sys
from pathlib import Path

import config
from orchestrator import Orchestrator
from store import DataStore
from limbs.claude_limb import ClaudeLimb
from limbs.codex_limb import CodexLimb
from limbs.gemini_limb import GeminiLimb


def _resolve_store(db_path: str) -> DataStore:
    store = DataStore(db_path)
    store.init_db()
    return store


def _resolve_renderer(store):
    try:
        from renderer import AquariumRenderer
        renderer = AquariumRenderer(store)
        renderer.on_feed  # 속성 존재 여부 확인
        return renderer
    except (ImportError, NotImplementedError, AttributeError):
        print("[aqua] WARNING: AquariumRenderer 미구현 → 콘솔 출력으로 실행")
        return None


# ── 진입 함수 ──────────────────────────────────────────────────────── #

def run(db_path: str | None = None) -> None:
    db_path = db_path or config.DB_PATH

    # 1. DataStore
    store = _resolve_store(db_path)

    # 2. Renderer (미구현이면 None)
    renderer = _resolve_renderer(store)
    on_feed = (
        renderer.on_feed
        if renderer
        else lambda feed: print(
            f"[feed] {feed.agent_name:<8} {feed.dir:<20} +{feed.normalized:.3f}"
        )
    )

    # 3. Orchestrator
    orchestrator = Orchestrator(store, on_feed=on_feed)

    # 4. Limb 등록
    limbs = [
        ClaudeLimb(),
        CodexLimb(),
        GeminiLimb(),
    ]
    for limb in limbs:
        orchestrator.register(limb)

    # 5. Renderer 시작 (별도 스레드)
    if renderer:
        renderer.start()

    # 6. Limb daemon 스레드 시작
    orchestrator.start()

    # 7. 종료 시그널 등록 (Ctrl+C / SIGTERM)
    def _shutdown(sig, frame):
        print("\n[aqua] shutting down...")
        orchestrator.stop()
        if renderer:
            renderer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 8. 메인 스레드 블로킹 루프 (stop_event 세팅 전까지 무한 실행)
    orchestrator.run_dispatch_loop()

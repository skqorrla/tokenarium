import queue
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FeedData:
    project_id: str        # sha256(cwd)[:8]
    project_name: str      # 폴더명
    raw_value: float       # 원시값 (토큰 수, 커밋 수)
    normalized: float      # 0.0 ~ 1.0
    source: str            # "claude" | "codex" | "gemini" | "git"
    timestamp: datetime = field(default_factory=datetime.now)


class BaseLimb(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """팔다리 식별자"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """현재 환경에서 동작 가능 여부 (설치 여부, 경로 존재 여부)"""
        ...

    @abstractmethod
    def watch(self, feed_queue: queue.Queue, stop_event: threading.Event) -> None:
        """파일 감시 루프. Orchestrator가 전용 daemon 스레드에서 호출."""
        ...

    def on_error(self, exc: Exception) -> None:
        """에러 발생 시 Orchestrator가 호출"""
        print(f"[{self.name}] error: {exc}")

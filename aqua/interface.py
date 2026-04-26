import queue
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FeedData:
    dir: str               # project.dir     (프로젝트 폴더명)
    agent_name: str        # agent.agent_name ("claude"|"codex"|"gemini"|"git")
    total_token: int       # info.total_token
    normalized: float      # 0.0 ~ 1.0 (DB 저장 안 함, fish XP 계산용)
    created_at: datetime = field(default_factory=datetime.now)
    model_name: str = ""   # agent.model_name
    session: str = ""      # project.session
    line_diff: int = 0     # info.line_diff


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

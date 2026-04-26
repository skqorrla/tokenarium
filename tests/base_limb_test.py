"""
base_limb_test.py - 모든 Limb 테스트가 상속하는 공통 계약

사용 방법:
    class TestCodexLimb(LimbContractMixin):
        def _make_limb(self): return CodexLimb()
        def _expected_source(self): return "codex"

이 클래스 자체는 pytest가 수집하지 않음 (Test 접두사 없음).
상속한 TestXxx 클래스에서 test_ 메서드가 자동으로 실행됨.
"""

from interface import FeedData


class LimbContractMixin:
    """
    모든 Limb이 반드시 통과해야 할 기본 계약.
    서브클래스에서 아래 두 메서드를 구현해야 함.
    """

    def _make_limb(self):
        raise NotImplementedError

    def _expected_agent_name(self) -> str:
        raise NotImplementedError

    # ── 공통 테스트 ────────────────────────────────────────────────── #

    def test_name_is_nonempty_string(self):
        limb = self._make_limb()
        assert isinstance(limb.name, str)
        assert limb.name != ""

    def test_on_error_does_not_raise(self):
        """에러 핸들러가 예외를 밖으로 던지지 않아야 한다"""
        limb = self._make_limb()
        limb.on_error(ValueError("테스트 에러"))  # 예외 없이 통과해야 함

    def test_is_available_returns_bool(self, tmp_path):
        limb = self._make_limb()
        result = limb.is_available()
        assert isinstance(result, bool)

    # ── FeedData 검증 헬퍼 (서브클래스 테스트에서 호출) ──────────── #

    @staticmethod
    def assert_feed_valid(feed, expected_agent_name: str):
        """FeedData 필드 정합성 공통 검증"""
        assert isinstance(feed, FeedData), f"FeedData 타입이어야 함, 실제: {type(feed)}"
        assert feed.agent_name == expected_agent_name, f"agent_name: {feed.agent_name!r} != {expected_agent_name!r}"
        assert feed.normalized >= 0.0,                 f"normalized 음수: {feed.normalized}"
        assert feed.dir != "",                          "dir 비어있음"
        assert feed.total_token >= 0,                  f"total_token 음수: {feed.total_token}"
        assert feed.created_at is not None,            "created_at 없음"

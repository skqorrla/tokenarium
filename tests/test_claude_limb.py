"""
test_claude_limb.py - ClaudeLimb 및 토큰 인식 로직 테스트

계층 구조:
  1. 순수 함수 단위 테스트  (_project_name, _normalize, _project_id)
  2. 파일 파싱 테스트        (_parse_offset - tmp_path 사용)
  3. FeedData 생성 테스트    (_parse_from_offset 반환값 검증)
  4. Limb 동작 통합 테스트   (polling 모드, 실제 watch 루프)
"""

import queue
import threading
import time

import pytest

from limbs.claude_limb import (
    ClaudeLimb,
    _make_feed,
    _normalize,
    _parse_offset,
    _project_id,
    _project_name,
)
from base_limb_test import LimbContractMixin
from conftest import make_broken_line, make_non_usage_line, make_usage_line


# ── 1. 순수 함수 단위 테스트 ───────────────────────────────────────── #

class TestProjectName:
    def test_normal_path(self):
        path = "/home/user/.claude/projects/-home-user-Project-myapp/abc.jsonl"
        assert _project_name(path) == "myapp"

    def test_short_folder_no_hyphen(self):
        """하이픈이 하나뿐인 폴더: rsplit 마지막 토큰 반환"""
        path = "/home/user/.claude/projects/-myapp/abc.jsonl"
        assert _project_name(path) == "myapp"

    def test_deep_nested_name(self):
        """하이픈이 많은 경로에서 마지막 세그먼트만 추출"""
        path = "/home/user/.claude/projects/-home-user-a-b-c-myapp/abc.jsonl"
        assert _project_name(path) == "myapp"


class TestNormalize:
    def test_zero_tokens(self):
        assert _normalize(0) == 0.0

    def test_half_max(self):
        assert _normalize(50_000) == pytest.approx(0.5)

    def test_at_max(self):
        assert _normalize(100_000) == 1.0

    def test_over_max_clamps_to_one(self):
        assert _normalize(200_000) == 1.0

    def test_small_value(self):
        result = _normalize(1_000)
        assert 0.0 < result < 1.0


class TestProjectId:
    def test_same_path_same_id(self):
        path = "/home/user/.claude/projects/-home-user-Project-myapp/abc.jsonl"
        assert _project_id(path) == _project_id(path)

    def test_different_path_different_id(self):
        path_a = "/home/user/.claude/projects/-home-user-Project-myapp/abc.jsonl"
        path_b = "/home/user/.claude/projects/-home-user-Project-otherapp/abc.jsonl"
        assert _project_id(path_a) != _project_id(path_b)

    def test_id_length_is_8(self):
        path = "/home/user/.claude/projects/-home-user-Project-myapp/abc.jsonl"
        assert len(_project_id(path)) == 8


# ── 2. 파일 파싱 테스트 ────────────────────────────────────────────── #

class TestParseOffset:
    def test_normal_jsonl(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(make_usage_line(100, 50) + make_usage_line(200, 100))

        tokens, new_offset = _parse_offset(str(f), 0)

        assert tokens == 450
        assert new_offset == f.stat().st_size

    def test_empty_file(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text("")

        tokens, new_offset = _parse_offset(str(f), 0)

        assert tokens == 0
        assert new_offset == 0

    def test_ignores_broken_lines(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(
            make_usage_line(100, 50)
            + make_broken_line()
            + make_usage_line(200, 100)
        )

        tokens, _ = _parse_offset(str(f), 0)

        assert tokens == 450  # 깨진 줄 무시

    def test_ignores_non_usage_lines(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(make_non_usage_line() + make_usage_line(100, 50))

        tokens, _ = _parse_offset(str(f), 0)

        assert tokens == 150  # usage 없는 줄 무시

    def test_file_not_found(self, tmp_path):
        missing = str(tmp_path / "nonexistent.jsonl")

        tokens, new_offset = _parse_offset(missing, 0)

        assert tokens == 0
        assert new_offset == 0  # offset 유지 (예외 없음)

    def test_incremental_offset_no_duplicate(self, tmp_path):
        """핵심: offset 기반 증분 읽기 - 이전에 읽은 줄을 다시 읽지 않는다"""
        f = tmp_path / "session.jsonl"
        first_line = make_usage_line(100, 50)
        f.write_text(first_line)

        # 1차 읽기
        tokens1, offset1 = _parse_offset(str(f), 0)
        assert tokens1 == 150

        # 파일에 새 줄 추가
        with open(f, "a") as fp:
            fp.write(make_usage_line(200, 100))

        # 2차 읽기: 이전 offset 부터 → 새 줄만 파싱
        tokens2, offset2 = _parse_offset(str(f), offset1)

        assert tokens2 == 300       # 새 줄만 (중복 없음)
        assert offset2 > offset1    # offset 전진


# ── 3. FeedData 생성 테스트 ────────────────────────────────────────── #

class TestParseFeedData:
    def test_returns_feed_when_tokens_positive(self, claude_jsonl):
        limb = ClaudeLimb()
        feeds, _ = limb._parse_from_offset(str(claude_jsonl), 0)

        assert len(feeds) == 1
        LimbContractMixin.assert_feed_valid(feeds[0], "claude")

    def test_returns_empty_on_zero_tokens(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(make_non_usage_line())  # 토큰 없는 줄만

        limb = ClaudeLimb()
        feeds, _ = limb._parse_from_offset(str(f), 0)

        assert feeds == []

    def test_feed_project_name(self, claude_project, claude_jsonl):
        limb = ClaudeLimb()
        feeds, _ = limb._parse_from_offset(str(claude_jsonl), 0)

        assert feeds[0].project_name == "myapp"

    def test_feed_raw_value(self, claude_jsonl):
        limb = ClaudeLimb()
        feeds, _ = limb._parse_from_offset(str(claude_jsonl), 0)

        assert feeds[0].raw_value == 150.0  # 100 + 50


# ── 4. Limb 동작 통합 테스트 ───────────────────────────────────────── #

class TestClaudeLimbAvailability:
    def test_available_when_dir_exists(self, monkeypatch, tmp_path):
        monkeypatch.setattr("limbs.claude_limb.CLAUDE_PROJECTS_DIR", tmp_path)
        assert ClaudeLimb().is_available() is True

    def test_unavailable_when_dir_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "limbs.claude_limb.CLAUDE_PROJECTS_DIR", tmp_path / "nonexistent"
        )
        assert ClaudeLimb().is_available() is False


class TestClaudeLimbIterFiles:
    def test_finds_jsonl_files(self, monkeypatch, claude_projects_dir, claude_jsonl):
        monkeypatch.setattr(
            "limbs.claude_limb.CLAUDE_PROJECTS_DIR", claude_projects_dir
        )
        limb = ClaudeLimb()
        files = list(limb._iter_target_files())

        assert claude_jsonl in files

    def test_finds_multiple_projects(self, monkeypatch, claude_projects_dir):
        """여러 프로젝트 디렉토리의 파일을 모두 탐색"""
        for proj in ["proj-A", "proj-B"]:
            d = claude_projects_dir / f"-home-user-{proj}"
            d.mkdir()
            (d / "session.jsonl").write_text(make_usage_line(100, 50))

        monkeypatch.setattr(
            "limbs.claude_limb.CLAUDE_PROJECTS_DIR", claude_projects_dir
        )
        files = list(ClaudeLimb()._iter_target_files())

        assert len(files) == 2


class TestClaudeLimbPollingIntegration:
    """
    polling 모드로 실제 watch 루프 동작 검증.
    watchdog 이벤트 없이도 토큰 변화를 감지해야 한다.
    """

    def test_polling_detects_new_tokens(self, monkeypatch, claude_projects_dir):
        # 빈 파일로 시작
        proj_dir = claude_projects_dir / "-home-user-Project-myapp"
        proj_dir.mkdir()
        jsonl = proj_dir / "session.jsonl"
        jsonl.write_text("")

        monkeypatch.setattr("limbs.claude_limb.CLAUDE_PROJECTS_DIR", claude_projects_dir)
        monkeypatch.setattr("limbs.claude_limb.pick_strategy", lambda: "polling")

        limb = ClaudeLimb()
        limb.POLL_INTERVAL = 0.1  # 테스트용 빠른 간격

        feed_queue = queue.Queue()
        stop_event = threading.Event()

        t = threading.Thread(
            target=limb.watch, args=(feed_queue, stop_event), daemon=True
        )
        t.start()

        # 첫 폴링 사이클이 빈 파일 상태를 기록하도록 대기
        time.sleep(0.25)

        # 토큰 데이터 추가
        jsonl.write_text(make_usage_line(100, 50))

        feed = feed_queue.get(timeout=3.0)  # 최대 3초 대기
        stop_event.set()

        assert feed.source == "claude"
        assert feed.project_name == "myapp"
        assert feed.raw_value == 150.0
        assert 0.0 < feed.normalized <= 1.0

    def test_polling_no_duplicate_on_second_cycle(self, monkeypatch, claude_projects_dir):
        """같은 파일을 두 번 폴링해도 동일한 토큰을 중복 발행하지 않는다"""
        proj_dir = claude_projects_dir / "-home-user-Project-myapp"
        proj_dir.mkdir()
        jsonl = proj_dir / "session.jsonl"
        jsonl.write_text(make_usage_line(100, 50))

        monkeypatch.setattr("limbs.claude_limb.CLAUDE_PROJECTS_DIR", claude_projects_dir)
        monkeypatch.setattr("limbs.claude_limb.pick_strategy", lambda: "polling")

        limb = ClaudeLimb()
        limb.POLL_INTERVAL = 0.1

        feed_queue = queue.Queue()
        stop_event = threading.Event()

        t = threading.Thread(
            target=limb.watch, args=(feed_queue, stop_event), daemon=True
        )
        t.start()

        # FeedData 1개 수신 후 추가 발행 없음 확인
        first = feed_queue.get(timeout=3.0)
        assert first.raw_value == 150.0

        # 충분한 시간 동안 추가 데이터 없음
        time.sleep(0.3)
        stop_event.set()

        assert feed_queue.empty(), "중복 FeedData가 발행됨"

    def test_polling_detects_multiple_projects(self, monkeypatch, claude_projects_dir):
        """여러 프로젝트가 동시에 감시될 때 각각 별도 FeedData를 발행한다"""
        for proj, tokens in [("proj-A", (100, 50)), ("proj-B", (200, 100))]:
            d = claude_projects_dir / f"-home-user-{proj}"
            d.mkdir()
            (d / "session.jsonl").write_text(make_usage_line(*tokens))

        monkeypatch.setattr("limbs.claude_limb.CLAUDE_PROJECTS_DIR", claude_projects_dir)
        monkeypatch.setattr("limbs.claude_limb.pick_strategy", lambda: "polling")

        limb = ClaudeLimb()
        limb.POLL_INTERVAL = 0.1

        feed_queue = queue.Queue()
        stop_event = threading.Event()

        t = threading.Thread(
            target=limb.watch, args=(feed_queue, stop_event), daemon=True
        )
        t.start()

        feeds = []
        for _ in range(2):
            feeds.append(feed_queue.get(timeout=3.0))
        stop_event.set()

        project_names = {f.project_name for f in feeds}
        project_ids   = {f.project_id   for f in feeds}

        assert project_names == {"A", "B"}
        assert len(project_ids) == 2  # 서로 다른 project_id


# ── LimbContractMixin 계약 테스트 ─────────────────────────────────── #

class TestClaudeLimbContract(LimbContractMixin):
    """공통 계약 테스트 - 3개 메서드만 구현하면 6개 테스트 자동 실행"""

    def _make_limb(self):
        return ClaudeLimb()

    def _expected_source(self):
        return "claude"

"""
test_claude_limb.py - ClaudeLimb 및 토큰 인식 로직 테스트

계층 구조:
  1. 순수 함수 단위 테스트  (_project_name)
  2. 파일 파싱 테스트        (_parse_offset - tmp_path 사용)
  3. FeedData 생성 테스트    (_parse_from_offset 반환값 검증)
  4. Limb 동작 통합 테스트   (polling 모드, 실제 watch 루프)

토큰 계산: output_tokens * 1.3 (input_tokens 미포함, 정규화 없음)
"""

import queue
import threading
import time

import pytest

from limbs.claude_limb import (
    ClaudeLimb,
    _make_feed,
    _parse_offset,
    _project_name,
)
from base_limb_test import LimbContractMixin
from conftest import make_broken_line, make_messages_line, make_non_usage_line, make_usage_line


# ── 1. 순수 함수 단위 테스트 ───────────────────────────────────────── #

class TestProjectName:
    def test_normal_path(self):
        path = "/home/user/.claude/projects/-home-user-Project-myapp/abc.jsonl"
        assert _project_name(path) == "myapp"

    def test_short_folder_no_hyphen(self):
        path = "/home/user/.claude/projects/-myapp/abc.jsonl"
        assert _project_name(path) == "myapp"

    def test_deep_nested_name(self):
        path = "/home/user/.claude/projects/-home-user-a-b-c-myapp/abc.jsonl"
        assert _project_name(path) == "myapp"


# ── 2. 파일 파싱 테스트 ────────────────────────────────────────────── #

class TestParseOffset:
    def test_normal_jsonl(self, tmp_path):
        # output=50 → 65, output=100 → 130, 합계=195
        f = tmp_path / "session.jsonl"
        f.write_text(make_usage_line(100, 50) + make_usage_line(200, 100))

        tokens, line_diff, new_offset = _parse_offset(str(f), 0)

        assert tokens == 195
        assert new_offset == f.stat().st_size

    def test_empty_file(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text("")

        tokens, line_diff, new_offset = _parse_offset(str(f), 0)

        assert tokens == 0
        assert new_offset == 0

    def test_ignores_broken_lines(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(
            make_usage_line(100, 50)
            + make_broken_line()
            + make_usage_line(200, 100)
        )

        tokens, _, _ = _parse_offset(str(f), 0)

        assert tokens == 195

    def test_ignores_non_usage_lines(self, tmp_path):
        # output=50 → 65
        f = tmp_path / "session.jsonl"
        f.write_text(make_non_usage_line() + make_usage_line(100, 50))

        tokens, _, _ = _parse_offset(str(f), 0)

        assert tokens == 65

    def test_file_not_found(self, tmp_path):
        missing = str(tmp_path / "nonexistent.jsonl")

        tokens, line_diff, new_offset = _parse_offset(missing, 0)

        assert tokens == 0
        assert line_diff == 0
        assert new_offset == 0

    def test_incremental_offset_no_duplicate(self, tmp_path):
        """offset 기반 증분 읽기 - 이전에 읽은 줄을 다시 읽지 않는다"""
        f = tmp_path / "session.jsonl"
        f.write_text(make_usage_line(100, 50))  # output=50 → 65

        tokens1, _, offset1 = _parse_offset(str(f), 0)
        assert tokens1 == 65

        with open(f, "a") as fp:
            fp.write(make_usage_line(200, 100))  # output=100 → 130

        tokens2, _, offset2 = _parse_offset(str(f), offset1)

        assert tokens2 == 130
        assert offset2 > offset1

    def test_counts_newlines_in_messages(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(make_messages_line("line1\nline2\nline3"))

        _, line_diff, _ = _parse_offset(str(f), 0)

        assert line_diff == 2

    def test_line_diff_zero_when_no_messages_key(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(make_usage_line(100, 50))

        _, line_diff, _ = _parse_offset(str(f), 0)

        assert line_diff == 0

    def test_line_diff_accumulates_across_lines(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(
            make_messages_line("a\nb") + make_messages_line("c\nd\ne")
        )

        _, line_diff, _ = _parse_offset(str(f), 0)

        assert line_diff == 3  # 1 + 2

    def test_only_output_tokens_counted(self, tmp_path):
        """input_tokens는 무시하고 output_tokens * 1.3만 집계"""
        f = tmp_path / "session.jsonl"
        f.write_text(make_usage_line(999, 100))  # output=100 → 130

        tokens, _, _ = _parse_offset(str(f), 0)

        assert tokens == 130


# ── 3. FeedData 생성 테스트 ────────────────────────────────────────── #

class TestParseFeedData:
    def test_returns_feed_when_tokens_positive(self, claude_jsonl):
        limb = ClaudeLimb()
        feeds, _ = limb._parse_from_offset(str(claude_jsonl), 0)

        assert len(feeds) == 1
        LimbContractMixin.assert_feed_valid(feeds[0], "claude")

    def test_returns_empty_on_zero_tokens(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(make_non_usage_line())

        limb = ClaudeLimb()
        feeds, _ = limb._parse_from_offset(str(f), 0)

        assert feeds == []

    def test_feed_dir(self, claude_project, claude_jsonl):
        limb = ClaudeLimb()
        feeds, _ = limb._parse_from_offset(str(claude_jsonl), 0)

        assert feeds[0].dir == "myapp"

    def test_feed_total_token(self, claude_jsonl):
        # claude_jsonl: make_usage_line(100, 50) → output=50 * 1.3 = 65
        limb = ClaudeLimb()
        feeds, _ = limb._parse_from_offset(str(claude_jsonl), 0)

        assert feeds[0].total_token == 65

    def test_feed_normalized_equals_total_token(self, claude_jsonl):
        """normalized는 0~1 클램핑 없이 total_token과 동일한 값"""
        limb = ClaudeLimb()
        feeds, _ = limb._parse_from_offset(str(claude_jsonl), 0)

        assert feeds[0].normalized == float(feeds[0].total_token)

    def test_feed_session(self, claude_jsonl):
        limb = ClaudeLimb()
        feeds, _ = limb._parse_from_offset(str(claude_jsonl), 0)

        assert feeds[0].session == "session"

    def test_feed_line_diff(self, claude_project):
        f = claude_project / "session2.jsonl"
        f.write_text(
            make_usage_line(100, 50) + make_messages_line("line1\nline2")
        )

        limb = ClaudeLimb()
        feeds, _ = limb._parse_from_offset(str(f), 0)

        assert feeds[0].line_diff == 1


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
    def test_polling_detects_new_tokens(self, monkeypatch, claude_projects_dir):
        proj_dir = claude_projects_dir / "-home-user-Project-myapp"
        proj_dir.mkdir()
        jsonl = proj_dir / "session.jsonl"
        jsonl.write_text("")

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

        time.sleep(0.25)
        jsonl.write_text(make_usage_line(100, 50))  # output=50 → 65

        feed = feed_queue.get(timeout=3.0)
        stop_event.set()

        assert feed.agent_name == "claude"
        assert feed.dir == "myapp"
        assert feed.total_token == 65
        assert feed.normalized == 65.0

    def test_polling_no_duplicate_on_second_cycle(self, monkeypatch, claude_projects_dir):
        proj_dir = claude_projects_dir / "-home-user-Project-myapp"
        proj_dir.mkdir()
        jsonl = proj_dir / "session.jsonl"
        jsonl.write_text(make_usage_line(100, 50))  # output=50 → 65

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

        first = feed_queue.get(timeout=3.0)
        assert first.total_token == 65

        time.sleep(0.3)
        stop_event.set()

        assert feed_queue.empty(), "중복 FeedData가 발행됨"

    def test_polling_detects_multiple_projects(self, monkeypatch, claude_projects_dir):
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

        dirs = {f.dir for f in feeds}
        assert dirs == {"A", "B"}


# ── LimbContractMixin 계약 테스트 ─────────────────────────────────── #

class TestClaudeLimbContract(LimbContractMixin):
    def _make_limb(self):
        return ClaudeLimb()

    def _expected_agent_name(self):
        return "claude"

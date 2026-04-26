"""
conftest.py - 공유 픽스처 및 경로 설정

모든 테스트 파일에서 자동으로 로드됨.
aqua/ 디렉토리를 import 경로에 추가하고 공통 픽스처를 제공.
"""

import sys
from pathlib import Path

# aqua/ 를 import 경로에 추가 (tests/ 에서 aqua 모듈을 직접 import 가능하게)
sys.path.insert(0, str(Path(__file__).parent.parent / "aqua"))

import pytest


# ── JSONL 데이터 헬퍼 ──────────────────────────────────────────────── #

def make_usage_line(input_tokens: int, output_tokens: int) -> str:
    return (
        f'{{"type": "assistant", "message": {{"usage": {{"input_tokens": {input_tokens},'
        f' "output_tokens": {output_tokens}}}}}}}\n'
    )

def make_non_usage_line() -> str:
    """토큰 필드 없는 줄 (무시 대상)"""
    return '{"type": "permission-mode", "sessionId": "abc123"}\n'

def make_broken_line() -> str:
    """깨진 JSON 줄 (무시 대상)"""
    return "NOT_VALID_JSON\n"


# ── Claude 디렉토리 픽스처 ─────────────────────────────────────────── #

@pytest.fixture
def claude_projects_dir(tmp_path):
    """가짜 ~/.claude/projects/ 디렉토리"""
    d = tmp_path / "projects"
    d.mkdir()
    return d


@pytest.fixture
def claude_project(claude_projects_dir):
    """단일 프로젝트 디렉토리 (-home-user-Project-myapp)"""
    p = claude_projects_dir / "-home-user-Project-myapp"
    p.mkdir()
    return p


@pytest.fixture
def claude_jsonl(claude_project):
    """토큰 100+50=150 이 기록된 JSONL 파일"""
    f = claude_project / "session.jsonl"
    f.write_text(make_usage_line(100, 50))
    return f

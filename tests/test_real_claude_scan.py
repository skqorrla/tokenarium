"""
test_real_claude_scan.py - 실제 ~/.claude/projects/ 데이터 스캔

목적: 실제 토큰 수와 프로젝트명을 터미널에서 확인
실행: pytest tests/test_real_claude_scan.py -s -v
"""

import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "aqua"))

from limbs.claude_limb import CLAUDE_PROJECTS_DIR, _parse_offset, _project_name

pytestmark = pytest.mark.skipif(
    not CLAUDE_PROJECTS_DIR.exists(),
    reason=f"~/.claude/projects/ 없음 ({CLAUDE_PROJECTS_DIR})",
)


def _scan_all() -> dict[str, dict]:
    """실제 JSONL 파일을 전부 읽어 프로젝트별 토큰 합산"""
    projects: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "files": 0})
    for path in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        tokens, _, _ = _parse_offset(str(path), 0)
        name = _project_name(str(path))
        projects[name]["tokens"] += tokens
        projects[name]["files"] += 1
    return dict(projects)


class TestRealClaudeScan:
    def test_scan_and_print(self):
        """실제 데이터 스캔 후 요약 출력 — 값 검증은 느슨하게"""
        projects = _scan_all()

        print("\n")
        print("=" * 50)
        print("[Real Claude Scan]")
        print("=" * 50)
        for name, info in sorted(projects.items()):
            print(
                f"  Project: {name:<20} | "
                f"tokens: {info['tokens']:>8,} | "
                f"files: {info['files']}"
            )
        print("-" * 50)
        total_tokens = sum(v["tokens"] for v in projects.values())
        print(f"  Total projects : {len(projects)}")
        print(f"  Total tokens   : {total_tokens:,}")
        print("=" * 50)

        for name, info in projects.items():
            assert info["tokens"] >= 0, f"{name}: 토큰 수 음수"
            assert name != "", "프로젝트명 비어있음"
            assert info["files"] > 0, f"{name}: 파일 수 0"

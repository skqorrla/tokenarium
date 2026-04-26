"""seed_from_xlsx 적재 + 멱등성 테스트."""

import sqlite3
from pathlib import Path

import pytest

from seed import seed_from_xlsx
from store import DataStore


DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

# docs/*.xlsx 의 데이터 행수 (헤더 제외). 새 시드 파일/행 추가 시 함께 갱신.
EXPECTED_ROWS = {
    "agent": 6,
    "aquarium_stage": 4,
    "fish_species": 11,
    "dialogue": 40,
}


@pytest.fixture
def initialized_db(tmp_path):
    db = str(tmp_path / "test.db")
    DataStore(db).init_db()
    return db


def _count(db_path: str, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_seed_loads_all_xlsx_files(initialized_db):
    counts = seed_from_xlsx(initialized_db, DOCS_DIR)
    assert counts == EXPECTED_ROWS
    for table, expected in EXPECTED_ROWS.items():
        assert _count(initialized_db, table) == expected


def test_seed_is_idempotent_via_or_ignore(initialized_db):
    seed_from_xlsx(initialized_db, DOCS_DIR)
    seed_from_xlsx(initialized_db, DOCS_DIR)  # 두 번째 호출 — 충돌은 OR IGNORE
    for table, expected in EXPECTED_ROWS.items():
        assert _count(initialized_db, table) == expected


def test_seed_preserves_existing_rows(initialized_db):
    """OR IGNORE: 첫 적재만 반영. 기존 행과 PK 충돌 시 xlsx 값을 무시한다."""
    conn = sqlite3.connect(initialized_db)
    try:
        # xlsx 의 fish_species level_min=1 데이터(이모지 '🐟')와 충돌하는 행을 미리 삽입
        conn.execute(
            "INSERT INTO fish_species (level_min, emoji, name_kr, xp_required, is_legendary) "
            "VALUES (1, 'PRE', 'pre-existing', 999, 0)"
        )
        conn.commit()
    finally:
        conn.close()

    seed_from_xlsx(initialized_db, DOCS_DIR)

    conn = sqlite3.connect(initialized_db)
    try:
        emoji = conn.execute(
            "SELECT emoji FROM fish_species WHERE level_min=1"
        ).fetchone()[0]
    finally:
        conn.close()
    assert emoji == "PRE", "OR IGNORE 가 기존 행을 보존하지 않았다"


def test_seed_skips_unknown_tables(tmp_path, initialized_db):
    """docs/ 에 DB 에 없는 테이블명 xlsx 가 있어도 에러 없이 스킵한다."""
    fake_docs = tmp_path / "fake_docs"
    fake_docs.mkdir()
    # 진짜 xlsx 를 흉내내는 가짜 파일 — 여기선 테이블이 DB 에 없으니 파일 내용은 안 읽힘
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["col"])
    ws.append([1])
    wb.save(fake_docs / "nonexistent_table.xlsx")

    counts = seed_from_xlsx(initialized_db, fake_docs)
    assert counts == {}

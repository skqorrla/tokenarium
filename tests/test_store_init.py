"""DataStore.init_db 스키마 생성 테스트.

검증:
  1. 12개 테이블이 모두 생성된다
  2. 각 테이블이 기대한 컬럼을 갖는다 (대표 컬럼만 표본 검증)
  3. 멱등 — init_db 두 번 호출해도 에러 없고 테이블 수 동일
  4. info(project_id, created_at) 인덱스가 존재한다
"""

import sqlite3

import pytest

from store import DataStore


EXPECTED_TABLES = {
    "aquarium",
    "agent",
    "project",
    "info",
    "fish_species",
    "aquarium_stage",
    "fish",
    "fish_state",
    "currency",
    "currency_log",
    "feed_log",
    "revive_log",
    "interaction_log",
    "dialogue",
}


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def _table_names(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def _columns_of(db_path: str, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    finally:
        conn.close()
    return {r[1] for r in rows}


def test_init_db_creates_all_tables(db_path):
    DataStore(db_path).init_db()
    assert _table_names(db_path) == EXPECTED_TABLES


def test_info_table_has_expected_columns(db_path):
    DataStore(db_path).init_db()
    cols = _columns_of(db_path, "info")
    expected = {
        "id", "agent_id", "project_id",
        "total_token", "line_diff", "created_at",
    }
    assert cols == expected


def test_fish_state_has_fullness_and_fainted_columns(db_path):
    DataStore(db_path).init_db()
    cols = _columns_of(db_path, "fish_state")
    assert {"fullness", "is_fainted", "fainted_at", "last_updated"} <= cols


def test_init_db_is_idempotent(db_path):
    store = DataStore(db_path)
    store.init_db()
    first = _table_names(db_path)
    store.init_db()
    second = _table_names(db_path)
    assert first == second == EXPECTED_TABLES


def test_info_project_index_exists(db_path):
    DataStore(db_path).init_db()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='info'"
        ).fetchall()
    finally:
        conn.close()
    assert any(r[0] == "idx_info_project_created" for r in rows)

"""DataStore - SQLite 영속화 계층.

현재 단계: 스키마 생성(`init_db`)만 구현. 실제 CRUD(`record_turn` 등)는 후속 단계.

기존 `save_feed`/`get_fish_states`/`update_fish_state`는 `main.py`의
`_StubStore` 자동 감지 로직과 호환되도록 NotImplementedError 스텁 유지.
"""

import sqlite3

# 12개 테이블의 idempotent DDL. CREATE TABLE IF NOT EXISTS 로 재실행 안전.
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS aquarium (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name  TEXT NOT NULL,
    model_name  TEXT NOT NULL,
    UNIQUE(agent_name, model_name)
);

CREATE TABLE IF NOT EXISTS project (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    aquarium_id  INTEGER NOT NULL REFERENCES aquarium(id),
    dir          TEXT    NOT NULL,
    session      TEXT    NOT NULL,
    UNIQUE(aquarium_id, dir, session)
);

CREATE TABLE IF NOT EXISTS info (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id      INTEGER NOT NULL REFERENCES agent(id),
    project_id    INTEGER NOT NULL REFERENCES project(id),
    total_token   INTEGER NOT NULL DEFAULT 0,
    line_diff     INTEGER NOT NULL DEFAULT 0,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_info_project_created ON info(project_id, created_at);

CREATE TABLE IF NOT EXISTS fish_species (
    level_min     INTEGER PRIMARY KEY,
    emoji         TEXT    NOT NULL,
    name_kr       TEXT    NOT NULL,
    xp_required   INTEGER NOT NULL,
    is_legendary  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS aquarium_stage (
    stage        INTEGER PRIMARY KEY,
    level_min    INTEGER NOT NULL,
    description  TEXT,
    decorations  TEXT
);

CREATE TABLE IF NOT EXISTS fish (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL UNIQUE REFERENCES project(id),
    name            TEXT    NOT NULL,
    level           INTEGER NOT NULL DEFAULT 1,
    xp              INTEGER NOT NULL DEFAULT 0,
    species         TEXT    NOT NULL,
    aquarium_stage  INTEGER NOT NULL DEFAULT 1 REFERENCES aquarium_stage(stage),
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fish_state (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fish_id       INTEGER NOT NULL UNIQUE REFERENCES fish(id),
    fullness      INTEGER NOT NULL DEFAULT 100,
    is_fainted    INTEGER NOT NULL DEFAULT 0,
    fainted_at    DATETIME,
    last_updated  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS currency (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    aquarium_id   INTEGER NOT NULL UNIQUE REFERENCES aquarium(id),
    coins         INTEGER NOT NULL DEFAULT 0,
    total_earned  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS currency_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    aquarium_id  INTEGER NOT NULL REFERENCES aquarium(id),
    source_type  TEXT    NOT NULL,
    amount       INTEGER NOT NULL,
    info_id      INTEGER NOT NULL REFERENCES info(id),
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feed_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fish_id          INTEGER NOT NULL REFERENCES fish(id),
    fullness_before  INTEGER NOT NULL,
    fullness_after   INTEGER NOT NULL,
    xp_gained        INTEGER NOT NULL DEFAULT 0,
    coins_used       INTEGER NOT NULL DEFAULT 0,
    fed_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS revive_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fish_id      INTEGER NOT NULL REFERENCES fish(id),
    coins_spent  INTEGER NOT NULL,
    revived_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interaction_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fish_id      INTEGER NOT NULL REFERENCES fish(id),
    trigger      TEXT    NOT NULL,
    dialogue     TEXT    NOT NULL,
    fullness_at  INTEGER NOT NULL,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dialogue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    condition  TEXT NOT NULL,
    species    TEXT,
    text       TEXT NOT NULL
);
"""


class DataStore:
    def __init__(self, db_path: str = "aqua.db"):
        self.db_path = db_path

    def init_db(self) -> None:
        """전체 스키마 생성. 멱등 — 이미 존재하는 테이블은 건드리지 않음."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    # ── 후속 단계 미구현 스텁 (main.py StubStore 감지 호환용) ────────── #

    def save_feed(self, feed_data):
        raise NotImplementedError

    def get_fish_states(self) -> list:
        raise NotImplementedError

    def update_fish_state(self, dir: str, session: str, food_delta: float):
        raise NotImplementedError

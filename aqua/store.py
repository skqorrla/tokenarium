"""DataStore - SQLite 영속화 계층.

현재 단계: 스키마 생성(`init_db`)만 구현. 실제 CRUD(`record_turn` 등)는 후속 단계.

기존 `save_feed`/`get_fish_states`/`update_fish_state`는 `main.py`의
`_StubStore` 자동 감지 로직과 호환되도록 NotImplementedError 스텁 유지.
"""

import sqlite3

# 8개 테이블의 idempotent DDL. CREATE TABLE IF NOT EXISTS 로 재실행 안전.
# PK 외 모든 컬럼은 NULL 허용 (사용자 정책).
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name  TEXT,
    model_name  TEXT,
    UNIQUE(agent_name, model_name)
);

CREATE TABLE IF NOT EXISTS project (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    dir      TEXT,
    session  TEXT,
    UNIQUE(dir, session)
);

CREATE TABLE IF NOT EXISTS info (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id     INTEGER REFERENCES agent(id),
    project_id   INTEGER REFERENCES project(id),
    total_token  INTEGER,
    line_diff    INTEGER,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_info_project_created ON info(project_id, created_at);

CREATE TABLE IF NOT EXISTS fish_species (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    level_min     INTEGER,
    emoji         TEXT,
    name_kr       TEXT,
    xp_required   INTEGER,
    is_legendary  INTEGER
);

CREATE TABLE IF NOT EXISTS aquarium_stage (
    stage        INTEGER PRIMARY KEY,
    level_min    INTEGER,
    description  TEXT,
    decorations  TEXT
);

CREATE TABLE IF NOT EXISTS fish (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    species_id      INTEGER REFERENCES fish_species(id),
    project_id      INTEGER UNIQUE REFERENCES project(id),
    name            TEXT,
    level           INTEGER,
    xp              INTEGER,
    aquarium_stage  INTEGER REFERENCES aquarium_stage(stage),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fish_state (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fish_id       INTEGER UNIQUE REFERENCES fish(id),
    fullness      INTEGER,
    last_updated  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feed_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fish_id          INTEGER REFERENCES fish(id),
    fullness_before  INTEGER,
    fullness_after   INTEGER,
    tokens_used       INTEGER,
    fed_at           DATETIME DEFAULT CURRENT_TIMESTAMP
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

    def save_feed(self, feed) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO agent(agent_name, model_name) VALUES(?, ?)",
                (feed.agent_name, feed.model_name),
            )
            (agent_id,) = conn.execute(
                "SELECT id FROM agent WHERE agent_name=? AND model_name=?",
                (feed.agent_name, feed.model_name),
            ).fetchone()

            conn.execute(
                "INSERT OR IGNORE INTO project(dir, session) VALUES(?, ?)",
                (feed.dir, feed.session),
            )
            (project_id,) = conn.execute(
                "SELECT id FROM project WHERE dir=? AND session=?",
                (feed.dir, feed.session),
            ).fetchone()

            conn.execute(
                "INSERT INTO info(agent_id, project_id, total_token, line_diff)"
                " VALUES(?, ?, ?, ?)",
                (agent_id, project_id, feed.total_token, feed.line_diff),
            )
            conn.commit()
        finally:
            conn.close()

    def get_fish_states(self) -> list:
        raise NotImplementedError

    def update_fish_state(self, dir: str, session: str, food_delta: float):
        raise NotImplementedError

"""DataStore - SQLite 영속화 계층."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import config
from fish import (
    AQUARIUM_STAGES,
    FISH_SPECIES,
    get_aquarium_stage_for_level,
    get_species_for_xp,
)

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
    tokens_used      INTEGER,
    fed_at           DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

_FOOD_STOCK_SQL = """
    (SELECT COALESCE(SUM(i.total_token), 0) FROM info i WHERE i.project_id = p.id)
  - (SELECT COALESCE(SUM(fl.tokens_used), 0) FROM feed_log fl WHERE fl.fish_id = f.id)
"""

_FISH_SELECT_SQL = f"""
    SELECT f.id, f.name, f.level, f.xp, f.aquarium_stage, f.project_id,
           fs.emoji AS species, fs.name_kr,
           fst.fullness, fst.last_updated,
           p.dir,
           ({_FOOD_STOCK_SQL}) AS food_stock
    FROM fish f
    JOIN project p  ON f.project_id = p.id
    JOIN fish_species fs ON f.species_id = fs.id
    LEFT JOIN fish_state fst ON f.id = fst.fish_id
"""


class DataStore:
    def __init__(self, db_path: str = "aqua.db"):
        self.db_path = db_path

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    def seed_data(self) -> None:
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO fish_species"
                " (level_min, emoji, name_kr, xp_required, is_legendary) VALUES (?,?,?,?,?)",
                [
                    (s["level_min"], s["emoji"], s["name_kr"],
                     s["xp_required"], int(s["is_legendary"]))
                    for s in FISH_SPECIES
                ],
            )
            conn.executemany(
                "INSERT OR REPLACE INTO aquarium_stage"
                " (stage, level_min, description, decorations) VALUES (?,?,?,?)",
                [
                    (s["stage"], s["level_min"], s["description"], s["decorations"])
                    for s in AQUARIUM_STAGES
                ],
            )

    # ── 내부 헬퍼 ──────────────────────────────────────────────────────── #

    def _get_or_create_agent(self, conn, agent_name: str, model_name: str) -> int:
        conn.execute(
            "INSERT OR IGNORE INTO agent(agent_name, model_name) VALUES(?,?)",
            (agent_name, model_name),
        )
        return conn.execute(
            "SELECT id FROM agent WHERE agent_name=? AND model_name=?",
            (agent_name, model_name),
        ).fetchone()["id"]

    def _get_or_create_project(self, conn, dir_path: str, session: str = "") -> int:
        row = conn.execute(
            "SELECT id FROM project WHERE dir=?",
            (dir_path,),
        ).fetchone()
        if row:
            if session:
                conn.execute(
                    "UPDATE project SET session=? WHERE id=? AND (session IS NULL OR session='')",
                    (session, row["id"]),
                )
            return row["id"]

        conn.execute(
            "INSERT INTO project(dir, session) VALUES(?,?)",
            (dir_path, session),
        )
        return conn.execute(
            "SELECT id FROM project WHERE dir=?",
            (dir_path,),
        ).fetchone()["id"]

    def _apply_decay(self, fullness: int, last_updated) -> int:
        try:
            updated = datetime.fromisoformat(str(last_updated).replace(" ", "T"))
        except (ValueError, TypeError):
            return fullness
        elapsed_minutes = (datetime.utcnow() - updated).total_seconds() / 60
        if elapsed_minutes < 0:
            return fullness
        decay = int(elapsed_minutes / 30) * config.FULLNESS_DECAY_RATE
        return max(fullness - decay, config.FULLNESS_MIN)

    def _sync_fish_xp_level(self, conn, fish_id: int, project_id: int) -> None:
        row = conn.execute(
            "SELECT COALESCE(SUM(line_diff), 0) AS total FROM info WHERE project_id=?",
            (project_id,),
        ).fetchone()
        xp = int((row["total"] or 0) // config.LINES_PER_XP)

        sp    = get_species_for_xp(xp)
        level = sp["level_min"]
        stage = get_aquarium_stage_for_level(level)

        old = conn.execute("SELECT level FROM fish WHERE id=?", (fish_id,)).fetchone()
        old_level = old["level"] if old else 1

        sp_row = conn.execute(
            "SELECT id FROM fish_species WHERE xp_required=? AND emoji=?",
            (sp["xp_required"], sp["emoji"]),
        ).fetchone()
        species_id = sp_row["id"] if sp_row else 1

        conn.execute(
            "UPDATE fish SET xp=?, level=?, species_id=?, aquarium_stage=? WHERE id=?",
            (xp, level, species_id, stage, fish_id),
        )

        if level > old_level:
            st = conn.execute(
                "SELECT fullness, last_updated FROM fish_state WHERE fish_id=?",
                (fish_id,),
            ).fetchone()
            if st:
                cur = self._apply_decay(st["fullness"], st["last_updated"])
                new_fullness = min(cur + config.LEVELUP_FULLNESS_BONUS, 100)
                conn.execute(
                    "UPDATE fish_state SET fullness=?, last_updated=datetime('now')"
                    " WHERE fish_id=?",
                    (new_fullness, fish_id),
                )

    # ── 프로젝트 / 물고기 관리 ─────────────────────────────────────────── #

    def register_project(self, dir_path: str) -> int:
        with self._connect() as conn:
            return self._get_or_create_project(conn, dir_path)

    def project_has_fish(self, dir_path: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT f.id FROM fish f JOIN project p ON f.project_id=p.id WHERE p.dir=?",
                (dir_path,),
            ).fetchone()
            return row is not None

    def create_fish(self, project_id: int, name: str) -> dict:
        with self._connect() as conn:
            sp_row = conn.execute(
                "SELECT id FROM fish_species WHERE xp_required=0 LIMIT 1"
            ).fetchone()
            species_id = sp_row["id"] if sp_row else 1
            conn.execute(
                "INSERT INTO fish(species_id, project_id, name, level, xp, aquarium_stage)"
                " VALUES(?,?,?,1,0,1)",
                (species_id, project_id, name),
            )
            fish_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO fish_state(fish_id, fullness, last_updated)"
                " VALUES(?,50,datetime('now'))",
                (fish_id,),
            )
            return {"name": name, "id": fish_id}

    # ── 조회 ───────────────────────────────────────────────────────────── #

    def get_fish_by_dir(self, dir_path: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                _FISH_SELECT_SQL + " WHERE p.dir=?", (dir_path,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["fullness"]   = self._apply_decay(d["fullness"] or 50, d.get("last_updated"))
            d["food_stock"] = max(d["food_stock"] or 0, 0)
            return d

    def get_all_fish_with_state(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(_FISH_SELECT_SQL + " ORDER BY f.id").fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["fullness"]   = self._apply_decay(d["fullness"] or 50, d.get("last_updated"))
                d["food_stock"] = max(d["food_stock"] or 0, 0)
                result.append(d)
            return result

    def get_today_activity(self, project_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT a.agent_name, a.model_name,
                       SUM(i.total_token) AS tokens,
                       SUM(i.line_diff)   AS diff,
                       SUM(i.line_diff) / ? AS xp
                FROM info i
                JOIN agent a ON i.agent_id = a.id
                WHERE i.project_id = ?
                  AND DATE(i.created_at) = DATE('now')
                GROUP BY a.id
                ORDER BY tokens DESC
                """,
                (config.LINES_PER_XP, project_id),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── 먹이주기 ───────────────────────────────────────────────────────── #

    def feed_fish(self, fish_id: int, project_id: int) -> dict:
        with self._connect() as conn:
            stock_row = conn.execute(
                f"SELECT ({_FOOD_STOCK_SQL}) AS food_stock"
                " FROM fish f JOIN project p ON f.project_id=p.id"
                " WHERE f.id=?",
                (fish_id,),
            ).fetchone()
            food_stock = max(stock_row["food_stock"] or 0, 0)

            if food_stock < config.FOOD_COST_PER_FEED:
                return {
                    "success": False,
                    "message": (
                        f"먹이 부족! 재고 {food_stock:,}tok"
                        f" (필요 {config.FOOD_COST_PER_FEED:,}tok)"
                    ),
                }

            st = conn.execute(
                "SELECT fullness, last_updated FROM fish_state WHERE fish_id=?",
                (fish_id,),
            ).fetchone()
            fullness_before = self._apply_decay(
                st["fullness"] if st else 50,
                st["last_updated"] if st else None,
            )
            fullness_after = min(fullness_before + config.FULLNESS_PER_FEED, 100)

            conn.execute(
                "UPDATE fish_state SET fullness=?, last_updated=datetime('now')"
                " WHERE fish_id=?",
                (fullness_after, fish_id),
            )
            conn.execute(
                "INSERT INTO feed_log(fish_id, fullness_before, fullness_after, tokens_used)"
                " VALUES(?,?,?,?)",
                (fish_id, fullness_before, fullness_after, config.FOOD_COST_PER_FEED),
            )
            return {
                "success":        True,
                "stock_before":   food_stock,
                "stock_after":    food_stock - config.FOOD_COST_PER_FEED,
                "fullness_before": fullness_before,
                "fullness_after":  fullness_after,
            }

    # ── Orchestrator 호환 인터페이스 ───────────────────────────────────── #

    def save_feed(self, feed) -> None:
        with self._connect() as conn:
            agent_id   = self._get_or_create_agent(conn, feed.agent_name, feed.model_name)
            project_id = self._get_or_create_project(
                conn, feed.dir, getattr(feed, "session", "")
            )
            conn.execute(
                "INSERT INTO info(agent_id, project_id, total_token, line_diff)"
                " VALUES(?,?,?,?)",
                (agent_id, project_id, feed.total_token, feed.line_diff),
            )
            fish_row = conn.execute(
                "SELECT id FROM fish WHERE project_id=?", (project_id,)
            ).fetchone()
            if not fish_row:
                sp_row = conn.execute(
                    "SELECT id FROM fish_species WHERE xp_required=0 LIMIT 1"
                ).fetchone()
                species_id = sp_row["id"] if sp_row else 1
                fish_name = Path(feed.dir).name or "new fish"
                conn.execute(
                    "INSERT INTO fish(species_id, project_id, name, level, xp, aquarium_stage)"
                    " VALUES(?,?,?,1,0,1)",
                    (species_id, project_id, fish_name),
                )
                fish_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute(
                    "INSERT INTO fish_state(fish_id, fullness, last_updated)"
                    " VALUES(?,50,datetime('now'))",
                    (fish_id,),
                )
            else:
                fish_id = fish_row["id"]

            self._sync_fish_xp_level(conn, fish_id, project_id)

    def get_fish_states(self) -> list:
        return self.get_all_fish_with_state()

    def update_fish_state(self, dir_path: str, food_delta: float = 0.0) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT f.id, f.project_id FROM fish f"
                " JOIN project p ON f.project_id=p.id WHERE p.dir=?",
                (dir_path,),
            ).fetchone()
            if row:
                self._sync_fish_xp_level(conn, row["id"], row["project_id"])

    # ── 삭제 ───────────────────────────────────────────────────────────── #

    def delete_fish(self, dir_path: str) -> bool:
        """project.dir 기준으로 물고기 및 관련 데이터를 모두 삭제. 존재하면 True 반환."""
        with self._connect() as conn:
            proj = conn.execute(
                "SELECT id FROM project WHERE dir=?", (dir_path,)
            ).fetchone()
            if not proj:
                return False
            project_id = proj["id"]

            fish = conn.execute(
                "SELECT id FROM fish WHERE project_id=?", (project_id,)
            ).fetchone()
            if fish:
                fish_id = fish["id"]
                conn.execute("DELETE FROM feed_log   WHERE fish_id=?",  (fish_id,))
                conn.execute("DELETE FROM fish_state WHERE fish_id=?",  (fish_id,))
                conn.execute("DELETE FROM fish       WHERE id=?",       (fish_id,))

            conn.execute("DELETE FROM info    WHERE project_id=?", (project_id,))
            conn.execute("DELETE FROM project WHERE id=?",         (project_id,))
            return True

    # ── 테스트 / 데모 헬퍼 ─────────────────────────────────────────────── #

    def add_test_tokens(
        self, dir_: str, agent_name: str, model_name: str,
        total_token: int, line_diff: int = 0,
    ) -> None:
        with self._connect() as conn:
            agent_id   = self._get_or_create_agent(conn, agent_name, model_name)
            project_id = self._get_or_create_project(conn, dir_, "")
            conn.execute(
                "INSERT INTO info(agent_id, project_id, total_token, line_diff)"
                " VALUES(?,?,?,?)",
                (agent_id, project_id, total_token, line_diff),
            )
            fish_row = conn.execute(
                "SELECT id FROM fish WHERE project_id=?", (project_id,)
            ).fetchone()
            if fish_row:
                self._sync_fish_xp_level(conn, fish_row["id"], project_id)

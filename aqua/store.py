"""DataStore - SQLite 영속화 계층 (전체 구현)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime

import config
import fish as fish_module

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
    level_min     INTEGER UNIQUE,
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
    project_id      INTEGER UNIQUE REFERENCES project(id),
    name            TEXT,
    level           INTEGER DEFAULT 1,
    xp              INTEGER DEFAULT 0,
    species         TEXT    DEFAULT '🐟',
    aquarium_stage  INTEGER DEFAULT 1 REFERENCES aquarium_stage(stage),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fish_state (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fish_id       INTEGER UNIQUE REFERENCES fish(id),
    fullness      INTEGER DEFAULT 50,
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


class DataStore:
    def __init__(self, db_path: str = "aqua.db"):
        self.db_path = db_path

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
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
        """전체 스키마 생성. 멱등."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    def seed_data(self) -> None:
        """agent / fish_species / aquarium_stage 시드 데이터 삽입 (최초 1회)."""
        with self._connect() as conn:
            agents = [
                (1, "claude", "claude-sonnet-4-6"),
                (2, "claude", "claude-opus-4-7"),
                (3, "gemini", "gemini-2.5-flash"),
                (4, "gemini", "gemini-2.5-pro"),
                (5, "codex",  "gpt-5.3"),
                (6, "codex",  "gpt-5.4"),
            ]
            conn.executemany(
                "INSERT OR IGNORE INTO agent (id, agent_name, model_name) VALUES (?,?,?)",
                agents,
            )

            species_data = [
                (sp["level_min"], sp["emoji"], sp["name_kr"],
                 sp["xp_required"], 1 if sp["is_legendary"] else 0)
                for sp in fish_module.FISH_SPECIES
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO fish_species "
                "(level_min, emoji, name_kr, xp_required, is_legendary) VALUES (?,?,?,?,?)",
                species_data,
            )

            stage_data = [
                (s["stage"], s["level_min"], s["description"], s["decorations"])
                for s in fish_module.AQUARIUM_STAGES
            ]
            conn.executemany(
                "INSERT OR IGNORE INTO aquarium_stage "
                "(stage, level_min, description, decorations) VALUES (?,?,?,?)",
                stage_data,
            )

    # ── 내부 헬퍼 ──────────────────────────────────────────────────── #

    def _get_or_create_agent(self, conn, agent_name: str, model_name: str) -> int:
        row = conn.execute(
            "SELECT id FROM agent WHERE agent_name=? AND model_name=?",
            (agent_name, model_name),
        ).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT OR IGNORE INTO agent (agent_name, model_name) VALUES (?,?)",
            (agent_name, model_name),
        )
        if cur.lastrowid:
            return cur.lastrowid
        return conn.execute(
            "SELECT id FROM agent WHERE agent_name=? AND model_name=?",
            (agent_name, model_name),
        ).fetchone()["id"]

    def _get_or_create_project(self, conn, dir_: str, session: str) -> int:
        row = conn.execute(
            "SELECT id FROM project WHERE dir=? AND session=?",
            (dir_, session),
        ).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT OR IGNORE INTO project (dir, session) VALUES (?,?)",
            (dir_, session),
        )
        if cur.lastrowid:
            return cur.lastrowid
        return conn.execute(
            "SELECT id FROM project WHERE dir=? AND session=?",
            (dir_, session),
        ).fetchone()["id"]

    def _apply_decay(self, fullness: int, last_updated: str) -> int:
        """last_updated 이후 경과 시간 기반 포만감 감소 계산.
        SQLite datetime('now')는 UTC → datetime.utcnow()로 비교."""
        try:
            updated = datetime.fromisoformat(str(last_updated).replace(" ", "T"))
        except (ValueError, TypeError):
            return fullness
        elapsed_minutes = (datetime.utcnow() - updated).total_seconds() / 60
        if elapsed_minutes < 0:
            return fullness
        decay = int(elapsed_minutes / 30) * config.FULLNESS_DECAY_RATE
        return max(fullness - decay, config.FULLNESS_MIN)

    def _sync_fish_xp_level(self, conn, fish_id: int, project_id: int) -> bool:
        """info 테이블 기반 XP 재계산 → 레벨업 여부 반환."""
        row = conn.execute(
            "SELECT COALESCE(SUM(ABS(line_diff)), 0) / ? AS xp_total "
            "FROM info WHERE project_id=?",
            (config.LINES_PER_XP, project_id),
        ).fetchone()
        xp = row[0] if row else 0

        current = conn.execute(
            "SELECT level, xp FROM fish WHERE id=?", (fish_id,)
        ).fetchone()
        old_level = current["level"] if current else 1

        species = fish_module.get_species_for_xp(xp)
        new_level = species["level_min"]
        new_stage = fish_module.get_aquarium_stage_for_level(new_level)

        conn.execute(
            "UPDATE fish SET xp=?, level=?, species=?, aquarium_stage=? WHERE id=?",
            (xp, new_level, species["emoji"], new_stage, fish_id),
        )

        leveled_up = new_level > old_level
        if leveled_up:
            state = conn.execute(
                "SELECT fullness, last_updated FROM fish_state WHERE fish_id=?",
                (fish_id,),
            ).fetchone()
            if state:
                current_fullness = self._apply_decay(
                    state["fullness"], state["last_updated"]
                )
                new_fullness = min(current_fullness + config.LEVELUP_FULLNESS_BONUS, 100)
                conn.execute(
                    "UPDATE fish_state SET fullness=?, last_updated=datetime('now') "
                    "WHERE fish_id=?",
                    (new_fullness, fish_id),
                )
        return leveled_up

    # ── Orchestrator 호환 메서드 ──────────────────────────────────── #

    def save_feed(self, feed_data) -> None:
        """Orchestrator 콜백. info 삽입 + 물고기 XP 갱신."""
        with self._connect() as conn:
            agent_id = self._get_or_create_agent(
                conn, feed_data.agent_name, feed_data.model_name
            )
            project_id = self._get_or_create_project(
                conn, feed_data.dir, feed_data.session
            )
            conn.execute(
                "INSERT INTO info (agent_id, project_id, total_token, line_diff) "
                "VALUES (?,?,?,?)",
                (agent_id, project_id, feed_data.total_token, feed_data.line_diff),
            )
            fish_row = conn.execute(
                "SELECT id FROM fish WHERE project_id=?", (project_id,)
            ).fetchone()
            if fish_row:
                self._sync_fish_xp_level(conn, fish_row["id"], project_id)

    def get_fish_states(self) -> list:
        """Orchestrator 호환. 모든 물고기 상태 반환."""
        return self.get_all_fish_with_state()

    def update_fish_state(self, dir_: str, session: str, food_delta: float) -> None:
        """Orchestrator 레거시 메서드 (save_feed 에서 처리됨)."""
        pass

    # ── CLI 메서드 ──────────────────────────────────────────────────── #

    def register_project(self, dir_: str) -> int:
        """프로젝트 등록. project.id 반환."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO project (dir, session) VALUES (?,?)",
                (dir_, ""),
            )
            return conn.execute(
                "SELECT id FROM project WHERE dir=? AND session=''", (dir_,)
            ).fetchone()["id"]

    def create_fish(self, project_id: int, name: str) -> dict:
        """물고기 + fish_state 생성."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO fish (project_id, name, level, xp, species, aquarium_stage) "
                "VALUES (?,?,?,?,?,?)",
                (project_id, name, 1, 0, "🐟", 1),
            )
            fish_id = cur.lastrowid
            conn.execute(
                "INSERT INTO fish_state (fish_id, fullness) VALUES (?,?)",
                (fish_id, 50),
            )
            return {"id": fish_id, "name": name, "level": 1, "species": "🐟"}

    def project_has_fish(self, dir_: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT f.id FROM fish f "
                "JOIN project p ON p.id = f.project_id "
                "WHERE p.dir=? AND p.session=''",
                (dir_,),
            ).fetchone()
            return row is not None

    def get_fish_by_dir(self, dir_: str) -> dict | None:
        """dir 기반 물고기 + 상태 조회."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    f.id, f.name, f.level, f.xp, f.species, f.aquarium_stage,
                    fs.fullness, fs.last_updated,
                    p.id AS project_id, p.dir,
                    (SELECT COALESCE(SUM(i.total_token), 0)
                     FROM info i WHERE i.project_id = p.id)
                    - (SELECT COALESCE(SUM(fl.tokens_used), 0)
                       FROM feed_log fl WHERE fl.fish_id = f.id)
                    AS food_stock
                FROM fish f
                JOIN project p ON p.id = f.project_id
                JOIN fish_state fs ON fs.fish_id = f.id
                WHERE p.dir = ? AND p.session = ''
                """,
                (dir_,),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["fullness"] = self._apply_decay(d["fullness"], d["last_updated"])
            d["name_kr"] = fish_module.get_name_kr_for_level(d["level"])
            d["food_stock"] = max(d["food_stock"], 0)
            return d

    def get_all_fish_with_state(self) -> list[dict]:
        """모든 물고기 + 상태 목록."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    f.id, f.name, f.level, f.xp, f.species, f.aquarium_stage,
                    fs.fullness, fs.last_updated,
                    p.id AS project_id, p.dir,
                    (SELECT COALESCE(SUM(i.total_token), 0)
                     FROM info i WHERE i.project_id = p.id)
                    - (SELECT COALESCE(SUM(fl.tokens_used), 0)
                       FROM feed_log fl WHERE fl.fish_id = f.id)
                    AS food_stock
                FROM fish f
                JOIN project p ON p.id = f.project_id
                JOIN fish_state fs ON fs.fish_id = f.id
                ORDER BY f.created_at
                """
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["fullness"] = self._apply_decay(d["fullness"], d["last_updated"])
                d["name_kr"] = fish_module.get_name_kr_for_level(d["level"])
                d["food_stock"] = max(d["food_stock"], 0)
                result.append(d)
            return result

    def get_food_stock(self, project_id: int, fish_id: int) -> int:
        """먹이 재고 계산."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  (SELECT COALESCE(SUM(total_token), 0) FROM info WHERE project_id = ?)
                  - (SELECT COALESCE(SUM(tokens_used), 0) FROM feed_log WHERE fish_id = ?)
                  AS food_stock
                """,
                (project_id, fish_id),
            ).fetchone()
            return max(row[0] if row else 0, 0)

    def feed_fish(self, fish_id: int, project_id: int) -> dict:
        """먹이 주기. 결과 dict 반환."""
        with self._connect() as conn:
            stock_row = conn.execute(
                """
                SELECT
                  (SELECT COALESCE(SUM(total_token), 0) FROM info WHERE project_id = ?)
                  - (SELECT COALESCE(SUM(tokens_used), 0) FROM feed_log WHERE fish_id = ?)
                  AS food_stock
                """,
                (project_id, fish_id),
            ).fetchone()
            stock = max(stock_row[0] if stock_row else 0, 0)

            if stock < config.FOOD_COST_PER_FEED:
                return {
                    "success": False,
                    "message": (
                        f"⚠ 먹이 부족 "
                        f"(보유 {stock:,} / 필요 {config.FOOD_COST_PER_FEED:,} 토큰)"
                    ),
                    "stock": stock,
                }

            state = conn.execute(
                "SELECT fullness, last_updated FROM fish_state WHERE fish_id=?",
                (fish_id,),
            ).fetchone()
            before = self._apply_decay(state["fullness"], state["last_updated"])
            after = min(before + config.FULLNESS_PER_FEED, 100)

            conn.execute(
                "INSERT INTO feed_log (fish_id, fullness_before, fullness_after, tokens_used) "
                "VALUES (?,?,?,?)",
                (fish_id, before, after, config.FOOD_COST_PER_FEED),
            )
            conn.execute(
                "UPDATE fish_state SET fullness=?, last_updated=datetime('now') "
                "WHERE fish_id=?",
                (after, fish_id),
            )
            return {
                "success": True,
                "stock_before": stock,
                "stock_after": stock - config.FOOD_COST_PER_FEED,
                "fullness_before": before,
                "fullness_after": after,
            }

    def get_today_activity(self, project_id: int) -> list[dict]:
        """오늘 에이전트별 활동 집계."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    a.agent_name,
                    a.model_name,
                    SUM(i.total_token)           AS tokens,
                    SUM(ABS(i.line_diff))        AS diff,
                    SUM(ABS(i.line_diff)) / ?    AS xp
                FROM info i
                JOIN agent a ON a.id = i.agent_id
                WHERE i.project_id = ?
                  AND DATE(i.created_at) = DATE('now', 'localtime')
                GROUP BY i.agent_id
                ORDER BY tokens DESC
                """,
                (config.LINES_PER_XP, project_id),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_test_tokens(self, dir_: str, agent_name: str, model_name: str,
                        total_token: int, line_diff: int = 0) -> None:
        """테스트/데모용 토큰 추가."""
        with self._connect() as conn:
            agent_id = self._get_or_create_agent(conn, agent_name, model_name)
            project_id = self._get_or_create_project(conn, dir_, "")
            conn.execute(
                "INSERT INTO info (agent_id, project_id, total_token, line_diff) "
                "VALUES (?,?,?,?)",
                (agent_id, project_id, total_token, line_diff),
            )
            fish_row = conn.execute(
                "SELECT id FROM fish WHERE project_id=?", (project_id,)
            ).fetchone()
            if fish_row:
                self._sync_fish_xp_level(conn, fish_row["id"], project_id)

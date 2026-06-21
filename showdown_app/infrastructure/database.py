from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from showdown_app.paths import AppPaths


LOGGER = logging.getLogger(__name__)


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS tournaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    event_date TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    tournament_format TEXT NOT NULL DEFAULT '',
    competition_mode TEXT NOT NULL DEFAULT 'group_playoff',
    table_count INTEGER NOT NULL DEFAULT 1,
    seeding_mode TEXT NOT NULL DEFAULT 'snake',
    match_format INTEGER NOT NULL DEFAULT 3,
    rule_mode TEXT NOT NULL DEFAULT 'standard_ibsa',
    time_limit_enabled INTEGER NOT NULL DEFAULT 0,
    time_limit_minutes INTEGER NOT NULL DEFAULT 0,
    match_duration_minutes INTEGER NOT NULL DEFAULT 30,
    day_start_time TEXT NOT NULL DEFAULT '09:00',
    lunch_break_enabled INTEGER NOT NULL DEFAULT 0,
    lunch_start_time TEXT NOT NULL DEFAULT '',
    lunch_end_time TEXT NOT NULL DEFAULT '',
    reports_path TEXT NOT NULL DEFAULT 'reports',
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    rating INTEGER,
    organization TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    gender TEXT NOT NULL DEFAULT '',
    birth_date TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY(tournament_id) REFERENCES tournaments(id)
);
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL,
    player_a_id INTEGER NOT NULL,
    player_b_id INTEGER NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    table_no TEXT NOT NULL DEFAULT '',
    referee TEXT NOT NULL DEFAULT '',
    secretary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'not_started',
    match_format INTEGER NOT NULL DEFAULT 3,
    rule_mode TEXT NOT NULL DEFAULT 'standard_ibsa',
    time_limit_enabled INTEGER NOT NULL DEFAULT 0,
    time_limit_minutes INTEGER NOT NULL DEFAULT 0,
    winner_role TEXT NOT NULL DEFAULT '',
    finish_reason TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    ended_at TEXT NOT NULL DEFAULT '',
    current_state_json TEXT NOT NULL DEFAULT '',
    event_cursor INTEGER NOT NULL DEFAULT 0,
    round_no INTEGER NOT NULL DEFAULT 1,
    display_order INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(tournament_id) REFERENCES tournaments(id)
);
CREATE TABLE IF NOT EXISTS match_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    seq_no INTEGER NOT NULL,
    set_no INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_subtype TEXT NOT NULL DEFAULT '',
    actor_role TEXT NOT NULL DEFAULT '',
    beneficiary_role TEXT NOT NULL DEFAULT '',
    points_awarded INTEGER NOT NULL DEFAULT 0,
    score_a_after INTEGER NOT NULL DEFAULT 0,
    score_b_after INTEGER NOT NULL DEFAULT 0,
    server_after TEXT NOT NULL DEFAULT '',
    serve_no_after INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    is_official_event INTEGER NOT NULL DEFAULT 1,
    state_before_json TEXT NOT NULL DEFAULT '',
    state_after_json TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(match_id) REFERENCES matches(id)
);
CREATE INDEX IF NOT EXISTS idx_players_tournament_id ON players(tournament_id);
CREATE INDEX IF NOT EXISTS idx_matches_tournament_archived_round ON matches(tournament_id, archived, round_no, display_order, id);
CREATE INDEX IF NOT EXISTS idx_match_events_match_seq ON match_events(match_id, seq_no);
"""


def configure_logging(paths: AppPaths) -> None:
    logging.basicConfig(
        filename=paths.error_log,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


class Database:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.path = paths.database_file
        self.initialize()

    def initialize(self) -> None:
        with sqlite3.connect(self.path, timeout=30.0) as conn:
            self._configure_connection(conn)
            conn.executescript(SCHEMA)
            self._migrate_schema(conn)
            conn.commit()

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        self._ensure_column(conn, "tournaments", "table_count", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column(conn, "tournaments", "competition_mode", "TEXT NOT NULL DEFAULT 'group_playoff'")
        self._ensure_column(conn, "tournaments", "seeding_mode", "TEXT NOT NULL DEFAULT 'snake'")
        self._ensure_column(conn, "tournaments", "match_duration_minutes", "INTEGER NOT NULL DEFAULT 30")
        self._ensure_column(conn, "tournaments", "day_start_time", "TEXT NOT NULL DEFAULT '09:00'")
        self._ensure_column(conn, "tournaments", "lunch_break_enabled", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(conn, "tournaments", "lunch_start_time", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "tournaments", "lunch_end_time", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "players", "rating", "INTEGER")
        self._ensure_column(conn, "matches", "round_no", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column(conn, "matches", "display_order", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(conn, "matches", "archived", "INTEGER NOT NULL DEFAULT 0")

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_sql: str,
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing = {row[1] for row in rows}
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        self._configure_connection(conn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            LOGGER.exception("Database transaction failed")
            raise
        finally:
            conn.close()

    def backup(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=30.0) as source:
            self._configure_connection(source)
            with sqlite3.connect(destination, timeout=30.0) as target:
                self._configure_connection(target)
                source.backup(target)
                target.commit()

    @staticmethod
    def dumps_json(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _configure_connection(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")

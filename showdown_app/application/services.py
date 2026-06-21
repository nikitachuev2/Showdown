from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import csv
import json
import math
from pathlib import Path
import random
from typing import Dict, Iterable, List, Optional

from showdown_app.domain.models import (
    MATCH_STATUS_COMPLETED,
    MATCH_STATUS_DEFAULTED,
    MATCH_STATUS_NOT_STARTED,
    ROLE_A,
    ROLE_B,
    Match,
    MatchCommand,
    MatchEventRecord,
    MatchState,
    Player,
    SetScore,
    Tournament,
    now_iso,
    other_role,
)
from showdown_app.domain.scoring import MatchValidationError, apply_command, create_initial_state
from showdown_app.infrastructure.database import Database
from showdown_app.paths import AppPaths
from showdown_app.settings import AppSettings


GROUP_STAGE_PREFIX = "Группа "
PLAYOFF_STAGE_1 = "Плей-офф 1"
PLAYOFF_STAGE_2 = "Плей-офф 2"
SEMIFINAL_STAGE = "Полуфинал"
FINAL_STAGE = "Финал"
THIRD_PLACE_STAGE = "Матч за 3 место"

TOURNAMENT_FORMATS = [
    ("individual", "Индивидуальный"),
    ("team", "Командный"),
]

COMPETITION_MODES = [
    ("group_playoff", "Группы + плей-офф"),
    ("round_robin", "Круговая система"),
    ("double_round_robin", "Двойная круговая"),
    ("single_elimination", "Олимпийская система"),
    ("swiss", "Швейцарская система"),
]

SEEDING_MODES = [
    ("snake", "Змейка по рейтингу"),
    ("straight", "По рейтингу по группам"),
    ("alphabetical", "Змейка по алфавиту"),
    ("random", "Случайная жеребьевка"),
]


def row_to_tournament(row) -> Tournament:
    return Tournament(
        id=row["id"],
        name=row["name"],
        event_date=row["event_date"],
        location=row["location"],
        tournament_format=row["tournament_format"],
        competition_mode=row["competition_mode"] or "group_playoff",
        table_count=row["table_count"] or 1,
        seeding_mode=row["seeding_mode"] or "snake",
        match_format=row["match_format"],
        rule_mode=row["rule_mode"],
        time_limit_enabled=bool(row["time_limit_enabled"]),
        time_limit_minutes=row["time_limit_minutes"],
        match_duration_minutes=row["match_duration_minutes"] or 30,
        day_start_time=row["day_start_time"] or "09:00",
        lunch_break_enabled=bool(row["lunch_break_enabled"]),
        lunch_start_time=row["lunch_start_time"] or "",
        lunch_end_time=row["lunch_end_time"] or "",
        reports_path=row["reports_path"],
        comment=row["comment"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def row_to_player(row) -> Player:
    return Player(
        id=row["id"],
        tournament_id=row["tournament_id"],
        full_name=row["full_name"],
        rating=row["rating"],
        organization=row["organization"],
        city=row["city"],
        gender=row["gender"],
        birth_date=row["birth_date"],
        comment=row["comment"],
        status=row["status"],
    )


def row_to_match(row) -> Match:
    return Match(
        id=row["id"],
        tournament_id=row["tournament_id"],
        player_a_id=row["player_a_id"],
        player_b_id=row["player_b_id"],
        stage=row["stage"],
        table_no=row["table_no"],
        referee=row["referee"],
        secretary=row["secretary"],
        status=row["status"],
        match_format=row["match_format"],
        rule_mode=row["rule_mode"],
        winner_role=row["winner_role"],
        finish_reason=row["finish_reason"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        current_state_json=row["current_state_json"],
        event_cursor=row["event_cursor"],
        round_no=row["round_no"] or 1,
        display_order=row["display_order"] or 0,
        archived=bool(row["archived"]),
    )


def player_sort_key(player: Player) -> tuple:
    return (
        0 if player.rating is not None else 1,
        -(player.rating or 0),
        player.full_name.casefold(),
    )


def select_group_count(total_players: int) -> int:
    if total_players <= 4:
        return 1
    lower_capacity = 4
    lower_groups = 1
    while total_players > lower_capacity:
        upper_capacity = lower_capacity * 2
        upper_groups = lower_groups * 2
        if total_players <= upper_capacity:
            midpoint = lower_capacity + ((upper_capacity - lower_capacity) // 2)
            return lower_groups if total_players < midpoint else upper_groups
        lower_capacity = upper_capacity
        lower_groups = upper_groups
    return lower_groups


def group_codes(count: int, start_code: str = "A") -> List[str]:
    start = ord(start_code)
    return [chr(start + index) for index in range(count)]


def needed_sets_to_win(match_format: int) -> int:
    return 1 if match_format == 1 else 2 if match_format == 3 else 3


@dataclass
class TournamentStanding:
    player_id: int
    player_name: str
    tournament_points: int = 0
    wins: int = 0
    losses: int = 0
    sets_won: int = 0
    sets_lost: int = 0
    points_won: int = 0
    points_lost: int = 0

    @property
    def points_diff(self) -> int:
        return self.points_won - self.points_lost


class TournamentService:
    def __init__(self, db: Database, paths: AppPaths, settings: AppSettings) -> None:
        self.db = db
        self.paths = paths
        self.settings = settings

    def create_tournament(self, tournament: Tournament) -> Tournament:
        tournament.updated_at = now_iso()
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tournaments (
                    name, event_date, location, tournament_format, competition_mode, table_count, match_format,
                    seeding_mode, rule_mode, time_limit_enabled, time_limit_minutes, match_duration_minutes,
                    day_start_time, lunch_break_enabled, lunch_start_time, lunch_end_time, reports_path,
                    comment, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tournament.name,
                    tournament.event_date,
                    tournament.location,
                    tournament.tournament_format,
                    tournament.competition_mode,
                    max(1, tournament.table_count),
                    tournament.match_format,
                    tournament.seeding_mode,
                    tournament.rule_mode,
                    int(tournament.time_limit_enabled),
                    tournament.time_limit_minutes,
                    tournament.match_duration_minutes,
                    tournament.day_start_time,
                    int(tournament.lunch_break_enabled),
                    tournament.lunch_start_time,
                    tournament.lunch_end_time,
                    tournament.reports_path,
                    tournament.comment,
                    tournament.created_at,
                    tournament.updated_at,
                ),
            )
            tournament.id = int(cursor.lastrowid)
        return tournament

    def update_tournament(self, tournament: Tournament) -> Tournament:
        tournament.updated_at = now_iso()
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE tournaments
                SET name=?, event_date=?, location=?, tournament_format=?, competition_mode=?, table_count=?, seeding_mode=?, match_format=?,
                    rule_mode=?, time_limit_enabled=?, time_limit_minutes=?, match_duration_minutes=?, day_start_time=?,
                    lunch_break_enabled=?, lunch_start_time=?, lunch_end_time=?, reports_path=?,
                    comment=?, updated_at=?
                WHERE id=?
                """,
                (
                    tournament.name,
                    tournament.event_date,
                    tournament.location,
                    tournament.tournament_format,
                    tournament.competition_mode,
                    max(1, tournament.table_count),
                    tournament.seeding_mode,
                    tournament.match_format,
                    tournament.rule_mode,
                    int(tournament.time_limit_enabled),
                    tournament.time_limit_minutes,
                    tournament.match_duration_minutes,
                    tournament.day_start_time,
                    int(tournament.lunch_break_enabled),
                    tournament.lunch_start_time,
                    tournament.lunch_end_time,
                    tournament.reports_path,
                    tournament.comment,
                    tournament.updated_at,
                    tournament.id,
                ),
            )
        return tournament

    def list_tournaments(self) -> List[Tournament]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM tournaments ORDER BY event_date DESC, id DESC").fetchall()
        return [row_to_tournament(row) for row in rows]

    def get_tournament(self, tournament_id: int) -> Tournament:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,)).fetchone()
        if not row:
            raise ValueError("Турнир не найден")
        return row_to_tournament(row)
    def save_player(self, player: Player) -> Player:
        with self.db.connection() as conn:
            if player.id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO players (
                        tournament_id, full_name, rating, organization, city, gender,
                        birth_date, comment, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        player.tournament_id,
                        player.full_name,
                        player.rating,
                        player.organization,
                        player.city,
                        player.gender,
                        player.birth_date,
                        player.comment,
                        player.status,
                    ),
                )
                player.id = int(cursor.lastrowid)
            else:
                conn.execute(
                    """
                    UPDATE players SET
                        full_name=?, rating=?, organization=?, city=?, gender=?,
                        birth_date=?, comment=?, status=?
                    WHERE id=?
                    """,
                    (
                        player.full_name,
                        player.rating,
                        player.organization,
                        player.city,
                        player.gender,
                        player.birth_date,
                        player.comment,
                        player.status,
                        player.id,
                    ),
                )
        return player

    def list_players(self, tournament_id: int) -> List[Player]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM players WHERE tournament_id = ?", (tournament_id,)).fetchall()
        return sorted((row_to_player(row) for row in rows), key=player_sort_key)

    def delete_player(self, player_id: int) -> None:
        with self.db.connection() as conn:
            in_match = conn.execute(
                "SELECT COUNT(1) FROM matches WHERE player_a_id = ? OR player_b_id = ?",
                (player_id, player_id),
            ).fetchone()[0]
            if in_match:
                conn.execute("UPDATE players SET status = 'withdrawn' WHERE id = ?", (player_id,))
            else:
                conn.execute("DELETE FROM players WHERE id = ?", (player_id,))

    def import_players(self, tournament_id: int, source_file: Path) -> int:
        count = 0
        rows: Iterable[dict]
        text = source_file.read_text(encoding="utf-8-sig")
        if source_file.suffix.lower() == ".txt":
            rows = ({"full_name": line.strip()} for line in text.splitlines() if line.strip())
        else:
            rows = csv.DictReader(text.splitlines())
        for row in rows:
            full_name = (row.get("full_name") or row.get("ФИО") or row.get("ФИО") or "").strip()
            if not full_name:
                continue
            rating_raw = (row.get("rating") or row.get("рейтинг") or "").strip()
            self.save_player(
                Player(
                    id=None,
                    tournament_id=tournament_id,
                    full_name=full_name,
                    rating=int(rating_raw) if rating_raw else None,
                    organization=(row.get("organization") or row.get("страна/клуб") or row.get("страна/клуб") or ""),
                    city=(row.get("city") or row.get("город") or row.get("город") or ""),
                    gender=(row.get("gender") or row.get("пол") or row.get("пол") or ""),
                    birth_date=(row.get("birth_date") or row.get("дата рождения") or row.get("дата рождения") or ""),
                    comment=(row.get("comment") or row.get("комментарий") or row.get("комментарий") or ""),
                )
            )
            count += 1
        return count

    def generate_group_stage(self, tournament_id: int, overwrite_existing: bool = False) -> int:
        tournament = self.get_tournament(tournament_id)
        players = [player for player in self.list_players(tournament_id) if player.status == "active"]
        if len(players) < 2:
            raise ValueError("Для автоматического формирования турнира нужно минимум 2 активных участника.")
        with self.db.connection() as conn:
            existing = conn.execute("SELECT COUNT(1) FROM matches WHERE tournament_id = ?", (tournament_id,)).fetchone()[0]
            if existing and not overwrite_existing:
                raise ValueError("Матчи уже существуют. Для пересоздания удалите текущую сетку или подтвердите замену.")
            if existing:
                conn.execute("DELETE FROM match_events WHERE match_id IN (SELECT id FROM matches WHERE tournament_id = ?)", (tournament_id,))
                conn.execute("DELETE FROM matches WHERE tournament_id = ?", (tournament_id,))
            schedule = self._build_schedule_for_mode(tournament, players)
            for index, item in enumerate(schedule, start=1):
                self._insert_generated_match(
                    conn,
                    tournament,
                    item["player_a"].id or 0,
                    item["player_b"].id or 0,
                    item["stage"],
                    item["table_no"],
                    round_no=1,
                    display_order=index,
                )
        return len(schedule)

    def generate_next_stage(self, tournament_id: int) -> int:
        tournament = self.get_tournament(tournament_id)
        matches = self._list_matches_raw(tournament_id)
        if not matches:
            raise ValueError("\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0441\u0444\u043e\u0440\u043c\u0438\u0440\u0443\u0439\u0442\u0435 \u0433\u0440\u0443\u043f\u043f\u043e\u0432\u043e\u0439 \u044d\u0442\u0430\u043f.")
        unfinished_matches = [match for match in matches if match.status not in {MATCH_STATUS_COMPLETED, MATCH_STATUS_DEFAULTED}]
        if unfinished_matches:
            raise ValueError("\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u044d\u0442\u0430\u043f \u043c\u043e\u0436\u043d\u043e \u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u0442\u043e\u043b\u044c\u043a\u043e \u043f\u043e\u0441\u043b\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0438\u044f \u0432\u0441\u0435\u0445 \u0442\u0435\u043a\u0443\u0449\u0438\u0445 \u043c\u0430\u0442\u0447\u0435\u0439.")
        if tournament.competition_mode == "group_playoff":
            return self._generate_group_playoff_next_stage(tournament, matches)
        if tournament.competition_mode == "single_elimination":
            return self._generate_single_elimination_next_stage(tournament, matches)
        if tournament.competition_mode == "swiss":
            return self._generate_swiss_next_round(tournament, matches)
        raise ValueError("Для выбранного формата турнир полностью формируется сразу. Следующий этап не требуется.")

    def _build_schedule_for_mode(self, tournament: Tournament, players: List[Player]) -> List[dict]:
        if tournament.competition_mode == "group_playoff":
            if len(players) < 3:
                raise ValueError("Для формата группы + плей-офф нужно минимум 3 активных участника.")
            groups = self._seed_players_by_groups(players, tournament.seeding_mode, tournament.id or 0)
            return self._build_group_schedule(groups, max(1, tournament.table_count))
        if tournament.competition_mode == "round_robin":
            return self._build_round_robin_schedule(players, tournament, cycles=1, stage_name="Круговой этап")
        if tournament.competition_mode == "double_round_robin":
            return self._build_round_robin_schedule(players, tournament, cycles=2, stage_name="Двойной круговой этап")
        if tournament.competition_mode == "single_elimination":
            ordered_players = self._order_players_for_seeding(players, tournament.seeding_mode, tournament.id or 0)
            return self._build_single_elimination_round(ordered_players, tournament, round_no=1)
        if tournament.competition_mode == "swiss":
            if len(players) % 2 != 0:
                raise ValueError("Для швейцарской системы в текущей реализации нужно четное число активных участников.")
            ordered_players = self._order_players_for_seeding(players, tournament.seeding_mode, tournament.id or 0)
            return self._build_pairings_schedule(self._pair_top_bottom(ordered_players), tournament, stage="Швейцарка 1")
        raise ValueError("Неизвестный формат соревнования.")

    def _generate_group_playoff_next_stage(self, tournament: Tournament, matches: List[Match]) -> int:
        with self.db.connection() as conn:
            active_matches = [match for match in matches if not match.archived]
            active_semifinals = [match for match in active_matches if match.stage == SEMIFINAL_STAGE]
            if active_semifinals and not any(match.stage == FINAL_STAGE for match in matches):
                if any(not self._winner_player_id(match) for match in active_semifinals):
                    raise ValueError("Сначала завершите все полуфинальные матчи.")
                semifinal_matches = sorted(active_semifinals, key=lambda item: item.display_order or item.id or 0)
                winners = [self._winner_player_id(match) for match in semifinal_matches]
                losers = [match.player_b_id if self._winner_player_id(match) == match.player_a_id else match.player_a_id for match in semifinal_matches]
                self._archive_current_round(conn, tournament.id or 0)
                self._insert_generated_match(conn, tournament, winners[0], winners[1], FINAL_STAGE, "1", round_no=self._next_round_number(matches), display_order=1)
                self._insert_generated_match(conn, tournament, losers[0], losers[1], THIRD_PLACE_STAGE, "2" if tournament.table_count > 1 else "1", round_no=self._next_round_number(matches), display_order=2)
                return 2
            knockout_stages = {"Четвертьфинал", "1/8 финала", "Олимпийский раунд 1", "Олимпийский раунд 2", "Олимпийский раунд 3"}
            existing_knockout = [match for match in matches if match.stage in knockout_stages or match.stage == SEMIFINAL_STAGE]
            if existing_knockout and not any(match.stage == FINAL_STAGE for match in matches):
                current_round = max(match.round_no for match in existing_knockout if not match.archived)
                current_matches = sorted(
                    [match for match in matches if match.round_no == current_round and not match.archived],
                    key=lambda item: item.display_order or item.id or 0,
                )
                if any(not self._winner_player_id(match) for match in current_matches):
                    raise ValueError("Сначала завершите все матчи текущего этапа плей-офф.")
                winners = [self._winner_player_id(match) for match in current_matches]
                if len(winners) == 2:
                    losers = [match.player_b_id if self._winner_player_id(match) == match.player_a_id else match.player_a_id for match in current_matches]
                    self._archive_current_round(conn, tournament.id or 0)
                    next_round_no = self._next_round_number(matches)
                    self._insert_generated_match(conn, tournament, winners[0], winners[1], FINAL_STAGE, "1", round_no=next_round_no, display_order=1)
                    self._insert_generated_match(conn, tournament, losers[0], losers[1], THIRD_PLACE_STAGE, "2" if tournament.table_count > 1 else "1", round_no=next_round_no, display_order=2)
                    return 2
                next_players = [player for player in self.list_players(tournament.id or 0) if (player.id or 0) in winners]
                ordered_map = {player.id or 0: player for player in self._order_players_for_seeding(next_players, tournament.seeding_mode, tournament.id or 0)}
                ordered_winners = [ordered_map[player_id] for player_id in winners]
                schedule = self._build_pairings_schedule(
                    self._consecutive_pairs(ordered_winners),
                    tournament,
                    self._single_elimination_stage_name(len(ordered_winners), 1),
                )
                self._archive_current_round(conn, tournament.id or 0)
                next_round_no = self._next_round_number(matches)
                for index, item in enumerate(schedule, start=1):
                    self._insert_generated_match(conn, tournament, item["player_a"].id or 0, item["player_b"].id or 0, item["stage"], item["table_no"], round_no=next_round_no, display_order=index)
                return len(schedule)
            if not existing_knockout:
                group_matches = [match for match in matches if match.stage.startswith(GROUP_STAGE_PREFIX)]
                if not group_matches:
                    raise ValueError("\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0437\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u0435 \u043c\u0430\u0442\u0447\u0438 \u0433\u0440\u0443\u043f\u043f\u043e\u0432\u043e\u0433\u043e \u044d\u0442\u0430\u043f\u0430.")
                rankings = self._group_rankings(group_matches, tournament.id or 0)
                codes = sorted(rankings)
                if len(codes) < 2:
                    raise ValueError("\u0414\u043b\u044f \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0433\u043e \u044d\u0442\u0430\u043f\u0430 \u043d\u0443\u0436\u043d\u044b \u043c\u0438\u043d\u0438\u043c\u0443\u043c \u0434\u0432\u0435 \u0433\u0440\u0443\u043f\u043f\u044b.")
                if len(codes) % 2 != 0:
                    raise ValueError("\u0414\u043b\u044f \u043f\u043b\u0435\u0439-\u043e\u0444\u0444 \u043d\u0443\u0436\u043d\u043e \u0447\u0435\u0442\u043d\u043e\u0435 \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e \u0433\u0440\u0443\u043f\u043f.")
                qualifiers: List[Player] = []
                for code in codes:
                    qualifiers.append(rankings[code][0])
                for code in reversed(codes):
                    qualifiers.append(rankings[code][1])
                stage = self._single_elimination_stage_name(len(qualifiers), 1)
                pairings = self._consecutive_pairs(qualifiers)
                self._archive_current_round(conn, tournament.id or 0)
                next_round_no = self._next_round_number(matches)
                for index, pair in enumerate(pairings, start=1):
                    self._insert_generated_match(conn, tournament, pair[0].id or 0, pair[1].id or 0, stage, str(((index - 1) % tournament.table_count) + 1), round_no=next_round_no, display_order=index)
                return len(pairings)
        raise ValueError("\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u044d\u0442\u0430\u043f \u0434\u043b\u044f \u044d\u0442\u043e\u0433\u043e \u0442\u0443\u0440\u043d\u0438\u0440\u0430 \u0443\u0436\u0435 \u0441\u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u043d.")

    def _generate_single_elimination_next_stage(self, tournament: Tournament, matches: List[Match]) -> int:
        players = [player for player in self.list_players(tournament.id or 0) if player.status == "active"]
        ordered_players = self._order_players_for_seeding(players, tournament.seeding_mode, tournament.id or 0)
        bracket = self._single_elimination_bracket_setup(ordered_players)
        with self.db.connection() as conn:
            next_round_no = self._next_round_number(matches)
            active_matches = [match for match in matches if not match.archived]
            if any(match.stage == FINAL_STAGE for match in matches):
                raise ValueError("Олимпийская сетка уже завершена.")
            if any(match.stage == SEMIFINAL_STAGE for match in active_matches):
                winners = [self._winner_player_id(match) for match in sorted(active_matches, key=lambda item: item.display_order or item.id or 0) if match.stage == SEMIFINAL_STAGE]
                losers = [match.player_b_id if self._winner_player_id(match) == match.player_a_id else match.player_a_id for match in sorted(active_matches, key=lambda item: item.display_order or item.id or 0) if match.stage == SEMIFINAL_STAGE]
                self._archive_current_round(conn, tournament.id or 0)
                self._insert_generated_match(conn, tournament, winners[0], winners[1], FINAL_STAGE, "1", round_no=next_round_no, display_order=1)
                self._insert_generated_match(conn, tournament, losers[0], losers[1], THIRD_PLACE_STAGE, "2" if tournament.table_count > 1 else "1", round_no=next_round_no, display_order=2)
                return 2
            if any(match.stage == "Отборочный раунд" for match in active_matches):
                winners_by_slot = {}
                for slot_seed, match in zip(bracket.get("preliminary_seed_slots", []), sorted(active_matches, key=lambda item: item.display_order or item.id or 0)):
                    if match.stage != "Отборочный раунд":
                        continue
                    winner_id = self._winner_player_id(match)
                    winner_player = next(player for player in ordered_players if (player.id or 0) == winner_id)
                    winners_by_slot[slot_seed] = winner_player
                seed_order = self._standard_seed_order(bracket["main_draw_size"])
                direct_seeds = bracket["direct_seeds"]
                participant_slots = []
                for seed_slot in seed_order:
                    if seed_slot <= direct_seeds:
                        participant_slots.append(ordered_players[seed_slot - 1])
                    else:
                        participant_slots.append(winners_by_slot[seed_slot])
                participant_pairs = self._consecutive_pairs(participant_slots)
                stage = self._single_elimination_stage_name(len(participant_slots), 2)
                self._archive_current_round(conn, tournament.id or 0)
                for index, pair in enumerate(participant_pairs, start=1):
                    self._insert_generated_match(conn, tournament, pair[0].id or 0, pair[1].id or 0, stage, str(((index - 1) % tournament.table_count) + 1), round_no=next_round_no, display_order=index)
                return len(participant_pairs)
            current_round = max(match.round_no for match in active_matches)
            current_matches = sorted([match for match in active_matches if match.round_no == current_round and match.stage != THIRD_PLACE_STAGE], key=lambda item: item.display_order or item.id or 0)
            winners = [self._winner_player_id(match) for match in current_matches]
            if len(winners) < 2:
                raise ValueError("Олимпийская сетка уже завершена.")
            next_players = [next(player for player in ordered_players if (player.id or 0) == winner_id) for winner_id in winners]
            stage = self._single_elimination_stage_name(len(next_players), current_round + 1)
            schedule = self._build_pairings_schedule(self._consecutive_pairs(next_players), tournament, stage)
            self._archive_current_round(conn, tournament.id or 0)
            for index, item in enumerate(schedule, start=1):
                self._insert_generated_match(conn, tournament, item["player_a"].id or 0, item["player_b"].id or 0, item["stage"], item["table_no"], round_no=next_round_no, display_order=index)
            return len(schedule)

    def _generate_swiss_next_round(self, tournament: Tournament, matches: List[Match]) -> int:
        players = [player for player in self.list_players(tournament.id or 0) if player.status == "active"]
        max_rounds = self._swiss_round_limit(len(players))
        existing_rounds = sorted(
            {
                int(match.stage.replace("Швейцарка ", "").strip())
                for match in matches
                if match.stage.startswith("Швейцарка ")
            }
        )
        if not existing_rounds:
            raise ValueError("Сначала сформируйте первый раунд швейцарской системы.")
        next_round = existing_rounds[-1] + 1
        if next_round > max_rounds:
            raise ValueError("Достигнуто максимальное количество раундов для швейцарской системы.")
        pairings = self._build_swiss_pairings(players, matches, tournament)
        schedule = self._build_pairings_schedule(pairings, tournament, stage=f"Швейцарка {next_round}")
        with self.db.connection() as conn:
            for item in schedule:
                self._insert_generated_match(conn, tournament, item["player_a"].id or 0, item["player_b"].id or 0, item["stage"], item["table_no"])
        return len(schedule)

    def _list_matches_raw(self, tournament_id: int) -> List[Match]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM matches WHERE tournament_id = ? ORDER BY id", (tournament_id,)).fetchall()
        return [row_to_match(row) for row in rows]

    def _winner_player_id(self, match: Match) -> int:
        if match.winner_role == ROLE_A:
            return match.player_a_id
        if match.winner_role == ROLE_B:
            return match.player_b_id
        raise ValueError("\u0423 \u043c\u0430\u0442\u0447\u0430 \u043d\u0435 \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0435\u043d \u043f\u043e\u0431\u0435\u0434\u0438\u0442\u0435\u043b\u044c.")

    def _match_result_points(self, sets_won: int, sets_lost: int, won_match: bool) -> int:
        target = max(1, sets_won if won_match else sets_lost)
        if target == 1:
            return 4 if won_match else 1
        if won_match:
            return 4 if sets_lost == 0 else 3
        return 2 if sets_won == target - 1 else 1

    def _group_rankings(self, group_matches: List[Match], tournament_id: int) -> Dict[str, List[Player]]:
        standings_by_group = self._group_rankings_with_stats(group_matches, tournament_id)
        players = {player.id or 0: player for player in self.list_players(tournament_id)}
        return {
            code: [players[standing.player_id] for standing in standings if standing.player_id in players]
            for code, standings in standings_by_group.items()
        }

    def _group_rankings_with_stats(self, group_matches: List[Match], tournament_id: int) -> Dict[str, List[TournamentStanding]]:
        players = {player.id or 0: player for player in self.list_players(tournament_id)}
        grouped: Dict[str, List[Match]] = {}
        for match in group_matches:
            code = match.stage.replace(GROUP_STAGE_PREFIX, "").strip()
            grouped.setdefault(code, []).append(match)
        rankings: Dict[str, List[TournamentStanding]] = {}
        for code, matches_in_group in grouped.items():
            participant_ids = sorted({match.player_a_id for match in matches_in_group} | {match.player_b_id for match in matches_in_group})
            if len(participant_ids) < 2:
                raise ValueError(f"\u0412 \u0433\u0440\u0443\u043f\u043f\u0435 {code} \u043d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u0443\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u043e\u0432 \u0434\u043b\u044f \u043f\u043e\u0441\u0442\u0440\u043e\u0435\u043d\u0438\u044f \u0440\u0435\u0439\u0442\u0438\u043d\u0433\u0430.")
            stats = {
                player_id: TournamentStanding(
                    player_id=player_id,
                    player_name=players[player_id].full_name,
                )
                for player_id in participant_ids
            }
            for match in matches_in_group:
                if not match.current_state_json:
                    continue
                state = MatchState.from_dict(json.loads(match.current_state_json))
                if state.status not in {MATCH_STATUS_COMPLETED, MATCH_STATUS_DEFAULTED}:
                    continue
                standing_a = stats[match.player_a_id]
                standing_b = stats[match.player_b_id]
                if state.winner_role == ROLE_A:
                    standing_a.wins += 1
                    standing_b.losses += 1
                elif state.winner_role == ROLE_B:
                    standing_b.wins += 1
                    standing_a.losses += 1
                standing_a.tournament_points += self._match_result_points(state.sets_won_a, state.sets_won_b, state.winner_role == ROLE_A)
                standing_b.tournament_points += self._match_result_points(state.sets_won_b, state.sets_won_a, state.winner_role == ROLE_B)
                for set_score in state.sets:
                    if not set_score.winner_role:
                        continue
                    if set_score.winner_role == ROLE_A:
                        standing_a.sets_won += 1
                        standing_b.sets_lost += 1
                    else:
                        standing_b.sets_won += 1
                        standing_a.sets_lost += 1
                    standing_a.points_won += set_score.score_a
                    standing_a.points_lost += set_score.score_b
                    standing_b.points_won += set_score.score_b
                    standing_b.points_lost += set_score.score_a
            ordered_ids = sorted(
                participant_ids,
                key=lambda pid: (
                    -stats[pid].tournament_points,
                    -stats[pid].wins,
                    -((stats[pid].sets_won - stats[pid].sets_lost)),
                    players[pid].full_name.casefold(),
                ),
            )
            rankings[code] = [stats[player_id] for player_id in ordered_ids]
        return rankings

    def _seed_players_by_groups(
        self,
        players: List[Player],
        seeding_mode: str,
        tournament_id: int,
    ) -> Dict[str, List[Player]]:
        ordered_players = self._order_players_for_seeding(players, seeding_mode, tournament_id)
        if seeding_mode == "straight":
            return self._seed_players_straight_by_groups(ordered_players)
        return self._seed_players_snake_by_groups(ordered_players)

    def _seed_players_straight_by_groups(self, ordered_players: List[Player]) -> Dict[str, List[Player]]:
        group_count = select_group_count(len(ordered_players))
        codes = group_codes(group_count)
        groups = {code: [] for code in codes}
        remaining_players = len(ordered_players)
        player_index = 0
        for group_index, code in enumerate(codes):
            remaining_groups = group_count - group_index
            size = math.ceil(remaining_players / remaining_groups)
            groups[code] = ordered_players[player_index : player_index + size]
            player_index += size
            remaining_players -= size
        return self._rebalance_group_cities(groups)

    def _seed_players_snake_by_groups(self, ordered_players: List[Player]) -> Dict[str, List[Player]]:
        group_count = select_group_count(len(ordered_players))
        codes = group_codes(group_count)
        groups = {code: [] for code in codes}
        matrix: List[List[Optional[Player]]] = []
        player_index = 0
        while player_index < len(ordered_players):
            row = [None] * group_count
            row_index = len(matrix)
            columns = list(range(group_count))
            if row_index % 2 == 1:
                columns.reverse()
            for column in columns:
                if player_index >= len(ordered_players):
                    break
                row[column] = ordered_players[player_index]
                player_index += 1
            matrix.append(row)
        matrix = self._rebalance_group_city_matrix(matrix)
        for row in matrix:
            for group_index, player in enumerate(row):
                if player is not None:
                    groups[codes[group_index]].append(player)
        return groups

    def _rebalance_group_cities(self, groups: Dict[str, List[Player]]) -> Dict[str, List[Player]]:
        codes = list(groups)
        max_rows = max((len(players) for players in groups.values()), default=0)
        matrix = [
            [groups[code][row_index] if row_index < len(groups[code]) else None for code in codes]
            for row_index in range(max_rows)
        ]
        matrix = self._rebalance_group_city_matrix(matrix)
        rebalanced = {code: [] for code in codes}
        for row in matrix:
            for group_index, player in enumerate(row):
                if player is not None:
                    rebalanced[codes[group_index]].append(player)
        return rebalanced

    def _rebalance_group_city_matrix(self, matrix: List[List[Optional[Player]]]) -> List[List[Optional[Player]]]:
        if not matrix:
            return matrix
        group_count = len(matrix[0])
        changed = True
        max_passes = max(1, len(matrix) * max(1, group_count) * 4)
        passes = 0
        while changed and passes < max_passes:
            passes += 1
            changed = False
            for group_index in range(group_count):
                seen_cities: Dict[str, int] = {}
                for row_index, row in enumerate(matrix):
                    player = row[group_index]
                    city = (player.city or "").strip().casefold() if player else ""
                    if not city:
                        continue
                    if city in seen_cities:
                        target_indices = self._candidate_group_indices(group_index, group_count)
                        for target_group_index in target_indices:
                            if target_group_index < 0 or target_group_index >= group_count:
                                continue
                            target_player = matrix[row_index][target_group_index]
                            target_city = (target_player.city or "").strip().casefold() if target_player else ""
                            if target_player is None or target_city == city:
                                continue
                            matrix[row_index][group_index], matrix[row_index][target_group_index] = (
                                matrix[row_index][target_group_index],
                                matrix[row_index][group_index],
                            )
                            changed = True
                            break
                        if changed:
                            break
                    else:
                        seen_cities[city] = row_index
                if changed:
                    break
        return matrix

    def _candidate_group_indices(self, group_index: int, group_count: int) -> List[int]:
        if group_count <= 1:
            return []
        if group_index == 0:
            return [1]
        if group_index == group_count - 1:
            return [group_count - 2]
        return [group_index + 1, group_index - 1, group_index + 2, group_index - 2]

    def _order_players_for_seeding(
        self,
        players: List[Player],
        seeding_mode: str,
        tournament_id: int,
    ) -> List[Player]:
        if seeding_mode == "alphabetical":
            return sorted(players, key=lambda player: player.full_name.casefold())
        if seeding_mode == "random":
            shuffled = list(players)
            random.Random(tournament_id or len(players)).shuffle(shuffled)
            return shuffled
        return sorted(players, key=player_sort_key)

    def _build_round_robin_schedule(
        self,
        players: List[Player],
        tournament: Tournament,
        cycles: int,
        stage_name: str,
    ) -> List[dict]:
        ordered_players = self._order_players_for_seeding(players, tournament.seeding_mode, tournament.id or 0)
        rounds = self._round_robin_pairs_by_round(len(ordered_players))
        schedule: List[dict] = []
        for cycle in range(cycles):
            for round_index, pairs in enumerate(rounds, start=1):
                for pair_index, (left, right) in enumerate(pairs, start=1):
                    player_a = ordered_players[left - 1]
                    player_b = ordered_players[right - 1]
                    if cycle % 2 == 1:
                        player_a, player_b = player_b, player_a
                    table_no = str(((pair_index - 1) % max(1, tournament.table_count)) + 1)
                    schedule.append(
                        {
                            "stage": f"{stage_name}, тур {((cycle * len(rounds)) + round_index)}",
                            "table_no": table_no,
                            "player_a": player_a,
                            "player_b": player_b,
                        }
                    )
        return schedule

    def _build_single_elimination_round(
        self,
        participants: List[Player],
        tournament: Tournament,
        round_no: int,
    ) -> List[dict]:
        bracket = self._single_elimination_bracket_setup(participants)
        if bracket["preliminary_pairs"]:
            return self._build_pairings_schedule(
                bracket["preliminary_pairs"],
                tournament,
                "Отборочный раунд",
            )
        main_draw_players = [player for player in bracket["main_draw_slots"] if player is not None]
        stage = self._single_elimination_stage_name(len(main_draw_players), round_no)
        return self._build_pairings_schedule(
            self._consecutive_pairs(main_draw_players),
            tournament,
            stage,
        )

    def _build_pairings_schedule(
        self,
        pairings: List[object],
        tournament: Tournament,
        stage: str,
    ) -> List[dict]:
        schedule: List[dict] = []
        for index, pair in enumerate(pairings, start=1):
            player_a, player_b = pair
            table_no = str(((index - 1) % max(1, tournament.table_count)) + 1)
            schedule.append(
                {
                    "stage": stage,
                    "table_no": table_no,
                    "player_a": player_a,
                    "player_b": player_b,
                }
            )
        return schedule

    def _pair_top_bottom(self, participants: List[Player]) -> List[List[Player]]:
        active = list(participants)
        pairs: List[List[Player]] = []
        while len(active) > 1:
            pairs.append([active.pop(0), active.pop(-1)])
        return pairs

    def _single_elimination_participants(
        self,
        ordered_players: List[Player],
        matches: List[Match],
    ) -> tuple[List[Player], int]:
        del ordered_players, matches
        return [], 1

    def _single_elimination_stage_name(self, participant_count: int, round_no: int) -> str:
        if participant_count == 2:
            return FINAL_STAGE
        if participant_count == 4:
            return SEMIFINAL_STAGE
        if participant_count == 8:
            return "Четвертьфинал"
        if participant_count == 16:
            return "1/8 финала"
        return f"Олимпийский раунд {round_no}"

    def _single_elimination_bracket_setup(self, ordered_players: List[Player]) -> dict:
        total_players = len(ordered_players)
        if total_players < 2:
            raise ValueError("Для олимпийской системы нужно минимум два участника.")
        main_draw_size = 1 << (total_players.bit_length() - 1)
        if total_players == main_draw_size:
            seed_order = self._standard_seed_order(main_draw_size)
            player_by_seed = {seed: ordered_players[seed - 1] for seed in range(1, total_players + 1)}
            slots = [player_by_seed.get(seed) for seed in seed_order]
            return {"main_draw_size": main_draw_size, "direct_seeds": total_players, "main_draw_slots": slots, "preliminary_pairs": []}
        direct_seeds = (2 * main_draw_size) - total_players
        player_by_seed = {seed: ordered_players[seed - 1] for seed in range(1, total_players + 1)}
        preliminary_pairs = []
        preliminary_seed_slots = list(range(direct_seeds + 1, main_draw_size + 1))
        for seed_slot in preliminary_seed_slots:
            preliminary_pairs.append(
                [
                    player_by_seed[seed_slot],
                    player_by_seed[(2 * main_draw_size) - seed_slot + 1],
                ]
            )
        seed_order = self._standard_seed_order(main_draw_size)
        main_draw_slots: List[Optional[Player]] = []
        for seed_slot in seed_order:
            main_draw_slots.append(player_by_seed.get(seed_slot) if seed_slot <= direct_seeds else None)
        return {
            "main_draw_size": main_draw_size,
            "direct_seeds": direct_seeds,
            "main_draw_slots": main_draw_slots,
            "preliminary_pairs": preliminary_pairs,
            "preliminary_seed_slots": preliminary_seed_slots,
        }

    def _standard_seed_order(self, draw_size: int) -> List[int]:
        seeds = [1]
        while len(seeds) < draw_size:
            limit = (len(seeds) * 2) + 1
            seeds = [value for seed in seeds for value in (seed, limit - seed)]
        return seeds

    def _consecutive_pairs(self, participants: List[Player]) -> List[List[Player]]:
        return [participants[index : index + 2] for index in range(0, len(participants), 2)]

    def _swiss_round_limit(self, player_count: int) -> int:
        return max(3, math.ceil(math.log2(max(2, player_count))))

    def _build_swiss_pairings(
        self,
        players: List[Player],
        matches: List[Match],
        tournament: Tournament,
    ) -> List[List[Player]]:
        ordered_players = self._order_players_for_seeding(players, tournament.seeding_mode, tournament.id or 0)
        player_by_id = {player.id or 0: player for player in ordered_players}
        opponents: Dict[int, set[int]] = {player.id or 0: set() for player in ordered_players}
        stats: Dict[int, tuple[int, int, int, int]] = {player.id or 0: (0, 0, 0, 0) for player in ordered_players}
        for match in matches:
            if not match.stage.startswith("Швейцарка "):
                continue
            state = MatchState.from_dict(json.loads(match.current_state_json))
            opponents[match.player_a_id].add(match.player_b_id)
            opponents[match.player_b_id].add(match.player_a_id)
            wins_a, sets_a, points_a, diff_a = stats[match.player_a_id]
            wins_b, sets_b, points_b, diff_b = stats[match.player_b_id]
            match_points_a = sum(set_score.score_a for set_score in state.sets if set_score.winner_role)
            match_points_b = sum(set_score.score_b for set_score in state.sets if set_score.winner_role)
            set_diff_a = state.sets_won_a - state.sets_won_b
            set_diff_b = state.sets_won_b - state.sets_won_a
            stats[match.player_a_id] = (
                wins_a + (1 if state.winner_role == ROLE_A else 0),
                sets_a + set_diff_a,
                points_a + match_points_a,
                diff_a + match_points_a - match_points_b,
            )
            stats[match.player_b_id] = (
                wins_b + (1 if state.winner_role == ROLE_B else 0),
                sets_b + set_diff_b,
                points_b + match_points_b,
                diff_b + match_points_b - match_points_a,
            )
        ranked_ids = sorted(
            stats,
            key=lambda pid: (
                -stats[pid][0],
                -stats[pid][1],
                -stats[pid][3],
                -stats[pid][2],
                ordered_players.index(player_by_id[pid]),
            ),
        )
        pairings = self._pair_swiss_recursively(ranked_ids, opponents)
        if not pairings:
            raise ValueError("Не удалось составить корректные пары швейцарского раунда без повторных встреч.")
        return [[player_by_id[left], player_by_id[right]] for left, right in pairings]

    def _pair_swiss_recursively(
        self,
        ranked_ids: List[int],
        opponents: Dict[int, set[int]],
    ) -> Optional[List[tuple[int, int]]]:
        if not ranked_ids:
            return []
        first = ranked_ids[0]
        for index in range(1, len(ranked_ids)):
            candidate = ranked_ids[index]
            if candidate in opponents[first]:
                continue
            remaining = ranked_ids[1:index] + ranked_ids[index + 1 :]
            suffix = self._pair_swiss_recursively(remaining, opponents)
            if suffix is not None:
                return [(first, candidate), *suffix]
        return None

    def _round_robin_pairs_by_round(self, slot_count: int) -> List[List[tuple[int, int]]]:
        if slot_count == 3:
            return [[(1, 3)], [(1, 2)], [(2, 3)]]
        if slot_count == 4:
            return [[(1, 4), (2, 3)], [(1, 3), (2, 4)], [(1, 2), (3, 4)]]
        entries = list(range(1, slot_count + 1))
        if slot_count % 2 == 1:
            entries.append(0)
        rounds: List[List[tuple[int, int]]] = []
        for _ in range(len(entries) - 1):
            pairs = []
            for left, right in zip(entries[: len(entries) // 2], reversed(entries[len(entries) // 2 :])):
                if 0 not in {left, right}:
                    pairs.append((left, right))
            rounds.append(pairs)
            entries = [entries[0], entries[-1], *entries[1:-1]]
        return rounds

    def _build_group_schedule(self, groups: Dict[str, List[Player]], table_count: int) -> List[dict]:
        queues = {
            group_code: [{"matches": [(members[left - 1], members[right - 1]) for left, right in pairs]} for pairs in self._round_robin_pairs_by_round(len(members))]
            for group_code, members in groups.items()
        }
        previous_players: set[int] = set()
        schedule: List[dict] = []
        while any(queue for queue in queues.values()):
            slot_matches: List[dict] = []
            used_players: set[int] = set()
            candidates = []
            for group_code in sorted(queues):
                if not queues[group_code]:
                    continue
                batch = queues[group_code][0]
                batch.setdefault("remaining", list(batch["matches"]))
                for player_a, player_b in batch["remaining"]:
                    blocked = bool({player_a.id or 0, player_b.id or 0} & previous_players)
                    candidates.append((blocked, group_code, player_a, player_b))
            candidates.sort(key=lambda item: (item[0], item[1]))
            for _, group_code, player_a, player_b in candidates:
                if len(slot_matches) >= table_count:
                    break
                player_ids = {player_a.id or 0, player_b.id or 0}
                if player_ids & used_players:
                    continue
                batch = queues[group_code][0]
                if (player_a, player_b) not in batch["remaining"]:
                    continue
                batch["remaining"].remove((player_a, player_b))
                used_players |= player_ids
                slot_matches.append({"stage": f"{GROUP_STAGE_PREFIX}{group_code}", "table_no": str(len(slot_matches) + 1), "player_a": player_a, "player_b": player_b})
                if not batch["remaining"]:
                    queues[group_code].pop(0)
            if not slot_matches:
                raise ValueError("Не удалось составить расписание матчей.")
            previous_players = {item["player_a"].id or 0 for item in slot_matches} | {item["player_b"].id or 0 for item in slot_matches}
            schedule.extend(slot_matches)
        return schedule

    def _insert_generated_match(
        self,
        conn,
        tournament: Tournament,
        player_a_id: int,
        player_b_id: int,
        stage: str,
        table_no: str,
        round_no: int = 1,
        display_order: int = 0,
    ) -> None:
        cursor = conn.execute(
            """
            INSERT INTO matches (
                tournament_id, player_a_id, player_b_id, stage, table_no, referee,
                secretary, status, match_format, rule_mode, time_limit_enabled,
                time_limit_minutes, winner_role, finish_reason, started_at, ended_at,
                current_state_json, event_cursor, round_no, display_order, archived
            ) VALUES (?, ?, ?, ?, ?, '', '', ?, ?, ?, ?, ?, '', '', '', '', '', 0, ?, ?, 0)
            """,
            (
                tournament.id,
                player_a_id,
                player_b_id,
                stage,
                table_no,
                MATCH_STATUS_NOT_STARTED,
                tournament.match_format,
                tournament.rule_mode,
                int(tournament.time_limit_enabled),
                tournament.time_limit_minutes,
                round_no,
                display_order,
            ),
        )
        match_id = int(cursor.lastrowid)
        state = create_initial_state(match_id=match_id, tournament_id=tournament.id or 0, match_format=tournament.match_format, rule_mode=tournament.rule_mode, time_limit_enabled=tournament.time_limit_enabled, time_limit_minutes=tournament.time_limit_minutes)
        conn.execute("UPDATE matches SET current_state_json = ? WHERE id = ?", (json.dumps(state.to_dict(), ensure_ascii=False), match_id))

    def _next_round_number(self, matches: List[Match]) -> int:
        return (max((match.round_no for match in matches), default=0)) + 1

    def _archive_current_round(self, conn, tournament_id: int) -> None:
        conn.execute("UPDATE matches SET archived = 1 WHERE tournament_id = ? AND archived = 0", (tournament_id,))


class MatchService:
    def __init__(self, db: Database, paths: AppPaths) -> None:
        self.db = db
        self.paths = paths

    def create_match(self, tournament: Tournament, player_a_id: int, player_b_id: int, stage: str, table_no: str, referee: str, secretary: str) -> Match:
        if player_a_id == player_b_id:
            raise ValueError("Игрок A и игрок B не могут совпадать")
        existing_matches = self.list_matches(tournament.id or 0, include_archived=True)
        current_round_no = max((match.round_no for match in existing_matches if not match.archived), default=1)
        current_round_count = sum(1 for match in existing_matches if not match.archived and match.round_no == current_round_no)
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO matches (
                    tournament_id, player_a_id, player_b_id, stage, table_no, referee,
                    secretary, status, match_format, rule_mode, time_limit_enabled,
                    time_limit_minutes, winner_role, finish_reason, started_at, ended_at,
                    current_state_json, event_cursor, round_no, display_order, archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '', '', '', 0, ?, ?, 0)
                """,
                (
                    tournament.id,
                    player_a_id,
                    player_b_id,
                    stage,
                    table_no,
                    referee,
                    secretary,
                    MATCH_STATUS_NOT_STARTED,
                    tournament.match_format,
                    tournament.rule_mode,
                    int(tournament.time_limit_enabled),
                    tournament.time_limit_minutes,
                    current_round_no,
                    current_round_count + 1,
                ),
            )
            match_id = int(cursor.lastrowid)
            state = create_initial_state(match_id=match_id, tournament_id=tournament.id or 0, match_format=tournament.match_format, rule_mode=tournament.rule_mode, time_limit_enabled=tournament.time_limit_enabled, time_limit_minutes=tournament.time_limit_minutes)
            conn.execute("UPDATE matches SET current_state_json = ? WHERE id = ?", (json.dumps(state.to_dict(), ensure_ascii=False), match_id))
            row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        return row_to_match(row)

    def list_matches(self, tournament_id: int, include_archived: bool = False) -> List[Match]:
        with self.db.connection() as conn:
            query = "SELECT * FROM matches WHERE tournament_id = ?"
            params: List[object] = [tournament_id]
            if not include_archived:
                query += " AND archived = 0"
            query += " ORDER BY round_no, display_order, id"
            rows = conn.execute(query, params).fetchall()
        return [row_to_match(row) for row in rows]

    def record_match_result(self, match_id: int, set_scores: List[object], winner_role: str, finish_reason: str = "Результат внесен вручную") -> MatchState:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
            if not row:
                raise ValueError("Матч не найден")
            match = row_to_match(row)
            state = MatchState.from_dict(json.loads(match.current_state_json))
            normalized_sets = self._normalize_set_scores(set_scores)
            if not normalized_sets:
                raise ValueError("Нужно указать хотя бы один завершенный сет.")
            state.first_set_starter_role = normalized_sets[0]["starter_role"]
            state.sets = []
            state.current_set_no = 1
            state.sets_won_a = 0
            state.sets_won_b = 0
            state.finish_reason = finish_reason
            state.status = MATCH_STATUS_COMPLETED
            state.started_at = state.started_at or now_iso()
            state.ended_at = now_iso()
            state.log_lines = []
            for index, set_payload in enumerate(normalized_sets, start=1):
                starter_role = set_payload["starter_role"]
                starter_score = set_payload["starter_score"]
                receiver_score = set_payload["receiver_score"]
                score_a = starter_score if starter_role == ROLE_A else receiver_score
                score_b = receiver_score if starter_role == ROLE_A else starter_score
                set_winner = ROLE_A if score_a > score_b else ROLE_B
                if set_winner == ROLE_A:
                    state.sets_won_a += 1
                else:
                    state.sets_won_b += 1
                state.sets.append(SetScore(set_no=index, starter_role=starter_role, score_a=score_a, score_b=score_b, winner_role=set_winner, started_at=state.started_at, ended_at=state.ended_at))
                state.log_lines.append(f"{now_iso()[11:19]} | Сет {index} | Результат внесен вручную | счет {starter_score}:{receiver_score}")
            target_sets = needed_sets_to_win(match.match_format)
            for index, set_score in enumerate(state.sets[:-1], start=1):
                wins_a = sum(1 for item in state.sets[:index] if item.winner_role == ROLE_A)
                wins_b = sum(1 for item in state.sets[:index] if item.winner_role == ROLE_B)
                if max(wins_a, wins_b) >= target_sets:
                    raise ValueError("Указаны лишние сеты после завершения матча.")
            inferred_winner_role = ROLE_A if state.sets_won_a > state.sets_won_b else ROLE_B
            if max(state.sets_won_a, state.sets_won_b) < target_sets:
                raise ValueError("Матч не завершен по количеству выигранных сетов.")
            if winner_role != inferred_winner_role:
                raise ValueError("Выбранный победитель не соответствует счету по сетам.")
            state.winner_role = inferred_winner_role
            state.current_set_no = len(state.sets)
            state.current_server = normalized_sets[-1]["starter_role"]
            state.serve_no = 1
            record = MatchEventRecord(id=None, match_id=match_id, seq_no=1, set_no=len(state.sets), timestamp=now_iso(), event_type="manual_result", actor_role=winner_role, beneficiary_role=winner_role, description=f"Результат матча внесен вручную. Победитель: игрок {winner_role}", state_before_json=row["current_state_json"], state_after_json=json.dumps(state.to_dict(), ensure_ascii=False))
            conn.execute("DELETE FROM match_events WHERE match_id = ?", (match_id,))
            conn.execute(
                """
                INSERT INTO match_events (
                    match_id, seq_no, set_no, timestamp, event_type, event_subtype,
                    actor_role, beneficiary_role, points_awarded, score_a_after,
                    score_b_after, server_after, serve_no_after, description,
                    is_official_event, state_before_json, state_after_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record.match_id, record.seq_no, record.set_no, record.timestamp, record.event_type, "", record.actor_role, record.beneficiary_role, 0, state.sets[-1].score_a, state.sets[-1].score_b, state.current_server, state.serve_no, record.description, 1, record.state_before_json, record.state_after_json),
            )
            conn.execute(
                """
                UPDATE matches SET
                    status = ?, winner_role = ?, finish_reason = ?, started_at = ?, ended_at = ?,
                    current_state_json = ?, event_cursor = ?
                WHERE id = ?
                """,
                (state.status, state.winner_role, state.finish_reason, state.started_at, state.ended_at, json.dumps(state.to_dict(), ensure_ascii=False), 1, match_id),
            )
        return state

    def get_match(self, match_id: int) -> Match:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        if not row:
            raise ValueError("Матч не найден")
        return row_to_match(row)

    def update_match(self, match_id: int, player_a_id: int, player_b_id: int, stage: str, table_no: str, referee: str, secretary: str) -> Match:
        if player_a_id == player_b_id:
            raise ValueError("Игрок A и игрок B не могут совпадать")
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
            if not row:
                raise ValueError("Матч не найден")
            match = row_to_match(row)
            conn.execute(
                """
                UPDATE matches
                SET player_a_id = ?, player_b_id = ?, stage = ?, table_no = ?, referee = ?, secretary = ?
                WHERE id = ?
                """,
                (player_a_id, player_b_id, stage.strip(), table_no.strip(), referee.strip(), secretary.strip(), match_id),
            )
            refreshed = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        return row_to_match(refreshed)

    def delete_match(self, match_id: int) -> None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT id FROM matches WHERE id = ?", (match_id,)).fetchone()
            if not row:
                raise ValueError("Матч не найден")
            conn.execute("DELETE FROM match_events WHERE match_id = ?", (match_id,))
            conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))

    def load_state(self, match_id: int) -> MatchState:
        match = self.get_match(match_id)
        if not match.current_state_json:
            raise ValueError("Состояние матча не инициализировано")
        return MatchState.from_dict(json.loads(match.current_state_json))

    def apply_event(self, match_id: int, command: MatchCommand) -> MatchState:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
            if not row:
                raise ValueError("Матч не найден")
            match = row_to_match(row)
            state = MatchState.from_dict(json.loads(match.current_state_json))
            future_exists = conn.execute("SELECT COUNT(1) FROM match_events WHERE match_id = ? AND seq_no > ?", (match_id, match.event_cursor)).fetchone()[0]
            if future_exists:
                conn.execute("DELETE FROM match_events WHERE match_id = ? AND seq_no > ?", (match_id, match.event_cursor))
            updated, record = apply_command(state, command, match.event_cursor + 1)
            record.state_before_json = json.dumps(state.to_dict(), ensure_ascii=False)
            record.state_after_json = json.dumps(updated.to_dict(), ensure_ascii=False)
            conn.execute(
                """
                INSERT INTO match_events (
                    match_id, seq_no, set_no, timestamp, event_type, event_subtype,
                    actor_role, beneficiary_role, points_awarded, score_a_after,
                    score_b_after, server_after, serve_no_after, description,
                    is_official_event, state_before_json, state_after_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record.match_id, record.seq_no, record.set_no, record.timestamp, record.event_type, record.event_subtype, record.actor_role, record.beneficiary_role, record.points_awarded, record.score_a_after, record.score_b_after, record.server_after, record.serve_no_after, record.description, int(record.is_official_event), record.state_before_json, record.state_after_json),
            )
            conn.execute(
                """
                UPDATE matches SET
                    status = ?, winner_role = ?, finish_reason = ?, started_at = ?, ended_at = ?,
                    current_state_json = ?, event_cursor = ?
                WHERE id = ?
                """,
                (updated.status, updated.winner_role, updated.finish_reason, updated.started_at, updated.ended_at, json.dumps(updated.to_dict(), ensure_ascii=False), record.seq_no, match_id),
            )
            if updated.status in {MATCH_STATUS_COMPLETED, MATCH_STATUS_DEFAULTED}:
                backup_name = f"tournament_{match.tournament_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                self.db.backup(self.paths.backup_dir / backup_name)
        return updated
    def undo(self, match_id: int) -> MatchState:
        with self.db.connection() as conn:
            match = row_to_match(conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone())
            if match.event_cursor <= 0:
                raise MatchValidationError("Нет действий для отмены")
            event_row = conn.execute("SELECT * FROM match_events WHERE match_id = ? AND seq_no = ?", (match_id, match.event_cursor)).fetchone()
            state = MatchState.from_dict(json.loads(event_row["state_before_json"]))
            conn.execute("UPDATE matches SET current_state_json = ?, event_cursor = ?, status = ?, winner_role = ?, finish_reason = ?, started_at = ?, ended_at = ? WHERE id = ?", (json.dumps(state.to_dict(), ensure_ascii=False), match.event_cursor - 1, state.status, state.winner_role, state.finish_reason, state.started_at, state.ended_at, match_id))
        return state

    def redo(self, match_id: int) -> MatchState:
        with self.db.connection() as conn:
            match = row_to_match(conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone())
            next_row = conn.execute("SELECT * FROM match_events WHERE match_id = ? AND seq_no = ?", (match_id, match.event_cursor + 1)).fetchone()
            if not next_row:
                raise MatchValidationError("Нет действий для повтора")
            state = MatchState.from_dict(json.loads(next_row["state_after_json"]))
            conn.execute("UPDATE matches SET current_state_json = ?, event_cursor = ?, status = ?, winner_role = ?, finish_reason = ?, started_at = ?, ended_at = ? WHERE id = ?", (json.dumps(state.to_dict(), ensure_ascii=False), match.event_cursor + 1, state.status, state.winner_role, state.finish_reason, state.started_at, state.ended_at, match_id))
        return state

    def cancel_match(self, match_id: int) -> MatchState:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
            if not row:
                raise ValueError("Матч не найден")
            match = row_to_match(row)
            cleared_state = create_initial_state(match_id=match.id or 0, tournament_id=match.tournament_id, match_format=match.match_format, rule_mode=match.rule_mode, time_limit_enabled=False, time_limit_minutes=0)
            cleared_state.status = "cancelled"
            cleared_state.finish_reason = "Матч завершен экстренно"
            cleared_state.started_at = match.started_at
            cleared_state.ended_at = now_iso()
            conn.execute("DELETE FROM match_events WHERE match_id = ?", (match_id,))
            conn.execute("UPDATE matches SET status = ?, winner_role = '', finish_reason = ?, ended_at = ?, current_state_json = ?, event_cursor = 0 WHERE id = ?", ("cancelled", cleared_state.finish_reason, cleared_state.ended_at, json.dumps(cleared_state.to_dict(), ensure_ascii=False), match_id))
        return cleared_state

    def list_event_records(self, match_id: int) -> List[MatchEventRecord]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM match_events WHERE match_id = ? ORDER BY seq_no", (match_id,)).fetchall()
        return [MatchEventRecord(id=row["id"], match_id=row["match_id"], seq_no=row["seq_no"], set_no=row["set_no"], timestamp=row["timestamp"], event_type=row["event_type"], event_subtype=row["event_subtype"], actor_role=row["actor_role"], beneficiary_role=row["beneficiary_role"], points_awarded=row["points_awarded"], score_a_after=row["score_a_after"], score_b_after=row["score_b_after"], server_after=row["server_after"], serve_no_after=row["serve_no_after"], description=row["description"], is_official_event=bool(row["is_official_event"]), state_before_json=row["state_before_json"], state_after_json=row["state_after_json"]) for row in rows]

    def _normalize_set_scores(self, set_scores: List[object]) -> List[dict]:
        normalized: List[dict] = []
        first_starter: Optional[str] = None
        for index, set_score in enumerate(set_scores, start=1):
            if isinstance(set_score, dict):
                starter_role = set_score["starter_role"]
                starter_score = int(set_score["starter_score"])
                receiver_score = int(set_score["receiver_score"])
            else:
                score_a, score_b = set_score
                starter_role = ROLE_A if index % 2 == 1 else ROLE_B
                starter_score = int(score_a) if starter_role == ROLE_A else int(score_b)
                receiver_score = int(score_b) if starter_role == ROLE_A else int(score_a)
            if starter_score == receiver_score:
                raise ValueError(f"Сет {index}: ничья недопустима.")
            if first_starter is None:
                first_starter = starter_role
            else:
                expected = first_starter if index % 2 == 1 else other_role(first_starter)
                if starter_role != expected:
                    raise ValueError("Начинающий сет должен чередоваться по регламенту.")
            normalized.append({"starter_role": starter_role, "starter_score": starter_score, "receiver_score": receiver_score})
        return normalized


class ReportService:
    def __init__(self, tournament_service: TournamentService, match_service: MatchService):
        self.tournament_service = tournament_service
        self.match_service = match_service

    def generate_report(self, tournament_id: int, output_dir: Path, include_details: bool) -> Path:
        tournament = self.tournament_service.get_tournament(tournament_id)
        players = self.tournament_service.list_players(tournament_id)
        matches = self.match_service.list_matches(tournament_id, include_archived=True)
        player_by_id = {player.id: player for player in players}
        standings = self.build_standings(tournament_id)
        tournament_winner = standings[0].player_name if standings else "Не определен"
        format_label = dict(TOURNAMENT_FORMATS).get(tournament.tournament_format, tournament.tournament_format)
        competition_label = dict(COMPETITION_MODES).get(tournament.competition_mode, tournament.competition_mode)
        lines = [f"ТУРНИР: {tournament.name}", f"Дата: {tournament.event_date}", f"Место: {tournament.location}", f"Тип турнира: {format_label}", f"Система проведения: {competition_label}", f"Количество столов: {tournament.table_count}", f"Формат игры: до {needed_sets_to_win(tournament.match_format)} выигранных сетов", f"Отчет сформирован: {datetime.now().strftime('%d.%m.%Y %H:%M')}", f"Победитель турнира: {tournament_winner}", "", "ИГРОКИ:"]
        for index, player in enumerate(players, start=1):
            rating_label = player.rating if player.rating is not None else "без рейтинга"
            city_label = player.city or "город не указан"
            lines.append(f"{index}. {player.full_name} | рейтинг: {rating_label} | город: {city_label} | {player.status}")
        lines.append("")
        group_matches = [match for match in matches if match.stage.startswith(GROUP_STAGE_PREFIX)]
        if group_matches:
            lines.append("ПРОМЕЖУТОЧНЫЕ РЕЗУЛЬТАТЫ ПО ГРУППАМ:")
            rankings = self.tournament_service._group_rankings_with_stats(group_matches, tournament_id)
            for code in sorted(rankings):
                lines.append(f"Группа {code}:")
                for place, standing in enumerate(rankings[code], start=1):
                    lines.append(
                        f"{place}. {standing.player_name} | очков {standing.tournament_points} | побед {standing.wins} | "
                        f"поражений {standing.losses} | сеты {standing.sets_won}:{standing.sets_lost} | "
                        f"забито/пропущено {standing.points_won}:{standing.points_lost} | разница {standing.points_diff}"
                    )
                lines.append("")
        for report_index, match in enumerate(matches, start=1):
            state = self.match_service.load_state(match.id or 0)
            player_a = player_by_id.get(match.player_a_id)
            player_b = player_by_id.get(match.player_b_id)
            player_a_name = player_a.full_name if player_a else str(match.player_a_id)
            player_b_name = player_b.full_name if player_b else str(match.player_b_id)
            group_label = match.stage.replace(GROUP_STAGE_PREFIX, "").strip() if match.stage.startswith(GROUP_STAGE_PREFIX) else ""
            lines.append(f"МАТЧ {report_index}")
            if group_label:
                lines.append(f"Группа: {group_label}")
            else:
                lines.append(f"Стадия: {match.stage}")
            lines.append(f"Стол: {match.table_no}")
            lines.append(f"Результат по сетам: {state.sets_won_a}:{state.sets_won_b}")
            set_fragments = []
            for set_score in state.sets:
                if not set_score.winner_role:
                    continue
                starter_name = player_a_name if set_score.starter_role == ROLE_A else player_b_name
                starter_points = set_score.score_a if set_score.starter_role == ROLE_A else set_score.score_b
                receiver_points = set_score.score_b if set_score.starter_role == ROLE_A else set_score.score_a
                set_fragments.append(f"{starter_points}:{receiver_points} (начинал {starter_name})")
            if set_fragments:
                lines.append(f"{player_a_name} - {player_b_name}: {state.sets_won_a}:{state.sets_won_b}. " + ", ".join(set_fragments))
            if state.winner_role:
                winner_name = player_a_name if state.winner_role == ROLE_A else player_b_name
                lines.append(f"Победитель: {winner_name}")
            if include_details:
                lines.append("")
                lines.append("ЖУРНАЛ СОБЫТИЙ:")
                for event in self.match_service.list_event_records(match.id or 0):
                    lines.append(f"{event.timestamp[11:19]} | Сет {event.set_no} | {event.description}")
                lines.append("")
        if standings:
            lines.append("ИТОГОВАЯ ТАБЛИЦА:")
            for place, standing in enumerate(standings, start=1):
                lines.append(
                    f"{place}. {standing.player_name} | турнирных очков {standing.tournament_points} | побед {standing.wins} | "
                    f"поражений {standing.losses} | сеты {standing.sets_won}:{standing.sets_lost} | "
                    f"забито/пропущено {standing.points_won}:{standing.points_lost} | разница {standing.points_diff}"
                )
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"showdown_report_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.txt"
        target = output_dir / filename
        target.write_text("\n".join(lines), encoding="utf-8")
        return target

    def build_standings(self, tournament_id: int) -> List[TournamentStanding]:
        tournament = self.tournament_service.get_tournament(tournament_id)
        players = self.tournament_service.list_players(tournament_id)
        matches = self.match_service.list_matches(tournament_id, include_archived=True)
        standings: Dict[int, TournamentStanding] = {player.id or 0: TournamentStanding(player_id=player.id or 0, player_name=player.full_name) for player in players}
        for match in matches:
            if not match.current_state_json:
                continue
            state = self.match_service.load_state(match.id or 0)
            if state.status not in {MATCH_STATUS_COMPLETED, MATCH_STATUS_DEFAULTED}:
                continue
            standing_a = standings.get(match.player_a_id)
            standing_b = standings.get(match.player_b_id)
            if not standing_a or not standing_b:
                continue
            if state.winner_role == ROLE_A:
                standing_a.wins += 1
                standing_b.losses += 1
            elif state.winner_role == ROLE_B:
                standing_b.wins += 1
                standing_a.losses += 1
            standing_a.tournament_points += self.tournament_service._match_result_points(state.sets_won_a, state.sets_won_b, state.winner_role == ROLE_A)
            standing_b.tournament_points += self.tournament_service._match_result_points(state.sets_won_b, state.sets_won_a, state.winner_role == ROLE_B)
            for set_score in state.sets:
                if not set_score.winner_role:
                    continue
                standing_a.sets_won += 1 if set_score.winner_role == ROLE_A else 0
                standing_a.sets_lost += 1 if set_score.winner_role == ROLE_B else 0
                standing_b.sets_won += 1 if set_score.winner_role == ROLE_B else 0
                standing_b.sets_lost += 1 if set_score.winner_role == ROLE_A else 0
                standing_a.points_won += set_score.score_a
                standing_a.points_lost += set_score.score_b
                standing_b.points_won += set_score.score_b
                standing_b.points_lost += set_score.score_a
        group_matches = [match for match in matches if match.stage.startswith(GROUP_STAGE_PREFIX)]
        if tournament.competition_mode == "group_playoff" and group_matches:
            rankings = self.tournament_service._group_rankings_with_stats(group_matches, tournament_id)
            group_places = {}
            for code in sorted(rankings):
                for place, standing in enumerate(rankings[code], start=1):
                    group_places[standing.player_id] = place
            return sorted(
                standings.values(),
                key=lambda item: (
                    group_places.get(item.player_id, 999),
                    -item.wins,
                    -item.tournament_points,
                    -item.points_diff,
                    -item.points_won,
                    item.player_name.casefold(),
                ),
            )
        return sorted(
            standings.values(),
            key=lambda item: (
                -item.wins,
                -item.tournament_points,
                -item.points_diff,
                -item.points_won,
                item.player_name.casefold(),
            ),
        )


def default_tournament() -> Tournament:
    today = date.today().isoformat()
    return Tournament(
        id=None,
        name="",
        event_date=today,
        tournament_format="individual",
        table_count=1,
        match_format=5,
        match_duration_minutes=30,
        day_start_time="09:00",
    )


class ReportService(ReportService):
    def generate_report(self, tournament_id: int, output_dir: Path, include_details: bool) -> Path:
        tournament = self.tournament_service.get_tournament(tournament_id)
        players = self.tournament_service.list_players(tournament_id)
        matches = self.match_service.list_matches(tournament_id, include_archived=True)
        player_by_id = {player.id: player for player in players}
        standings = self.build_standings(tournament_id)
        tournament_winner = standings[0].player_name if standings else "Не определен"
        format_label = dict(TOURNAMENT_FORMATS).get(tournament.tournament_format, tournament.tournament_format)
        competition_label = dict(COMPETITION_MODES).get(tournament.competition_mode, tournament.competition_mode)
        lines = [
            f"ТУРНИР: {tournament.name}",
            f"Дата: {tournament.event_date}",
            f"Место: {tournament.location}",
            f"Тип турнира: {format_label}",
            f"Система проведения: {competition_label}",
            f"Количество столов: {tournament.table_count}",
            f"Формат игры: до {needed_sets_to_win(tournament.match_format)} выигранных сетов",
            f"Отчет сформирован: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"Победитель турнира: {tournament_winner}",
            "",
            "ИГРОКИ:",
        ]
        for index, player in enumerate(players, start=1):
            rating_label = player.rating if player.rating is not None else "без рейтинга"
            city_label = player.city or "город не указан"
            lines.append(f"{index}. {player.full_name} | рейтинг: {rating_label} | город: {city_label} | {player.status}")
        lines.append("")
        group_matches = [match for match in matches if match.stage.startswith(GROUP_STAGE_PREFIX)]
        if group_matches:
            lines.append("ПРОМЕЖУТОЧНЫЕ РЕЗУЛЬТАТЫ ПО ГРУППАМ:")
            rankings = self.tournament_service._group_rankings_with_stats(group_matches, tournament_id)
            for code in sorted(rankings):
                lines.append(f"Группа {code}:")
                for place, standing in enumerate(rankings[code], start=1):
                    lines.append(
                        f"{place}. {standing.player_name} | очков {standing.tournament_points} | побед {standing.wins} | "
                        f"поражений {standing.losses} | сеты {standing.sets_won}:{standing.sets_lost} | "
                        f"забито/пропущено {standing.points_won}:{standing.points_lost} | разница {standing.points_diff}"
                    )
                lines.append("")
        for report_index, match in enumerate(matches, start=1):
            state = self.match_service.load_state(match.id or 0)
            player_a = player_by_id.get(match.player_a_id)
            player_b = player_by_id.get(match.player_b_id)
            player_a_name = player_a.full_name if player_a else str(match.player_a_id)
            player_b_name = player_b.full_name if player_b else str(match.player_b_id)
            group_label = match.stage.replace(GROUP_STAGE_PREFIX, "").strip() if match.stage.startswith(GROUP_STAGE_PREFIX) else ""
            lines.append(f"МАТЧ {report_index}")
            lines.append(f"Группа: {group_label}" if group_label else f"Стадия: {match.stage}")
            lines.append(f"Стол: {match.table_no}")
            set_fragments = []
            for set_score in state.sets:
                if not set_score.winner_role:
                    continue
                starter_name = player_a_name if set_score.starter_role == ROLE_A else player_b_name
                starter_points = set_score.score_a if set_score.starter_role == ROLE_A else set_score.score_b
                receiver_points = set_score.score_b if set_score.starter_role == ROLE_A else set_score.score_a
                set_fragments.append(f"{starter_points}:{receiver_points} (начинал {starter_name})")
            if set_fragments:
                lines.append(f"{player_a_name} - {player_b_name}: {state.sets_won_a}:{state.sets_won_b}. " + ", ".join(set_fragments))
            if state.winner_role:
                winner_name = player_a_name if state.winner_role == ROLE_A else player_b_name
                lines.append(f"Победитель: {winner_name}")
            if include_details:
                lines.append("")
                lines.append("ЖУРНАЛ СОБЫТИЙ:")
                for event in self.match_service.list_event_records(match.id or 0):
                    lines.append(f"{event.timestamp[11:19]} | Сет {event.set_no} | {event.description}")
            lines.append("")
        if standings:
            lines.append("ИТОГОВАЯ ТАБЛИЦА:")
            for place, standing in enumerate(standings, start=1):
                lines.append(
                    f"{place}. {standing.player_name} | турнирных очков {standing.tournament_points} | побед {standing.wins} | "
                    f"поражений {standing.losses} | сеты {standing.sets_won}:{standing.sets_lost} | "
                    f"забито/пропущено {standing.points_won}:{standing.points_lost} | разница {standing.points_diff}"
                )
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"showdown_report_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.txt"
        target = output_dir / filename
        target.write_text("\n".join(lines), encoding="utf-8")
        return target

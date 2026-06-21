from pathlib import Path
import shutil
import sqlite3

from showdown_app.application.services import MatchService, TournamentService
from showdown_app.domain.models import Player, Tournament
from showdown_app.infrastructure.database import Database
from showdown_app.paths import AppPaths
from showdown_app.settings import AppSettings


def build_paths(tmp_path: Path) -> AppPaths:
    data_dir = tmp_path / "data"
    reports_dir = tmp_path / "reports"
    backup_dir = data_dir / "backup"
    data_dir.mkdir()
    reports_dir.mkdir()
    backup_dir.mkdir()
    return AppPaths(
        root=tmp_path,
        data_dir=data_dir,
        reports_dir=reports_dir,
        backup_dir=backup_dir,
        error_log=tmp_path / "error.log",
        settings_file=data_dir / "settings.json",
        database_file=data_dir / "tournaments.db",
    )


def make_workspace(name: str) -> Path:
    root = Path.cwd() / ".tests_runtime" / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def _play_single_elimination_to_finish(
    tournament_service: TournamentService,
    match_service: MatchService,
    tournament_id: int,
) -> int:
    completed = 0
    while True:
        active_matches = match_service.list_matches(tournament_id)
        unfinished = [match for match in active_matches if match.status not in {"completed", "defaulted"}]
        if unfinished:
            for match in unfinished:
                winner_role = "A" if match.player_a_id < match.player_b_id else "B"
                set_scores = [(11, 7), (11, 8)] if winner_role == "A" else [(7, 11), (8, 11)]
                match_service.record_match_result(match.id or 0, set_scores, winner_role)
                completed += 1
            continue
        try:
            tournament_service.generate_next_stage(tournament_id)
        except ValueError as exc:
            if "полностью" in str(exc).lower() or "уже заверш" in str(exc).lower():
                break
            raise
    return completed


def test_can_create_and_reopen_many_tournaments():
    workspace = make_workspace("many_tournaments")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    service = TournamentService(db, paths, settings)

    for index in range(150):
        service.create_tournament(
            Tournament(
                id=None,
                name=f"Турнир {index + 1}",
                event_date=f"2026-04-{(index % 28) + 1:02d}",
                location=f"Город {(index % 12) + 1}",
            )
        )

    reopened = TournamentService(Database(paths), paths, AppSettings.load(paths))
    tournaments = reopened.list_tournaments()

    assert len(tournaments) == 150
    assert {item.name for item in tournaments} == {f"Турнир {index + 1}" for index in range(150)}


def test_sqlite_backup_creates_valid_database_snapshot():
    workspace = make_workspace("database_backup")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    service = TournamentService(db, paths, settings)
    tournament = service.create_tournament(Tournament(id=None, name="Backup Cup", event_date="2026-04-30"))

    backup_path = paths.backup_dir / "snapshot.db"
    db.backup(backup_path)

    with sqlite3.connect(backup_path) as conn:
        row = conn.execute("SELECT name FROM tournaments WHERE id = ?", (tournament.id,)).fetchone()

    assert row is not None
    assert row[0] == "Backup Cup"


def test_eighty_player_single_elimination_can_finish_cleanly():
    workspace = make_workspace("eighty_players")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(
            id=None,
            name="Большой тестовый турнир",
            event_date="2026-04-30",
            location="Алматы",
            competition_mode="single_elimination",
            tournament_format="individual",
            table_count=10,
            seeding_mode="snake",
            match_format=3,
            match_duration_minutes=25,
        )
    )
    for index in range(80):
        tournament_service.save_player(
            Player(
                id=None,
                tournament_id=tournament.id or 0,
                full_name=f"Игрок {index + 1}",
                city=f"Город {(index % 16) + 1}",
                rating=2500 - index,
            )
        )

    initial_created = tournament_service.generate_group_stage(tournament.id or 0)
    completed_matches = _play_single_elimination_to_finish(
        tournament_service,
        match_service,
        tournament.id or 0,
    )
    final_matches = [match for match in match_service.list_matches(tournament.id or 0, include_archived=True) if match.stage == "Финал"]

    assert initial_created > 0
    assert completed_matches == 80
    assert len(final_matches) == 1

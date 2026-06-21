from pathlib import Path
import shutil

from showdown_app.application.services import MatchService, ReportService, TournamentService
from showdown_app.domain.models import EVENT_ERROR, EVENT_GOAL, MatchCommand, Player, Tournament
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


def test_services_create_match_apply_events_undo_redo_and_report():
    paths = build_paths(make_workspace("services_flow"))
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)
    report_service = ReportService(tournament_service, match_service)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Open Showdown Cup", event_date="2026-04-16")
    )
    player_a = tournament_service.save_player(
        Player(
            id=None,
            tournament_id=tournament.id or 0,
            full_name="Иванов Иван",
            organization="Казахстан",
        )
    )
    player_b = tournament_service.save_player(
        Player(
            id=None,
            tournament_id=tournament.id or 0,
            full_name="Петров Петр",
            organization="Россия",
        )
    )

    match = match_service.create_match(
        tournament,
        player_a.id or 0,
        player_b.id or 0,
        stage="группа A",
        table_no="1",
        referee="Судья",
        secretary="Секретарь",
    )

    state = match_service.apply_event(match.id or 0, MatchCommand(EVENT_GOAL, actor_role="A"))
    assert state.current_set.score_a == 2
    state = match_service.apply_event(
        match.id or 0, MatchCommand(EVENT_ERROR, actor_role="B", subtype="center_board")
    )
    assert state.current_set.score_a == 3

    undone = match_service.undo(match.id or 0)
    assert undone.current_set.score_a == 2
    redone = match_service.redo(match.id or 0)
    assert redone.current_set.score_a == 3

    report_path = report_service.generate_report(tournament.id or 0, paths.reports_dir, True)
    content = report_path.read_text(encoding="utf-8")
    assert "Open Showdown Cup" in content
    assert player_a.full_name in content
    assert "ИТОГОВАЯ ТАБЛИЦА:" in content
    assert "ПРОМЕЖУТОЧНЫЕ РЕЗУЛЬТАТЫ ПО ГРУППАМ:" not in content
    assert "ЖУРНАЛ СОБЫТИЙ" in content
    assert "забито/пропущено" in content
    assert "разница" in content


def test_import_players_from_txt():
    workspace = make_workspace("import_players")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Test", event_date="2026-04-16")
    )
    source = workspace / "players.txt"
    source.write_text("Игрок Один\nИгрок Два\n", encoding="utf-8")
    count = tournament_service.import_players(tournament.id or 0, source)
    assert count == 2
    assert len(tournament_service.list_players(tournament.id or 0)) == 2


def test_tournaments_are_saved_and_can_be_listed_again():
    workspace = make_workspace("tournament_persistence")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)

    first = tournament_service.create_tournament(Tournament(id=None, name="First Cup", event_date="2026-04-15"))
    second = tournament_service.create_tournament(Tournament(id=None, name="Second Cup", event_date="2026-04-16"))

    listed = tournament_service.list_tournaments()

    assert [item.name for item in listed[:2]] == ["Second Cup", "First Cup"]
    assert tournament_service.get_tournament(first.id or 0).name == "First Cup"
    assert tournament_service.get_tournament(second.id or 0).name == "Second Cup"


def test_tournament_data_persists_after_reopen():
    workspace = make_workspace("tournament_reopen")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)

    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(Tournament(id=None, name="Persistent Cup", event_date="2026-04-20"))
    player_a = tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Игрок 1", city="Алматы"))
    player_b = tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Игрок 2", city="Астана"))
    match = match_service.create_match(
        tournament,
        player_a.id or 0,
        player_b.id or 0,
        stage="Финал",
        table_no="1",
        referee="",
        secretary="",
    )
    match_service.record_match_result(match.id or 0, [(11, 7), (11, 8)], "A")

    reopened_settings = AppSettings.load(paths)
    reopened_db = Database(paths)
    reopened_tournament_service = TournamentService(reopened_db, paths, reopened_settings)
    reopened_match_service = MatchService(reopened_db, paths)

    tournaments = reopened_tournament_service.list_tournaments()
    players = reopened_tournament_service.list_players(tournament.id or 0)
    matches = reopened_match_service.list_matches(tournament.id or 0)
    state = reopened_match_service.load_state(match.id or 0)

    assert tournaments[0].name == "Persistent Cup"
    assert [player.full_name for player in players] == ["Игрок 1", "Игрок 2"]
    assert len(matches) == 1
    assert matches[0].stage == "Финал"
    assert state.winner_role == "A"
    assert state.sets_won_a == 2


def test_manual_result_updates_report_and_standings():
    workspace = make_workspace("manual_result")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)
    report_service = ReportService(tournament_service, match_service)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Cup", event_date="2026-04-16")
    )
    player_a = tournament_service.save_player(
        Player(id=None, tournament_id=tournament.id or 0, full_name="Игрок А")
    )
    player_b = tournament_service.save_player(
        Player(id=None, tournament_id=tournament.id or 0, full_name="Игрок Б")
    )
    match = match_service.create_match(
        tournament,
        player_a.id or 0,
        player_b.id or 0,
        stage="Финал",
        table_no="1",
        referee="",
        secretary="",
    )

    state = match_service.record_match_result(match.id or 0, [(11, 8), (11, 9)], "A")
    assert state.winner_role == "A"
    assert state.sets_won_a == 2

    standings = report_service.build_standings(tournament.id or 0)
    assert standings[0].player_name == "Игрок А"
    assert standings[0].wins == 1

    report_path = report_service.generate_report(tournament.id or 0, paths.reports_dir, False)
    content = report_path.read_text(encoding="utf-8")
    assert "Победитель турнира: Игрок А" in content
    assert "ИТОГОВАЯ ТАБЛИЦА:" in content


def test_cancel_match_clears_live_data_and_marks_cancelled():
    workspace = make_workspace("cancel_match")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Cancel Cup", event_date="2026-04-16")
    )
    player_a = tournament_service.save_player(
        Player(id=None, tournament_id=tournament.id or 0, full_name="Игрок А")
    )
    player_b = tournament_service.save_player(
        Player(id=None, tournament_id=tournament.id or 0, full_name="Игрок Б")
    )
    match = match_service.create_match(
        tournament,
        player_a.id or 0,
        player_b.id or 0,
        stage="Финал",
        table_no="1",
        referee="",
        secretary="",
    )
    match_service.apply_event(match.id or 0, MatchCommand(EVENT_GOAL, actor_role="A"))

    cancelled = match_service.cancel_match(match.id or 0)

    assert cancelled.status == "cancelled"
    assert cancelled.current_set.score_a == 0
    assert cancelled.current_set.score_b == 0
    assert match_service.list_event_records(match.id or 0) == []


def test_players_are_sorted_by_rating_then_alphabetically():
    workspace = make_workspace("player_sorting")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Sorting Cup", event_date="2026-04-16")
    )
    tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Василий", rating=None))
    tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Алексей", rating=1350))
    tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Борис", rating=1500))
    tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Андрей", rating=None))

    players = tournament_service.list_players(tournament.id or 0)

    assert [player.full_name for player in players] == ["Борис", "Алексей", "Андрей", "Василий"]


def test_generate_group_stage_uses_rating_snake_and_tables():
    workspace = make_workspace("group_generation")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Groups Cup", event_date="2026-04-16", table_count=2)
    )
    for index in range(8):
        tournament_service.save_player(
            Player(
                id=None,
                tournament_id=tournament.id or 0,
                full_name=f"Игрок {index + 1}",
                rating=2000 - index * 10,
            )
        )

    created = tournament_service.generate_group_stage(tournament.id or 0)
    matches = match_service.list_matches(tournament.id or 0)

    assert created == 12
    assert len(matches) == 12
    assert matches[0].stage == "Группа A"
    assert matches[0].table_no in {"1", "2"}


def test_generate_group_stage_supports_straight_seeding_mode():
    workspace = make_workspace("group_generation_straight")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(
            id=None,
            name="Straight Cup",
            event_date="2026-04-16",
            table_count=2,
            seeding_mode="straight",
        )
    )
    for index in range(8):
        tournament_service.save_player(
            Player(
                id=None,
                tournament_id=tournament.id or 0,
                full_name=f"P{index + 1}",
                rating=2000 - index * 10,
            )
        )

    tournament_service.generate_group_stage(tournament.id or 0)
    matches = match_service.list_matches(tournament.id or 0)
    group_a_players = sorted(
        {
            player_id
            for match in matches
            if match.stage == "Группа A"
            for player_id in (match.player_a_id, match.player_b_id)
        }
    )
    players = tournament_service.list_players(tournament.id or 0)

    assert len(matches) == 12
    assert group_a_players == sorted(player.id or 0 for player in players[:4])


def test_round_robin_generation_creates_all_pairs():
    workspace = make_workspace("round_robin")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Round Robin Cup", event_date="2026-04-16", competition_mode="round_robin")
    )
    for index in range(4):
        tournament_service.save_player(
            Player(id=None, tournament_id=tournament.id or 0, full_name=f"Игрок {index + 1}", rating=1500 - index)
        )

    created = tournament_service.generate_group_stage(tournament.id or 0)
    matches = match_service.list_matches(tournament.id or 0)

    assert created == 6
    assert len(matches) == 6
    assert all(match.stage.startswith("Круговой этап") for match in matches)


def test_single_elimination_builds_next_round():
    workspace = make_workspace("single_elimination")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Knockout Cup", event_date="2026-04-16", competition_mode="single_elimination")
    )
    for index in range(4):
        tournament_service.save_player(
            Player(id=None, tournament_id=tournament.id or 0, full_name=f"Игрок {index + 1}", rating=1800 - index)
        )

    created = tournament_service.generate_group_stage(tournament.id or 0)
    playoff_matches = [match for match in match_service.list_matches(tournament.id or 0) if "Полуфинал" in match.stage]
    assert created == 2
    for match in match_service.list_matches(tournament.id or 0):
        match_service.record_match_result(match.id or 0, [(11, 5), (11, 6)], "A")

    next_created = tournament_service.generate_next_stage(tournament.id or 0)
    final_matches = [match for match in match_service.list_matches(tournament.id or 0) if match.stage == "Финал"]

    third_place_matches = [match for match in match_service.list_matches(tournament.id or 0) if "3" in match.stage]
    assert next_created == 2
    assert len(final_matches) == 1
    assert len(third_place_matches) == 1


def test_swiss_next_round_avoids_repeat_pairings():
    workspace = make_workspace("swiss")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Swiss Cup", event_date="2026-04-16", competition_mode="swiss")
    )
    for index in range(4):
        tournament_service.save_player(
            Player(id=None, tournament_id=tournament.id or 0, full_name=f"Игрок {index + 1}", rating=1700 - index)
        )

    tournament_service.generate_group_stage(tournament.id or 0)
    round_one = [match for match in match_service.list_matches(tournament.id or 0) if match.stage == "Швейцарка 1"]
    first_pairs = {tuple(sorted((match.player_a_id, match.player_b_id))) for match in round_one}
    for match in round_one:
        match_service.record_match_result(match.id or 0, [(11, 7), (11, 8)], "A")

    created = tournament_service.generate_next_stage(tournament.id or 0)
    playoff_matches = [match for match in match_service.list_matches(tournament.id or 0) if "Полуфинал" in match.stage]
    round_two = [match for match in match_service.list_matches(tournament.id or 0) if match.stage == "Швейцарка 2"]
    second_pairs = {tuple(sorted((match.player_a_id, match.player_b_id))) for match in round_two}

    assert created == 2
    assert first_pairs.isdisjoint(second_pairs)


def test_manual_result_keeps_set_starter_in_state_and_report():
    workspace = make_workspace("starter_report")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)
    report_service = ReportService(tournament_service, match_service)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Starter Cup", event_date="2026-04-16")
    )
    player_a = tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Иванов"))
    player_b = tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Сидоров"))
    match = match_service.create_match(
        tournament,
        player_a.id or 0,
        player_b.id or 0,
        stage="Финал",
        table_no="1",
        referee="",
        secretary="",
    )

    state = match_service.record_match_result(
        match.id or 0,
        [
            {"starter_role": "B", "starter_score": 11, "receiver_score": 3},
            {"starter_role": "A", "starter_score": 12, "receiver_score": 6},
            {"starter_role": "B", "starter_score": 11, "receiver_score": 8},
        ],
        "B",
    )
    report_path = report_service.generate_report(tournament.id or 0, paths.reports_dir, False)
    content = report_path.read_text(encoding="utf-8")

    assert state.sets[0].starter_role == "B"
    assert "начинал Сидоров" in content


def test_generate_next_stage_after_group_completion():
    workspace = make_workspace("next_stage")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Next Stage Cup", event_date="2026-04-16", table_count=2)
    )
    for index in range(8):
        tournament_service.save_player(
            Player(
                id=None,
                tournament_id=tournament.id or 0,
                full_name=f"Игрок {index + 1}",
                rating=1600 - index,
            )
        )

    tournament_service.generate_group_stage(tournament.id or 0)
    for match in match_service.list_matches(tournament.id or 0):
        winner_role = "A" if match.player_a_id < match.player_b_id else "B"
        match_service.record_match_result(
            match.id or 0,
            [(11, 5), (11, 7)],
            winner_role,
        )

    created = tournament_service.generate_next_stage(tournament.id or 0)
    playoff_matches = [match for match in match_service.list_matches(tournament.id or 0) if match.stage == "Полуфинал"]

    assert created == 2
    assert len(playoff_matches) == 2


def test_default_loss_is_counted_in_report_and_standings():
    workspace = make_workspace("default_loss_report")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)
    report_service = ReportService(tournament_service, match_service)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Default Cup", event_date="2026-04-16")
    )
    player_a = tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Игрок А"))
    player_b = tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Игрок Б"))
    match = match_service.create_match(
        tournament,
        player_a.id or 0,
        player_b.id or 0,
        stage="Финал",
        table_no="1",
        referee="",
        secretary="",
    )

    match_service.apply_event(match.id or 0, MatchCommand("default_loss", actor_role="A"))

    standings = report_service.build_standings(tournament.id or 0)
    assert standings[0].player_name == "Игрок Б"
    assert standings[0].sets_won == 2
    assert standings[0].points_won == 22

    report_path = report_service.generate_report(tournament.id or 0, paths.reports_dir, False)
    content = report_path.read_text(encoding="utf-8")
    assert "Игрок А - Игрок Б: 0:2." in content
    assert "Победитель: Игрок Б" in content


def test_single_elimination_with_ten_players_creates_preliminary_and_quarterfinals():
    workspace = make_workspace("single_elimination_ten")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Ten Cup", event_date="2026-04-16", competition_mode="single_elimination")
    )
    for index in range(10):
        tournament_service.save_player(
            Player(id=None, tournament_id=tournament.id or 0, full_name=f"Игрок {index + 1}", rating=2000 - index)
        )

    created = tournament_service.generate_group_stage(tournament.id or 0)
    first_round = match_service.list_matches(tournament.id or 0)

    assert created == 2
    assert all(match.stage == "Отборочный раунд" for match in first_round)
    pair_ids = {(match.player_a_id, match.player_b_id) for match in first_round}
    assert len(pair_ids) == 2

    for match in first_round:
        match_service.record_match_result(match.id or 0, [(11, 7), (11, 8)], "A")

    created_next = tournament_service.generate_next_stage(tournament.id or 0)
    second_round = match_service.list_matches(tournament.id or 0)

    assert created_next == 4
    assert all(match.stage == "Четвертьфинал" for match in second_round)


def test_group_generation_scales_to_forty_players_without_sparse_groups():
    workspace = make_workspace("group_generation_forty")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Forty Cup", event_date="2026-04-16", table_count=4)
    )
    for index in range(40):
        tournament_service.save_player(
            Player(
                id=None,
                tournament_id=tournament.id or 0,
                full_name=f"Игрок {index + 1}",
                rating=2400 - index,
                city=f"Город {(index % 10) + 1}",
            )
        )

    tournament_service.generate_group_stage(tournament.id or 0)
    matches = match_service.list_matches(tournament.id or 0)
    groups = {}
    for match in matches:
        groups.setdefault(match.stage, set()).update({match.player_a_id, match.player_b_id})

    assert len(groups) == 8
    assert all(len(players) == 5 for players in groups.values())


def test_group_generation_keeps_four_groups_for_seventeen_players():
    workspace = make_workspace("group_generation_seventeen")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Seventeen Cup", event_date="2026-04-16", table_count=4)
    )
    for index in range(17):
        tournament_service.save_player(
            Player(
                id=None,
                tournament_id=tournament.id or 0,
                full_name=f"Игрок {index + 1}",
                rating=2200 - index,
            )
        )

    tournament_service.generate_group_stage(tournament.id or 0)
    matches = match_service.list_matches(tournament.id or 0)
    groups = {}
    for match in matches:
        groups.setdefault(match.stage, set()).update({match.player_a_id, match.player_b_id})

    assert len(groups) == 4
    assert sorted(len(group_players) for group_players in groups.values()) == [4, 4, 4, 5]


def test_group_generation_uses_eight_groups_for_twenty_five_players():
    workspace = make_workspace("group_generation_twenty_five")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Twenty Five Cup", event_date="2026-04-16", table_count=4)
    )
    for index in range(25):
        tournament_service.save_player(
            Player(
                id=None,
                tournament_id=tournament.id or 0,
                full_name=f"Игрок {index + 1}",
                rating=2400 - index,
            )
        )

    tournament_service.generate_group_stage(tournament.id or 0)
    matches = match_service.list_matches(tournament.id or 0)
    groups = {}
    for match in matches:
        groups.setdefault(match.stage, set()).update({match.player_a_id, match.player_b_id})

    assert len(groups) == 8
    assert sorted(len(group_players) for group_players in groups.values()) == [3, 3, 3, 3, 3, 3, 3, 4]


def test_group_city_rebalance_avoids_duplicate_city_when_neighbor_swap_is_available():
    workspace = make_workspace("group_city_rebalance")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="City Cup", event_date="2026-04-16", table_count=2)
    )
    cities = ["Минск", "Рига", "Вильнюс", "Таллин", "Минск", "Каунас", "Гродно", "Брест"]
    for index, city in enumerate(cities):
        tournament_service.save_player(
            Player(
                id=None,
                tournament_id=tournament.id or 0,
                full_name=f"Игрок {index + 1}",
                rating=2000 - index,
                city=city,
            )
        )

    tournament_service.generate_group_stage(tournament.id or 0)
    matches = match_service.list_matches(tournament.id or 0)
    players_by_id = {player.id or 0: player for player in tournament_service.list_players(tournament.id or 0)}
    groups = {}
    for match in matches:
        groups.setdefault(match.stage, set()).update({match.player_a_id, match.player_b_id})

    for player_ids in groups.values():
        cities_in_group = [players_by_id[player_id].city for player_id in player_ids]
        assert len(cities_in_group) == len(set(cities_in_group))


def test_group_report_contains_points_and_final_table_is_grouped_by_places():
    workspace = make_workspace("group_report_places")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)
    report_service = ReportService(tournament_service, match_service)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Groups Report Cup", event_date="2026-04-16", table_count=2)
    )
    for index in range(8):
        tournament_service.save_player(
            Player(
                id=None,
                tournament_id=tournament.id or 0,
                full_name=f"Игрок {index + 1}",
                rating=2000 - index,
            )
        )

    tournament_service.generate_group_stage(tournament.id or 0)
    matches = match_service.list_matches(tournament.id or 0)
    for match in matches:
        if match.stage == "Группа A":
            winner_role = "A" if match.player_a_id < match.player_b_id else "B"
        else:
            winner_role = "A" if match.player_a_id > match.player_b_id else "B"
        set_scores = [(11, 8), (11, 9)] if winner_role == "A" else [(8, 11), (9, 11)]
        match_service.record_match_result(match.id or 0, set_scores, winner_role)

    rankings = tournament_service._group_rankings_with_stats(
        match_service.list_matches(tournament.id or 0),
        tournament.id or 0,
    )
    group_winners = {group_rankings[0].player_name for group_rankings in rankings.values()}
    group_runners_up = {group_rankings[1].player_name for group_rankings in rankings.values()}
    standings = report_service.build_standings(tournament.id or 0)

    assert {standing.player_name for standing in standings[: len(group_winners)]} == group_winners
    assert {
        standing.player_name for standing in standings[len(group_winners) : len(group_winners) + len(group_runners_up)]
    } == group_runners_up

    report_path = report_service.generate_report(tournament.id or 0, paths.reports_dir, False)
    content = report_path.read_text(encoding="utf-8")

    assert "ПРОМЕЖУТОЧНЫЕ РЕЗУЛЬТАТЫ ПО ГРУППАМ:" in content
    assert "Группа A:" in content
    assert "очков " in content
    assert "забито/пропущено" in content
    assert "разница" in content


def test_report_match_block_uses_compact_format_without_extra_result_line():
    workspace = make_workspace("compact_report")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)
    report_service = ReportService(tournament_service, match_service)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Compact Cup", event_date="2026-04-16")
    )
    player_a = tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Андрей"))
    player_b = tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name="Володя"))
    match = match_service.create_match(
        tournament,
        player_a.id or 0,
        player_b.id or 0,
        stage="Группа A",
        table_no="2",
        referee="",
        secretary="",
    )
    match_service.record_match_result(match.id or 0, [(11, 8), (11, 7)], "A")

    report_path = report_service.generate_report(tournament.id or 0, paths.reports_dir, False)
    content = report_path.read_text(encoding="utf-8")

    assert "Группа: A" in content
    assert "Андрей - Володя: 2:0." in content
    assert "Победитель: Андрей" in content
    assert "Результат по сетам:" not in content


def test_group_playoff_with_sixteen_players_builds_semifinals_after_quarterfinals():
    workspace = make_workspace("group_playoff_sixteen")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Sixteen Cup", event_date="2026-04-16", table_count=4)
    )
    for index in range(16):
        tournament_service.save_player(
            Player(
                id=None,
                tournament_id=tournament.id or 0,
                full_name=f"Игрок {index + 1}",
                rating=2200 - index,
            )
        )

    tournament_service.generate_group_stage(tournament.id or 0)
    group_matches = match_service.list_matches(tournament.id or 0)
    for match in group_matches:
        winner_role = "A" if match.player_a_id < match.player_b_id else "B"
        set_scores = [(11, 7), (11, 8)] if winner_role == "A" else [(7, 11), (8, 11)]
        match_service.record_match_result(match.id or 0, set_scores, winner_role)

    created_quarters = tournament_service.generate_next_stage(tournament.id or 0)
    quarterfinals = match_service.list_matches(tournament.id or 0)
    assert created_quarters == 4
    assert all(match.stage == "Четвертьфинал" for match in quarterfinals)

    for match in quarterfinals:
        winner_role = "A" if match.player_a_id < match.player_b_id else "B"
        set_scores = [(11, 6), (11, 7)] if winner_role == "A" else [(6, 11), (7, 11)]
        match_service.record_match_result(match.id or 0, set_scores, winner_role)

    created_semis = tournament_service.generate_next_stage(tournament.id or 0)
    semifinals = match_service.list_matches(tournament.id or 0)

    assert created_semis == 2
    assert all(match.stage == "Полуфинал" for match in semifinals)


def test_match_can_be_updated_and_deleted():
    workspace = make_workspace("update_delete_match")
    paths = build_paths(workspace)
    settings = AppSettings()
    settings.save(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)

    tournament = tournament_service.create_tournament(
        Tournament(id=None, name="Edit Cup", event_date="2026-04-16")
    )
    players = [
        tournament_service.save_player(Player(id=None, tournament_id=tournament.id or 0, full_name=f"Игрок {index}"))
        for index in range(1, 4)
    ]
    match = match_service.create_match(
        tournament,
        players[0].id or 0,
        players[1].id or 0,
        stage="Группа A",
        table_no="1",
        referee="",
        secretary="",
    )

    updated = match_service.update_match(
        match.id or 0,
        players[0].id or 0,
        players[2].id or 0,
        stage="Группа B",
        table_no="2",
        referee="Судья",
        secretary="Секретарь",
    )

    assert updated.stage == "Группа B"
    assert updated.table_no == "2"
    assert updated.player_b_id == players[2].id

    match_service.delete_match(match.id or 0)

    assert match_service.list_matches(tournament.id or 0) == []

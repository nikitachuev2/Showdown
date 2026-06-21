from __future__ import annotations

from dataclasses import dataclass

from showdown_app.application.services import MatchService, ReportService, TournamentService
from showdown_app.infrastructure.database import Database, configure_logging
from showdown_app.paths import AppPaths, ensure_app_paths
from showdown_app.settings import AppSettings


@dataclass
class AppContext:
    paths: AppPaths
    settings: AppSettings
    db: Database
    tournament_service: TournamentService
    match_service: MatchService
    report_service: ReportService


def build_context() -> AppContext:
    paths = ensure_app_paths()
    configure_logging(paths)
    settings = AppSettings.load(paths)
    db = Database(paths)
    tournament_service = TournamentService(db, paths, settings)
    match_service = MatchService(db, paths)
    report_service = ReportService(tournament_service, match_service)
    return AppContext(
        paths=paths,
        settings=settings,
        db=db,
        tournament_service=tournament_service,
        match_service=match_service,
        report_service=report_service,
    )

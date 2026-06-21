from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Dict

from showdown_app.paths import AppPaths


DEFAULT_HOTKEYS = {
    "new_tournament": "Ctrl+N",
    "open_tournament": "Ctrl+O",
    "announce_score": "F5",
}


@dataclass
class AppSettings:
    reports_path: str = "reports"
    include_event_details_in_report: bool = True
    hotkeys: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    show_author_signature: bool = True

    @classmethod
    def load(cls, paths: AppPaths) -> "AppSettings":
        if not paths.settings_file.exists():
            settings = cls()
            settings.save(paths)
            return settings
        payload = json.loads(paths.settings_file.read_text(encoding="utf-8"))
        settings = cls()
        settings.reports_path = payload.get("reports_path", settings.reports_path)
        settings.include_event_details_in_report = payload.get(
            "include_event_details_in_report",
            settings.include_event_details_in_report,
        )
        settings.hotkeys.update(payload.get("hotkeys", {}))
        settings.show_author_signature = payload.get(
            "show_author_signature",
            settings.show_author_signature,
        )
        return settings

    def save(self, paths: AppPaths) -> None:
        paths.settings_file.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

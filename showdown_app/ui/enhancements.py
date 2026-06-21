from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

import wx

import showdown_app.ui.app as ui_app
from showdown_app.domain.models import (
    EVENT_ERROR,
    EVENT_GOAL,
    Match,
    MatchCommand,
    Player,
    Tournament,
)
from showdown_app.settings import AppSettings


HOTKEY_DESCRIPTIONS: Dict[str, str] = {
    "new_tournament": "Создать новый турнир из главного окна или из окна открытого турнира.",
    "open_tournament": "Открыть список сохраненных турниров и выбрать нужный турнир.",
    "new_match": "Создать матч вручную на вкладке матчей турнира.",
    "save": "Сохранить изменения в текущем диалоге настроек.",
    "undo": "Отменить последнее действие в live-режиме матча.",
    "redo": "Повторить отмененное действие в live-режиме матча.",
    "announce_score": "Озвучить текущий счет или текущий контекст выбранной вкладки.",
    "focus_journal": "Перевести фокус в журнал действий live-матча.",
    "goal_a": "Добавить гол игроку A в live-режиме.",
    "goal_b": "Добавить гол игроку B в live-режиме.",
    "error_a": "Открыть меню ошибки для игрока A в live-режиме.",
    "error_b": "Открыть меню ошибки для игрока B в live-режиме.",
    "penalty_a": "Штраф игроку A в live-режиме.",
    "penalty_b": "Штраф игроку B в live-режиме.",
    "timeouts": "Открыть действия, связанные с тайм-аутами, в live-режиме.",
    "switch_sides": "Зафиксировать смену сторон в live-режиме.",
    "replay_serve": "Зафиксировать повторную подачу в live-режиме.",
    "lost_ball": "Зафиксировать потерю мяча в live-режиме.",
}

_MODIFIER_FLAGS = {
    "CTRL": wx.ACCEL_CTRL,
    "CONTROL": wx.ACCEL_CTRL,
    "SHIFT": wx.ACCEL_SHIFT,
    "ALT": wx.ACCEL_ALT,
}

_SPECIAL_KEYS = {
    "SPACE": ord(" "),
    "TAB": wx.WXK_TAB,
    "ENTER": wx.WXK_RETURN,
    "RETURN": wx.WXK_RETURN,
    "ESC": wx.WXK_ESCAPE,
    "ESCAPE": wx.WXK_ESCAPE,
    "DELETE": wx.WXK_DELETE,
    "BACKSPACE": wx.WXK_BACK,
}


def _announce_status(panel: wx.Window, text: str) -> None:
    if hasattr(panel, "selection_status") and getattr(panel, "selection_status", None):
        panel.selection_status.SetLabel(text)
        ui_app.set_accessible_name(panel.selection_status, text)
    ui_app.announce_action(panel, text)


def _reports_dir(panel: wx.Window) -> Path:
    reports_dir = Path(panel.context.settings.reports_path)
    if not reports_dir.is_absolute():
        reports_dir = panel.context.paths.root / reports_dir
    return reports_dir


def _parent_frame(panel: wx.Window) -> Optional[wx.Frame]:
    parent = panel.GetParent()
    if parent:
        parent = parent.GetParent()
    return parent if isinstance(parent, wx.Frame) else None


def _parse_hotkey(value: str) -> Optional[tuple[int, int]]:
    text = (value or "").strip()
    if not text:
        return None
    parts = [part.strip().upper() for part in text.replace(" ", "").split("+") if part.strip()]
    if not parts:
        return None
    flags = 0
    key_name = parts[-1]
    for modifier in parts[:-1]:
        flags |= _MODIFIER_FLAGS.get(modifier, 0)
    if key_name in _SPECIAL_KEYS:
        return flags, _SPECIAL_KEYS[key_name]
    if key_name.startswith("F") and key_name[1:].isdigit():
        number = int(key_name[1:])
        if 1 <= number <= 24:
            return flags, wx.WXK_F1 + (number - 1)
    if len(key_name) == 1:
        return flags, ord(key_name)
    return None


def _install_hotkeys(
    window: wx.Window,
    configured_hotkeys: Dict[str, str],
    bindings: List[tuple[str, Callable[[wx.CommandEvent], None]]],
) -> None:
    entries: List[tuple[int, int, int]] = []
    for action, handler in bindings:
        parsed = _parse_hotkey(configured_hotkeys.get(action, ""))
        if not parsed:
            continue
        flags, keycode = parsed
        command_id = int(wx.NewIdRef())
        entries.append((flags, keycode, command_id))
        window.Bind(wx.EVT_MENU, handler, id=command_id)
    if entries:
        window.SetAcceleratorTable(wx.AcceleratorTable(entries))


def _hotkeys_help_text(settings: AppSettings) -> str:
    lines = [
        "Поддерживаемый формат записи: Ctrl+N, Ctrl+Shift+Z, Alt+1, F5.",
        "Изменения применяются после сохранения настроек и используются окнами приложения.",
        "",
    ]
    for key, title in ui_app.HOTKEY_LABELS.items():
        description = HOTKEY_DESCRIPTIONS.get(key, "Действие без дополнительного описания.")
        value = settings.hotkeys.get(key, "")
        lines.append(f"{title}: {value}. {description}")
    return "\n".join(lines)


def _tab_switch_id(offset: int) -> int:
    return wx.ID_HIGHEST + 400 + offset


class EditMatchDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, match: Match, tournament: Tournament, players: List[Player]):
        super().__init__(parent, title="Редактировать матч", size=(560, 420))
        self.match = match
        self.tournament = tournament
        self.players = players
        self.player_by_name = {player.full_name: player for player in players}
        self._build_ui()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)
        names = [player.full_name for player in self.players]
        self.player_a = wx.Choice(panel, choices=names)
        self.player_b = wx.Choice(panel, choices=names)
        ui_app.bind_accessible_focus(self.player_a, "Игрок A")
        ui_app.bind_accessible_focus(self.player_b, "Игрок B")
        player_a_name = next((player.full_name for player in self.players if player.id == self.match.player_a_id), names[0] if names else "")
        player_b_name = next((player.full_name for player in self.players if player.id == self.match.player_b_id), names[1] if len(names) > 1 else names[0] if names else "")
        if player_a_name:
            self.player_a.SetStringSelection(player_a_name)
        if player_b_name:
            self.player_b.SetStringSelection(player_b_name)
        self.stage = wx.TextCtrl(panel, value=self.match.stage)
        self.table_no = wx.TextCtrl(panel, value=self.match.table_no)
        self.referee = wx.TextCtrl(panel, value=self.match.referee)
        self.secretary = wx.TextCtrl(panel, value=self.match.secretary)
        for label, control in [
            ("Игрок A", self.player_a),
            ("Игрок B", self.player_b),
            ("Стадия", self.stage),
            ("Номер стола", self.table_no),
            ("Судья", self.referee),
            ("Секретарь", self.secretary),
        ]:
            if isinstance(control, wx.TextCtrl):
                ui_app.bind_accessible_focus(control, label)
            form.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(control, 1, wx.EXPAND)
        root.Add(form, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        panel.SetSizer(root)
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.Add(panel, 1, wx.EXPAND)
        self.SetSizer(frame)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        if self.player_a.GetSelection() == self.player_b.GetSelection():
            ui_app.error_message(self, "Игрок A и игрок B не могут совпадать.")
            return
        self.EndModal(wx.ID_OK)

    def get_value(self) -> ui_app.MatchDraft:
        player_a = self.player_by_name[self.player_a.GetStringSelection()]
        player_b = self.player_by_name[self.player_b.GetStringSelection()]
        return ui_app.MatchDraft(
            player_a_id=player_a.id or 0,
            player_b_id=player_b.id or 0,
            stage=self.stage.GetValue().strip(),
            table_no=self.table_no.GetValue().strip(),
            referee=self.referee.GetValue().strip(),
            secretary=self.secretary.GetValue().strip(),
        )


class AccessibleTournamentPickerDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, context):
        super().__init__(parent, title="Открыть турнир", size=(760, 460))
        self.context = context
        self.selected_tournament: Optional[Tournament] = None
        self.tournament_ids: List[int] = []
        self.list_ctrl = wx.ListBox(self)
        self.status_text = wx.StaticText(self, label="Список турниров загружается")
        self.details_text = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_THEME)
        self.open_button = wx.Button(self, label="Открыть")
        self.cancel_button = wx.Button(self, label="Отмена")
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            self,
            label="Выберите турнир стрелками вверх и вниз, затем нажмите Enter или кнопку Открыть.",
        )
        intro.Wrap(700)
        root.Add(intro, 0, wx.ALL | wx.EXPAND, 12)

        ui_app.bind_accessible_focus(self.list_ctrl, "Список сохраненных турниров")
        self.list_ctrl.Bind(wx.EVT_LISTBOX, self.on_select_item)
        self.list_ctrl.Bind(wx.EVT_LISTBOX_DCLICK, self.on_activate)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_focus_list)
        root.Add(self.list_ctrl, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        ui_app.bind_accessible_focus(self.status_text, "Текущий турнир")
        root.Add(self.status_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        ui_app.bind_accessible_focus(self.details_text, "Подробности выбранного турнира")
        root.Add(self.details_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        ui_app.bind_accessible_focus(self.open_button, "Открыть выбранный турнир")
        self.open_button.Bind(wx.EVT_BUTTON, self.on_ok)
        buttons.Add(self.open_button, 0, wx.RIGHT, 8)
        ui_app.bind_accessible_focus(self.cancel_button, "Закрыть окно открытия турнира")
        self.cancel_button.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(wx.ID_CANCEL))
        buttons.Add(self.cancel_button, 0)
        root.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(root)
        wx.CallLater(150, self._focus_list)

    def _focus_list(self) -> None:
        self.list_ctrl.SetFocus()
        self._announce_selection()

    def _populate(self) -> None:
        tournaments = self.context.tournament_service.list_tournaments()
        self.list_ctrl.Clear()
        self.tournament_ids = []
        for tournament in tournaments:
            self.tournament_ids.append(tournament.id or 0)
            self.list_ctrl.Append(
                f"{tournament.name} | {tournament.event_date} | {tournament.location or 'Место не указано'}"
            )
        if tournaments:
            self.list_ctrl.SetSelection(0)
            self._announce_selection()
        else:
            self.status_text.SetLabel("Сохраненных турниров нет")
            self.details_text.SetValue("Список турниров пуст.")
            ui_app.set_accessible_name(self.list_ctrl, "Список турниров пуст")

    def _announce_selection(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        tournament = self.context.tournament_service.get_tournament(self.tournament_ids[index])
        current = self.list_ctrl.GetString(index)
        ui_app.set_accessible_name(self.list_ctrl, f"Список турниров. Текущий турнир: {tournament.name}")
        self.status_text.SetLabel(f"Выбран: {tournament.name}")
        ui_app.set_accessible_name(self.status_text, f"Выбран турнир: {tournament.name}")
        details = (
            f"Название: {tournament.name}\n"
            f"Дата: {tournament.event_date}\n"
            f"Место: {tournament.location or 'не указано'}\n"
            f"Система: {dict(ui_app.COMPETITION_MODES).get(tournament.competition_mode, tournament.competition_mode)}\n"
            f"Столов: {tournament.table_count}"
        )
        self.details_text.SetValue(details)
        ui_app.set_accessible_name(self.details_text, f"Подробности выбранного турнира: {current}")
        ui_app.announce_action(self, f"Выбран турнир {tournament.name}")

    def on_select_item(self, event: wx.CommandEvent) -> None:
        self._announce_selection()
        event.Skip()

    def on_focus_list(self, event: wx.FocusEvent) -> None:
        self._announce_selection()
        event.Skip()

    def on_activate(self, event: wx.CommandEvent) -> None:
        self.on_ok(event)

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            ui_app.error_message(self, "Выберите турнир.")
            return
        self.selected_tournament = self.context.tournament_service.get_tournament(self.tournament_ids[index])
        self.EndModal(wx.ID_OK)


class AccessibleTournamentDialog(ui_app.AccessibleTournamentDialog):
    def __init__(self, parent: wx.Window, tournament: Tournament):
        self.match_format_map = {label: value for value, label in ui_app.MATCH_FORMAT_CHOICES}
        super().__init__(parent, tournament)

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        content = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)

        self.name_ctrl = self._text_field(panel, form, "Название турнира", self.tournament.name)
        self.date_ctrl = self._text_field(panel, form, "Дата турнира", self.tournament.event_date or date.today().isoformat())
        self.location_ctrl = self._text_field(panel, form, "Место проведения", self.tournament.location)

        format_label = next((label for value, label in ui_app.TOURNAMENT_FORMATS if value == self.tournament.tournament_format), ui_app.TOURNAMENT_FORMATS[0][1])
        self.format_choice = wx.Choice(panel, choices=[label for _, label in ui_app.TOURNAMENT_FORMATS])
        self.format_choice.SetStringSelection(format_label)
        ui_app.bind_accessible_focus(self.format_choice, "Тип турнира")
        form.Add(wx.StaticText(panel, label="Тип турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.format_choice, 1, wx.EXPAND)

        competition_mode_label = next((label for value, label in ui_app.COMPETITION_MODES if value == self.tournament.competition_mode), ui_app.COMPETITION_MODES[0][1])
        self.competition_mode_choice = wx.Choice(panel, choices=[label for _, label in ui_app.COMPETITION_MODES])
        self.competition_mode_choice.SetStringSelection(competition_mode_label)
        ui_app.bind_accessible_focus(self.competition_mode_choice, "Система турнира")
        form.Add(wx.StaticText(panel, label="Система турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.competition_mode_choice, 1, wx.EXPAND)

        self.table_count_ctrl = self._text_field(panel, form, "Количество игровых столов", str(self.tournament.table_count or 1))

        match_format_label = next((label for value, label in ui_app.MATCH_FORMAT_CHOICES if value == self.tournament.match_format), ui_app.MATCH_FORMAT_CHOICES[0][1])
        self.match_format_choice = wx.Choice(panel, choices=[label for _, label in ui_app.MATCH_FORMAT_CHOICES])
        self.match_format_choice.SetStringSelection(match_format_label)
        ui_app.bind_accessible_focus(self.match_format_choice, "Формат матча")
        form.Add(wx.StaticText(panel, label="Формат матча"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.match_format_choice, 1, wx.EXPAND)

        self.match_duration_ctrl = self._text_field(panel, form, "Минут на матч", str(self.tournament.match_duration_minutes or 30))
        self.day_start_ctrl = self._text_field(panel, form, "Начало игрового дня", self.tournament.day_start_time or "09:00")

        self.lunch_enabled = wx.CheckBox(panel, label="Обеденный перерыв")
        self.lunch_enabled.SetValue(self.tournament.lunch_break_enabled)
        ui_app.bind_accessible_focus(self.lunch_enabled, self._lunch_checkbox_label())
        self.lunch_enabled.Bind(wx.EVT_CHECKBOX, self.on_toggle_lunch)
        form.Add(wx.StaticText(panel, label="Есть ли обед"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.lunch_enabled, 1, wx.EXPAND)

        self.lunch_panel = wx.Panel(panel)
        lunch_form = wx.FlexGridSizer(0, 2, 8, 8)
        lunch_form.AddGrowableCol(1, 1)
        self.lunch_start_ctrl = self._text_field(self.lunch_panel, lunch_form, "Начало обеда", self.tournament.lunch_start_time)
        self.lunch_end_ctrl = self._text_field(self.lunch_panel, lunch_form, "Конец обеда", self.tournament.lunch_end_time)
        self.lunch_panel.SetSizer(lunch_form)

        content.Add(form, 0, wx.EXPAND | wx.ALL, 12)
        content.Add(self.lunch_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        panel.SetSizer(content)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(panel, 1, wx.EXPAND)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self._update_lunch_visibility()
        ui_app.schedule_initial_focus(self.name_ctrl)

    def get_value(self) -> Tournament:
        tournament = super().get_value()
        tournament.seeding_mode = tournament.seeding_mode or "snake"
        tournament.match_format = self.match_format_map[self.match_format_choice.GetStringSelection()]
        return tournament


class AccessibleSettingsDialog(ui_app.SettingsDialog):
    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel_root = wx.BoxSizer(wx.VERTICAL)
        self.signature_check = wx.CheckBox(panel, label="Показывать визуальный информационный блок автора")
        self.signature_check.SetValue(self.settings.show_author_signature)
        ui_app.bind_accessible_focus(self.signature_check, "Показывать визуальный информационный блок автора")
        self.first_focus_control = self.signature_check
        panel_root.Add(self.signature_check, 0, wx.BOTTOM | wx.EXPAND, 12)

        hotkeys_title = wx.StaticText(panel, label="Горячие клавиши")
        panel_root.Add(hotkeys_title, 0, wx.BOTTOM, 8)

        help_label = wx.StaticText(
            panel,
            label="Каждое поле ниже задает сочетание клавиш для действия. После сохранения настройки применяются в окнах приложения.",
        )
        help_label.Wrap(620)
        panel_root.Add(help_label, 0, wx.BOTTOM | wx.EXPAND, 8)

        self.help_text = wx.TextCtrl(
            panel,
            value=_hotkeys_help_text(self.settings),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_THEME,
            size=(-1, 180),
        )
        ui_app.bind_accessible_focus(self.help_text, "Подробное описание горячих клавиш и поддерживаемых форматов")
        panel_root.Add(self.help_text, 0, wx.BOTTOM | wx.EXPAND, 12)

        hotkeys = wx.FlexGridSizer(0, 2, 6, 8)
        hotkeys.AddGrowableCol(1, 1)
        self.hotkey_fields = {}
        for key, value in self.settings.hotkeys.items():
            label_text = ui_app.HOTKEY_LABELS.get(key, key)
            description = HOTKEY_DESCRIPTIONS.get(key, "Действие без дополнительного описания.")
            label = wx.StaticText(panel, label=label_text)
            hotkeys.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            field = wx.TextCtrl(panel, value=value)
            ui_app.bind_accessible_focus(field, f"Горячая клавиша: {label_text}. {description}")
            hotkeys.Add(field, 1, wx.EXPAND)
            self.hotkey_fields[key] = field
        panel_root.Add(hotkeys, 1, wx.EXPAND)
        panel.SetSizer(panel_root)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(panel, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.TOP | wx.EXPAND, 12)
        self.SetSizer(root)
        if self.first_focus_control:
            wx.CallLater(150, self.first_focus_control.SetFocus)

    def get_value(self) -> AppSettings:
        settings = super().get_value()
        for key, ctrl in self.hotkey_fields.items():
            value = ctrl.GetValue().strip() or settings.hotkeys.get(key, "")
            settings.hotkeys[key] = value
        return settings


class AccessibleMainFrame(ui_app.AccessibleMainFrame):
    def _build_ui(self) -> None:
        super()._build_ui()
        if self.GetStatusBar() is None:
            self.CreateStatusBar()
        _install_hotkeys(
            self,
            self.context.settings.hotkeys,
            [
                ("new_tournament", self.on_new_tournament),
                ("open_tournament", self.on_open_tournament),
            ],
        )
        ui_app.announce_action(self, "Главное меню открыто. Доступны создание и открытие турнира.")

    def on_new_tournament(self, event: wx.CommandEvent) -> None:
        super().on_new_tournament(event)
        ui_app.announce_action(self, "Создан новый турнир.")

    def on_open_tournament(self, event: wx.CommandEvent) -> None:
        super().on_open_tournament(event)
        ui_app.announce_action(self, "Диалог открытия турнира закрыт.")

    def on_settings(self, event: wx.CommandEvent) -> None:
        super().on_settings(event)
        ui_app.announce_action(self, "Настройки закрыты.")


class AccessibleTournamentFrame(ui_app.TournamentFrame):
    def _build_ui(self) -> None:
        super()._build_ui()
        main_frame = self.GetParent()
        _install_hotkeys(
            self,
            self.context.settings.hotkeys,
            [
                ("new_tournament", getattr(main_frame, "on_new_tournament")),
                ("open_tournament", getattr(main_frame, "on_open_tournament")),
                ("announce_score", self.on_announce_current_context),
            ],
        )
        ui_app.announce_action(self, f"Турнир открыт: {self.tournament.name}")


class AccessibleMatchesPanel(ui_app.AccessibleMatchesPanel):
    def _set_status(self, text: str) -> None:
        super()._set_status(text)
        ui_app.announce_action(self, text)

    def on_add_match(self, event: wx.CommandEvent) -> None:
        super().on_add_match(event)
        self._set_status("Матч создан вручную.")

    def on_delete_match(self, event: wx.CommandEvent) -> None:
        before = self.selected_match_id()
        super().on_delete_match(event)
        after = self.selected_match_id()
        if before != after:
            self._set_status("Матч удален.")

    def on_open_match(self, event: wx.CommandEvent) -> None:
        super().on_open_match(event)
        self._set_status("Открыт live-режим выбранного матча.")


class TablesPanel(ui_app.TablesPanel):
    def _build_ui(self) -> None:
        super()._build_ui()
        self.list_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_table_key_navigation)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, accessible_label, handler in [
            ("Открыть матч", "Открыть выбранный матч из списка столов", self.on_open_match),
            ("Редактировать матч", "Редактировать выбранный матч из списка столов", self.on_edit_match),
            ("Удалить матч", "Удалить выбранный матч из списка столов", self.on_delete_match),
            ("Сохранить отчет", "Сохранить текстовый отчет по турниру", self.on_report),
        ]:
            button = wx.Button(self, label=label)
            ui_app.bind_accessible_focus(button, accessible_label)
            button.Bind(wx.EVT_BUTTON, handler)
            actions.Add(button, 0, wx.RIGHT, 8)
        self.GetSizer().Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.Layout()

    def focus_primary_control(self) -> None:
        self.list_ctrl.SetFocus()
        if self.list_ctrl.GetCount() > 0 and self.list_ctrl.GetSelection() == wx.NOT_FOUND:
            self.list_ctrl.SetSelection(0)
            self._announce_current_item()

    def _find_first_table_index(self, table_no: str) -> Optional[int]:
        for index in range(self.list_ctrl.GetCount()):
            text = self.list_ctrl.GetString(index)
            if text.startswith(f"Стол {table_no}") or f"Стол {table_no}" in text:
                return index
        return None

    def on_table_key_navigation(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if ord("0") <= code <= ord("9"):
            table_no = chr(code)
            if table_no == "0":
                table_no = "10"
            index = self._find_first_table_index(table_no)
            if index is not None:
                self.list_ctrl.SetSelection(index)
                self._announce_current_item()
                _announce_status(self, f"Переход к столу {table_no}.")
                return
        event.Skip()

    def on_open_match(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self._selected_match_id()
        if not match_id:
            ui_app.error_message(self, "Выберите строку с матчем.")
            return
        frame = ui_app.MatchScoringFrame(self, self.context, self.tournament, match_id)
        frame.Show()
        _announce_status(self, "Открыт live-режим выбранного матча.")

    def on_edit_match(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self._selected_match_id()
        if not match_id:
            ui_app.error_message(self, "Выберите строку с матчем.")
            return
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        match = self.context.match_service.get_match(match_id)
        dialog = EditMatchDialog(self, match, self.tournament, players)
        if dialog.ShowModal() == wx.ID_OK:
            data = dialog.get_value()
            self.context.match_service.update_match(match_id, data.player_a_id, data.player_b_id, data.stage, data.table_no, data.referee, data.secretary)
            frame = _parent_frame(self)
            if frame and hasattr(frame, "refresh_all"):
                frame.refresh_all()
            else:
                self.refresh()
            _announce_status(self, "Матч обновлен.")
        dialog.Destroy()

    def on_delete_match(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self._selected_match_id()
        if not match_id:
            ui_app.error_message(self, "Выберите строку с матчем.")
            return
        if not ui_app.confirm(self, "Удалить выбранный матч?"):
            return
        self.context.match_service.delete_match(match_id)
        frame = _parent_frame(self)
        if frame and hasattr(frame, "refresh_all"):
            frame.refresh_all()
        else:
            self.refresh()
        _announce_status(self, "Матч удален.")

    def on_report(self, event: wx.CommandEvent) -> None:
        del event
        target = self.context.report_service.generate_report(self.tournament.id or 0, _reports_dir(self), False)
        _announce_status(self, f"Отчет сохранен: {target.name}")

    def on_record_result(self, event: wx.CommandEvent) -> None:
        match_id = self._selected_match_id()
        super().on_record_result(event)
        if match_id:
            _announce_status(self, "Результат матча сохранен.")

    def on_refresh(self, event: wx.CommandEvent) -> None:
        super().on_refresh(event)
        _announce_status(self, "Список столов обновлен.")


class RoundsPanel(ui_app.RoundsPanel):
    def _build_ui(self) -> None:
        super()._build_ui()
        actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, accessible_label, handler in [
            ("Открыть матч", "Открыть выбранный матч из списка туров", self.on_open_match),
            ("Редактировать матч", "Редактировать выбранный матч из списка туров", self.on_edit_match),
            ("Удалить матч", "Удалить выбранный матч из списка туров", self.on_delete_match),
            ("Сохранить отчет", "Сохранить текстовый отчет по турниру", self.on_report),
        ]:
            button = wx.Button(self, label=label)
            ui_app.bind_accessible_focus(button, accessible_label)
            button.Bind(wx.EVT_BUTTON, handler)
            actions.Add(button, 0, wx.RIGHT, 8)
        self.GetSizer().Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.Layout()

    def focus_primary_control(self) -> None:
        self.list_ctrl.SetFocus()
        if self.list_ctrl.GetCount() > 0 and self.list_ctrl.GetSelection() == wx.NOT_FOUND:
            self.list_ctrl.SetSelection(0)
            self._announce_current_item()

    def on_open_match(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self._selected_match_id()
        if not match_id:
            ui_app.error_message(self, "Выберите матч.")
            return
        frame = ui_app.MatchScoringFrame(self, self.context, self.tournament, match_id)
        frame.Show()
        _announce_status(self, "Открыт live-режим выбранного матча.")

    def on_edit_match(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self._selected_match_id()
        if not match_id:
            ui_app.error_message(self, "Выберите матч.")
            return
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        match = self.context.match_service.get_match(match_id)
        dialog = EditMatchDialog(self, match, self.tournament, players)
        if dialog.ShowModal() == wx.ID_OK:
            data = dialog.get_value()
            self.context.match_service.update_match(match_id, data.player_a_id, data.player_b_id, data.stage, data.table_no, data.referee, data.secretary)
            frame = _parent_frame(self)
            if frame and hasattr(frame, "refresh_all"):
                frame.refresh_all()
            else:
                self.refresh()
            _announce_status(self, "Матч обновлен.")
        dialog.Destroy()

    def on_delete_match(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self._selected_match_id()
        if not match_id:
            ui_app.error_message(self, "Выберите матч.")
            return
        if not ui_app.confirm(self, "Удалить выбранный матч?"):
            return
        self.context.match_service.delete_match(match_id)
        frame = _parent_frame(self)
        if frame and hasattr(frame, "refresh_all"):
            frame.refresh_all()
        else:
            self.refresh()
        _announce_status(self, "Матч удален.")

    def on_report(self, event: wx.CommandEvent) -> None:
        del event
        target = self.context.report_service.generate_report(self.tournament.id or 0, _reports_dir(self), False)
        _announce_status(self, f"Отчет сохранен: {target.name}")

    def on_record_result(self, event: wx.CommandEvent) -> None:
        match_id = self._selected_match_id()
        super().on_record_result(event)
        if match_id:
            _announce_status(self, "Результат матча сохранен.")

    def on_refresh(self, event: wx.CommandEvent) -> None:
        super().on_refresh(event)
        _announce_status(self, "Список туров обновлен.")


class AccessibleMatchScoringFrame(ui_app.MatchScoringFrame):
    def _bind_hotkeys(self) -> None:
        bindings: List[tuple[str, Callable[[wx.CommandEvent], None]]] = [
            ("goal_a", lambda evt: self.apply(MatchCommand(EVENT_GOAL, actor_role="A"))),
            ("goal_b", lambda evt: self.apply(MatchCommand(EVENT_GOAL, actor_role="B"))),
            ("error_a", lambda evt: self.open_error_menu("A")),
            ("error_b", lambda evt: self.open_error_menu("B")),
            ("undo", self.on_undo),
            ("redo", self.on_redo),
            ("announce_score", self.on_announce_score),
            ("focus_journal", lambda evt: self.journal.SetFocus()),
        ]
        _install_hotkeys(self, self.context.settings.hotkeys, bindings)

    def on_announce_score(self, event: wx.CommandEvent) -> None:
        super().on_announce_score(event)
        announcement = self.live_status.GetLabel().strip()
        if announcement:
            ui_app.announce_action(self, announcement)


class AccessibleTournamentPickerDialog(AccessibleTournamentPickerDialog):
    def _build_ui(self) -> None:
        super()._build_ui()
        self.list_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_key_navigation)
        self.open_button.SetDefault()

    def on_key_navigation(self, event: wx.KeyEvent) -> None:
        key_code = event.GetKeyCode()
        if key_code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_ok(wx.CommandEvent())
            return
        if key_code == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()


class AccessibleMainFrame(ui_app.AccessibleMainFrame):
    def _build_ui(self) -> None:
        super()._build_ui()
        if self.GetStatusBar() is None:
            self.CreateStatusBar()
        _install_hotkeys(
            self,
            self.context.settings.hotkeys,
            [
                ("new_tournament", self.on_new_tournament),
                ("open_tournament", self.on_open_tournament),
            ],
        )
        ui_app.announce_action(self, "Главное меню открыто. Доступны создание и открытие турнира.")

    def on_new_tournament(self, event: wx.CommandEvent) -> None:
        super().on_new_tournament(event)
        ui_app.announce_action(self, "Создан новый турнир.")

    def on_open_tournament(self, event: wx.CommandEvent) -> None:
        del event
        dialog = ui_app.TournamentPickerDialog(self, self.context)
        if dialog.ShowModal() == wx.ID_OK and dialog.selected_tournament:
            tournament = dialog.selected_tournament
            self.open_tournament_frame(tournament)
            ui_app.announce_action(self, f"Открыт турнир {tournament.name}.")
        else:
            ui_app.announce_action(self, "Открытие турнира отменено.")
        dialog.Destroy()

    def on_settings(self, event: wx.CommandEvent) -> None:
        super().on_settings(event)
        ui_app.announce_action(self, "Настройки закрыты.")


class AccessibleTournamentFrame(ui_app.TournamentFrame):
    def _build_ui(self) -> None:
        super()._build_ui()
        main_frame = self.GetParent()
        _install_hotkeys(
            self,
            self.context.settings.hotkeys,
            [
                ("new_tournament", getattr(main_frame, "on_new_tournament")),
                ("open_tournament", getattr(main_frame, "on_open_tournament")),
                ("announce_score", self.on_announce_current_context),
            ],
        )
        self._install_tab_shortcuts()
        self.Bind(wx.EVT_CHAR_HOOK, self.on_frame_key_navigation)
        ui_app.announce_action(self, f"Турнир открыт: {self.tournament.name}")

    def _install_tab_shortcuts(self) -> None:
        for offset, key in enumerate((ord("1"), ord("2"), ord("3"), ord("4")), start=1):
            command_id = _tab_switch_id(offset)
            self.Bind(wx.EVT_MENU, lambda event, index=offset - 1: self._activate_tab(index), id=command_id)

    def _activate_tab(self, index: int) -> None:
        if not self.notebook:
            return
        if index < 0 or index >= self.notebook.GetPageCount():
            return
        self.notebook.SetSelection(index)
        self._announce_current_tab()
        self._focus_current_page()

    def _focus_current_page(self) -> None:
        if not self.notebook:
            return
        page = self.notebook.GetCurrentPage()
        if page is None:
            return
        focus_method = getattr(page, "focus_primary_control", None)
        if callable(focus_method):
            wx.CallAfter(focus_method)
            return
        list_ctrl = getattr(page, "list_ctrl", None)
        if list_ctrl is not None:
            wx.CallAfter(list_ctrl.SetFocus)

    def on_frame_key_navigation(self, event: wx.KeyEvent) -> None:
        if not self.notebook:
            event.Skip()
            return
        key_code = event.GetKeyCode()
        if event.ControlDown() and key_code == wx.WXK_TAB:
            page_count = self.notebook.GetPageCount()
            if page_count:
                direction = -1 if event.ShiftDown() else 1
                self._activate_tab((self.notebook.GetSelection() + direction) % page_count)
                return
        if event.ControlDown() and ord("1") <= key_code <= ord("4"):
            self._activate_tab(key_code - ord("1"))
            return
        if event.AltDown() and key_code in (wx.WXK_LEFT, wx.WXK_RIGHT):
            page_count = self.notebook.GetPageCount()
            if page_count:
                direction = -1 if key_code == wx.WXK_LEFT else 1
                self._activate_tab((self.notebook.GetSelection() + direction) % page_count)
                return
        event.Skip()

    def on_change_tab(self, event: wx.BookCtrlEvent) -> None:
        self._announce_current_tab()
        self._focus_current_page()
        event.Skip()

    def on_announce_current_context(self, event: wx.CommandEvent) -> None:
        del event
        self._announce_current_tab()
        self._focus_current_page()

    def _announce_current_tab(self) -> None:
        if not self.notebook:
            return
        index = self.notebook.GetSelection()
        if index == wx.NOT_FOUND:
            return
        tab_name = self.notebook.GetPageText(index)
        page = self.notebook.GetCurrentPage()
        ui_app.set_accessible_name(self.notebook, f"Вкладка турнира {index + 1}: {tab_name}")
        self.SetStatusText(f"Вкладка: {tab_name}. Ctrl+Tab, Ctrl+1..4, Alt+влево/вправо.")
        ui_app.announce_action(self, f"Вкладка {tab_name}.")
        if page is None:
            return
        for method_name in ("_announce_current_item", "_announce_selected_match", "_announce_selected_player"):
            method = getattr(page, method_name, None)
            if callable(method):
                method()
                return


ui_app.EditMatchDialog = EditMatchDialog
ui_app.TournamentPickerDialog = AccessibleTournamentPickerDialog
ui_app.AccessibleTournamentDialog = AccessibleTournamentDialog
ui_app.SettingsDialog = AccessibleSettingsDialog
ui_app.AccessibleMainFrame = AccessibleMainFrame
ui_app.TournamentFrame = AccessibleTournamentFrame
ui_app.AccessibleMatchesPanel = AccessibleMatchesPanel
ui_app.TablesPanel = TablesPanel
ui_app.RoundsPanel = RoundsPanel
ui_app.MatchScoringFrame = AccessibleMatchScoringFrame


def _message(parent: wx.Window, text: str, caption: str = "ShowdownApp") -> None:
    ui_app.announce_action(parent, text)
    wx.MessageBox(text, caption, wx.OK | wx.ICON_INFORMATION, parent)


def _error_message(parent: wx.Window, text: str) -> None:
    ui_app.announce_action(parent, text, beep=True)
    wx.MessageBox(text, "Ошибка", wx.OK | wx.ICON_ERROR, parent)


def _confirm(parent: wx.Window, text: str, caption: str = "Подтверждение") -> bool:
    ui_app.announce_action(parent, text)
    return wx.MessageBox(text, caption, wx.YES_NO | wx.ICON_QUESTION, parent) == wx.YES


ui_app.message = _message
ui_app.error_message = _error_message
ui_app.confirm = _confirm


class StableTournamentPickerDialog(AccessibleTournamentPickerDialog):
    def _build_ui(self) -> None:
        super()._build_ui()
        self.list_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_key_navigation)
        self.open_button.SetDefault()
        refresh_button = wx.Button(self, label="Обновить список")
        ui_app.bind_accessible_focus(refresh_button, "Обновить список турниров")
        refresh_button.Bind(wx.EVT_BUTTON, self.on_refresh_list)
        buttons_sizer = self.GetSizer().GetItemCount() - 1
        button_row = self.GetSizer().GetItem(buttons_sizer).GetSizer()
        button_row.Insert(1, refresh_button, 0, wx.RIGHT, 8)
        self.Bind(wx.EVT_SHOW, self.on_dialog_show)

    def on_key_navigation(self, event: wx.KeyEvent) -> None:
        key_code = event.GetKeyCode()
        if key_code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_ok(wx.CommandEvent())
            return
        if key_code == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()

    def on_dialog_show(self, event: wx.ShowEvent) -> None:
        if event.IsShown():
            self._populate()
        event.Skip()

    def _focus_list(self) -> None:
        self._populate()
        self.list_ctrl.SetFocus()
        self._announce_selection()

    def on_refresh_list(self, event: wx.CommandEvent) -> None:
        del event
        self._populate()
        ui_app.announce_action(self, "Список турниров обновлен.")


class StableAccessibleMainFrame(ui_app.MainFrame):
    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            panel,
            label="Приложение для ведения турниров по Showdown и внесения результатов в доступном для скринридера виде.",
        )
        intro.Wrap(680)
        intro.SetFont(wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        ui_app.clear_accessibility(intro)
        root.Add(intro, 0, wx.ALL | wx.EXPAND, 18)

        buttons = [
            ("Создать новый турнир", self.on_new_tournament),
            ("Открыть турнир", self.on_open_tournament),
            ("Настройки", self.on_settings),
            ("Выход", self.on_exit),
        ]
        for label, handler in buttons:
            button = wx.Button(panel, label=label)
            ui_app.bind_accessible_focus(button, label)
            button.Bind(wx.EVT_BUTTON, handler)
            if self.primary_button is None:
                self.primary_button = button
            root.Add(button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 18)

        signature = ui_app.SignaturePanel(panel, self.context.settings)
        root.AddStretchSpacer()
        root.Add(signature, 1, wx.EXPAND)
        panel.SetSizer(root)
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        accel = wx.AcceleratorTable([(wx.ACCEL_CTRL, ord("N"), wx.ID_NEW), (wx.ACCEL_CTRL, ord("O"), wx.ID_OPEN)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, self.on_new_tournament, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.on_open_tournament, id=wx.ID_OPEN)
        if self.GetStatusBar() is None:
            self.CreateStatusBar()
        self.SetStatusText("Главное меню. Доступны создание и открытие турнира.")

    def on_new_tournament(self, event: wx.CommandEvent) -> None:
        del event
        dialog = ui_app.AccessibleTournamentDialog(self, ui_app.default_tournament())
        if dialog.ShowModal() == wx.ID_OK:
            tournament = self.context.tournament_service.create_tournament(dialog.get_value())
            self.SetStatusText("Турнир создан успешно. Перейдите в Открыть турнир для его проведения.")
            ui_app.message(self, f"Турнир создан успешно: {tournament.name}. Перейдите в Открыть турнир для его проведения.")
            if self.primary_button:
                self.primary_button.SetFocus()
        dialog.Destroy()

    def on_open_tournament(self, event: wx.CommandEvent) -> None:
        del event
        dialog = ui_app.TournamentPickerDialog(self, self.context)
        if dialog.ShowModal() == wx.ID_OK and dialog.selected_tournament:
            tournament = dialog.selected_tournament
            self.open_tournament_frame(tournament)
            ui_app.announce_action(self, f"Открыт турнир {tournament.name}.")
        else:
            ui_app.announce_action(self, "Открытие турнира отменено.")
        dialog.Destroy()

    def on_settings(self, event: wx.CommandEvent) -> None:
        super().on_settings(event)
        ui_app.announce_action(self, "Окно настроек закрыто.")


class StableAccessibleMatchesPanel(ui_app.AccessibleMatchesPanel):
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)

        options_row = wx.BoxSizer(wx.HORIZONTAL)
        seeding_label = wx.StaticText(self, label="Способ посева")
        ui_app.clear_accessibility(seeding_label)
        options_row.Add(seeding_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.seeding_choice = wx.Choice(self, choices=[label for _, label in ui_app.SEEDING_MODES])
        ui_app.bind_accessible_focus(self.seeding_choice, "Способ посева для автоматического формирования матчей")
        self.seeding_choice.Bind(wx.EVT_CHOICE, self.on_change_seeding_mode)
        options_row.Add(self.seeding_choice, 0)
        root.Add(options_row, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 12)

        ui_app.bind_accessible_focus(self.list_ctrl, "Список матчей")
        self.list_ctrl.Bind(wx.EVT_CHOICE, self.on_select_match)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_list_focus)
        self.list_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_list_key_navigation)
        root.Add(self.list_ctrl, 0, wx.ALL | wx.EXPAND, 12)

        self.selection_status = wx.StaticText(self, label="Матчи не созданы")
        ui_app.bind_accessible_focus(self.selection_status, "Текущий матч")
        root.Add(self.selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.selection_details = wx.TextCtrl(
            self,
            value="",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE,
        )
        ui_app.bind_accessible_focus(self.selection_details, "Подробности выбранного матча")
        root.Add(self.selection_details, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        buttons = wx.GridSizer(0, 4, 8, 8)
        for label, accessible_label, handler in [
            ("Сформировать матчи", "Сформировать матчи автоматически", self.on_generate_matches),
            ("Следующий этап", "Сформировать следующий этап", self.on_generate_next_stage),
            ("Добавить матч", "Добавить матч вручную", self.on_add_match),
            ("Внести результат", "Внести итоговый результат выбранного матча", self.on_record_result),
            ("Сохранить отчет", "Сохранить текстовый отчет по турниру", self.on_report),
            ("Удалить матч", "Удалить выбранный матч", self.on_delete_match),
            ("Обновить список", "Обновить список матчей", self.on_refresh),
        ]:
            button = wx.Button(self, label=label)
            ui_app.bind_accessible_focus(button, accessible_label)
            button.Bind(wx.EVT_BUTTON, handler)
            if self.primary_button is None:
                self.primary_button = button
            buttons.Add(button, 0, wx.EXPAND)
        root.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.SetSizer(root)

    def focus_primary_control(self) -> None:
        self.list_ctrl.SetFocus()
        if self.list_ctrl.GetCount() > 0 and self.list_ctrl.GetSelection() == wx.NOT_FOUND:
            self.list_ctrl.SetSelection(0)
            self._announce_selected_match()

    def on_list_key_navigation(self, event: wx.KeyEvent) -> None:
        key_code = event.GetKeyCode()
        if key_code == wx.WXK_DELETE:
            self.on_delete_match(wx.CommandEvent())
            return
        event.Skip()


class StableTablesPanel(ui_app.TablesPanel):
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        top = wx.BoxSizer(wx.HORIZONTAL)
        label = wx.StaticText(self, label="Вид списка")
        ui_app.clear_accessibility(label)
        top.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.view_choice = wx.Choice(self, choices=["По столам", "По группам"])
        self.view_choice.SetSelection(0)
        ui_app.bind_accessible_focus(self.view_choice, "Вид списка столов")
        self.view_choice.Bind(wx.EVT_CHOICE, lambda event: self.refresh())
        top.Add(self.view_choice, 0)
        schedule_button = wx.Button(self, label="Настроить время")
        ui_app.bind_accessible_focus(schedule_button, "Настроить время матчей и обеденный перерыв")
        schedule_button.Bind(wx.EVT_BUTTON, self.on_edit_schedule)
        top.Add(schedule_button, 0, wx.LEFT, 8)
        root.Add(top, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)

        ui_app.bind_accessible_focus(self.list_ctrl, "Список столов")
        root.Add(self.list_ctrl, 1, wx.ALL | wx.EXPAND, 12)
        self.selection_status = wx.StaticText(self, label="")
        ui_app.bind_accessible_focus(self.selection_status, "Текущий пункт списка столов")
        root.Add(self.selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.selection_details = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE)
        ui_app.bind_accessible_focus(self.selection_details, "Подробности выбранного пункта списка столов")
        root.Add(self.selection_details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        result_button = wx.Button(self, label="Внести результат")
        ui_app.bind_accessible_focus(result_button, "Внести итоговый результат выбранного матча из списка столов")
        result_button.Bind(wx.EVT_BUTTON, self.on_record_result)
        actions.Add(result_button, 0, wx.RIGHT, 8)
        refresh_button = wx.Button(self, label="Обновить список")
        ui_app.bind_accessible_focus(refresh_button, "Обновить список столов")
        refresh_button.Bind(wx.EVT_BUTTON, self.on_refresh)
        actions.Add(refresh_button, 0)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(root)

        self.list_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_extra_key_navigation)
        self.list_ctrl.Bind(wx.EVT_LISTBOX, self.on_select_item)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_focus_list)

    def focus_primary_control(self) -> None:
        self.list_ctrl.SetFocus()
        if self.list_ctrl.GetCount() > 0 and self.list_ctrl.GetSelection() == wx.NOT_FOUND:
            self.list_ctrl.SetSelection(0)
            self._announce_current_item()

    def on_extra_key_navigation(self, event: wx.KeyEvent) -> None:
        key_code = event.GetKeyCode()
        if key_code == wx.WXK_F5:
            index = self.list_ctrl.GetSelection()
            if index != wx.NOT_FOUND:
                current = self.list_ctrl.GetString(index)
                self._announce_current_item()
                ui_app.announce_action(self, current)
            return
        if ord("0") <= key_code <= ord("9") and self.view_choice and self.view_choice.GetSelection() == 0:
            self._table_jump_buffer += chr(key_code)
            if self._table_jump_reset:
                self._table_jump_reset.Stop()
            self._table_jump_reset = wx.CallLater(1200, self._reset_table_jump_buffer)
            for index in range(self.list_ctrl.GetCount()):
                line = self.list_ctrl.GetString(index)
                parts = [part for part in line.replace("-", " ").split() if part.isdigit()]
                if parts and parts[0] == self._table_jump_buffer:
                    self.list_ctrl.SetSelection(index)
                    self._announce_current_item()
                    ui_app.announce_action(self, f"Переход к столу {self._table_jump_buffer}.")
                    return
            return
        event.Skip()

    def _reset_table_jump_buffer(self) -> None:
        self._table_jump_buffer = ""


class StableRoundsPanel(ui_app.RoundsPanel):
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        ui_app.bind_accessible_focus(self.list_ctrl, "Список туров")
        root.Add(self.list_ctrl, 1, wx.ALL | wx.EXPAND, 12)
        self.selection_status = wx.StaticText(self, label="")
        ui_app.bind_accessible_focus(self.selection_status, "Текущий пункт списка туров")
        root.Add(self.selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.selection_details = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE)
        ui_app.bind_accessible_focus(self.selection_details, "Подробности выбранного пункта списка туров")
        root.Add(self.selection_details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        result_button = wx.Button(self, label="Внести результат")
        ui_app.bind_accessible_focus(result_button, "Внести итоговый результат для выбранного матча из списка туров")
        result_button.Bind(wx.EVT_BUTTON, self.on_record_result)
        actions.Add(result_button, 0, wx.RIGHT, 8)
        refresh_button = wx.Button(self, label="Обновить список")
        ui_app.bind_accessible_focus(refresh_button, "Обновить список туров")
        refresh_button.Bind(wx.EVT_BUTTON, self.on_refresh)
        actions.Add(refresh_button, 0)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(root)

        self.list_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_extra_key_navigation)
        self.list_ctrl.Bind(wx.EVT_LISTBOX, self.on_select_item)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_focus_list)

    def focus_primary_control(self) -> None:
        self.list_ctrl.SetFocus()
        if self.list_ctrl.GetCount() > 0 and self.list_ctrl.GetSelection() == wx.NOT_FOUND:
            self.list_ctrl.SetSelection(0)
            self._announce_current_item()

    def on_extra_key_navigation(self, event: wx.KeyEvent) -> None:
        event.Skip()


class StableTournamentFrame(ui_app.TournamentFrame):
    def _build_ui(self) -> None:
        self.notebook = wx.Notebook(self)
        ui_app.bind_accessible_focus(self.notebook, "Вкладки турнира: участники, матчи, столы, туры")

        self.players_panel = ui_app.AccessiblePlayersPanel(self.notebook, self.context, self.tournament)
        self.matches_panel = ui_app.AccessibleMatchesPanel(self.notebook, self.context, self.tournament, self.players_panel)
        self.tables_panel = ui_app.TablesPanel(self.notebook, self.context, self.tournament)
        self.rounds_panel = ui_app.RoundsPanel(self.notebook, self.context, self.tournament)

        ui_app.set_accessible_name(self.players_panel, "Вкладка участников турнира")
        ui_app.set_accessible_name(self.matches_panel, "Вкладка матчей турнира")
        ui_app.set_accessible_name(self.tables_panel, "Вкладка списка столов")
        ui_app.set_accessible_name(self.rounds_panel, "Вкладка списка туров")

        self.notebook.AddPage(self.players_panel, "Список игроков")
        self.notebook.AddPage(self.matches_panel, "Список матчей")
        self.notebook.AddPage(self.tables_panel, "Список столов")
        self.notebook.AddPage(self.rounds_panel, "Список туров")

        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(self.notebook, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        main_frame = self.GetParent()
        _install_hotkeys(
            self,
            self.context.settings.hotkeys,
            [
                ("new_tournament", getattr(main_frame, "on_new_tournament")),
                ("open_tournament", getattr(main_frame, "on_open_tournament")),
                ("announce_score", self.on_announce_current_context),
            ],
        )
        self.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_change_tab)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_frame_key_navigation)
        if self.GetStatusBar() is None:
            self.CreateStatusBar()
        self.SetStatusText(f"Турнир открыт: {self.tournament.name}. Вкладок: 4.")
        wx.CallAfter(self._focus_tabs)

    def _focus_tabs(self) -> None:
        if self.notebook:
            self.notebook.SetFocus()
            self._announce_current_tab()

    def on_frame_key_navigation(self, event: wx.KeyEvent) -> None:
        if not self.notebook:
            event.Skip()
            return
        key_code = event.GetKeyCode()
        page_count = self.notebook.GetPageCount()
        if event.ControlDown() and key_code == wx.WXK_TAB and page_count:
            direction = -1 if event.ShiftDown() else 1
            self._activate_tab((self.notebook.GetSelection() + direction) % page_count)
            return
        if event.ControlDown() and ord("1") <= key_code <= ord("4"):
            self._activate_tab(key_code - ord("1"))
            return
        if event.AltDown() and key_code in (wx.WXK_LEFT, wx.WXK_RIGHT) and page_count:
            direction = -1 if key_code == wx.WXK_LEFT else 1
            self._activate_tab((self.notebook.GetSelection() + direction) % page_count)
            return
        event.Skip()

    def _activate_tab(self, index: int) -> None:
        if not self.notebook:
            return
        if index < 0 or index >= self.notebook.GetPageCount():
            return
        self.notebook.SetSelection(index)
        self._announce_current_tab()
        self._focus_current_page()

    def _focus_current_page(self) -> None:
        if not self.notebook:
            return
        page = self.notebook.GetCurrentPage()
        if page is None:
            return
        focus_method = getattr(page, "focus_primary_control", None)
        if callable(focus_method):
            wx.CallAfter(focus_method)
            return
        list_ctrl = getattr(page, "list_ctrl", None)
        if list_ctrl is not None:
            wx.CallAfter(list_ctrl.SetFocus)

    def on_change_tab(self, event: wx.BookCtrlEvent) -> None:
        self._announce_current_tab()
        event.Skip()

    def on_announce_current_context(self, event: wx.CommandEvent) -> None:
        del event
        self._announce_current_tab()

    def _announce_current_tab(self) -> None:
        if not self.notebook:
            return
        index = self.notebook.GetSelection()
        if index == wx.NOT_FOUND:
            return
        tab_name = self.notebook.GetPageText(index)
        ui_app.set_accessible_name(self.notebook, f"Вкладка турнира {index + 1} из {self.notebook.GetPageCount()}: {tab_name}")
        self.SetStatusText(f"Вкладка: {tab_name}. Используйте Tab, стрелки, Ctrl+Tab или Alt+влево/вправо.")
        ui_app.announce_action(self, f"Вкладка {tab_name}.")


VISIBLE_SETTINGS_KEYS = [
    "new_tournament",
    "open_tournament",
    "announce_score",
]


class StableSettingsDialog(ui_app.SettingsDialog):
    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel_root = wx.BoxSizer(wx.VERTICAL)
        self.signature_check = wx.CheckBox(panel, label="Показывать визуальный информационный блок автора")
        self.signature_check.SetValue(self.settings.show_author_signature)
        ui_app.bind_accessible_focus(self.signature_check, "Показывать визуальный информационный блок автора")
        self.first_focus_control = self.signature_check
        panel_root.Add(self.signature_check, 0, wx.BOTTOM | wx.EXPAND, 12)

        hotkeys_title = wx.StaticText(panel, label="Горячие клавиши")
        panel_root.Add(hotkeys_title, 0, wx.BOTTOM, 8)
        help_label = wx.StaticText(panel, label="Показаны только горячие клавиши для основных экранов без live-режима.")
        help_label.Wrap(620)
        panel_root.Add(help_label, 0, wx.BOTTOM | wx.EXPAND, 8)

        hotkeys = wx.FlexGridSizer(0, 2, 6, 8)
        hotkeys.AddGrowableCol(1, 1)
        self.hotkey_fields = {}
        for key in VISIBLE_SETTINGS_KEYS:
            label_text = ui_app.HOTKEY_LABELS.get(key, key)
            label = wx.StaticText(panel, label=label_text)
            hotkeys.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            field = wx.TextCtrl(panel, value=self.settings.hotkeys.get(key, ""))
            ui_app.bind_accessible_focus(field, f"Горячая клавиша: {label_text}")
            hotkeys.Add(field, 1, wx.EXPAND)
            self.hotkey_fields[key] = field
        panel_root.Add(hotkeys, 1, wx.EXPAND)
        panel.SetSizer(panel_root)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(panel, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.TOP | wx.EXPAND, 12)
        self.SetSizer(root)
        if self.first_focus_control:
            wx.CallLater(150, self.first_focus_control.SetFocus)

    def get_value(self) -> AppSettings:
        settings = super().get_value()
        settings.hotkeys = {key: settings.hotkeys.get(key, "") for key in VISIBLE_SETTINGS_KEYS}
        for key, ctrl in self.hotkey_fields.items():
            settings.hotkeys[key] = ctrl.GetValue().strip() or settings.hotkeys.get(key, "")
        return settings


ui_app.TournamentPickerDialog = StableTournamentPickerDialog
ui_app.AccessibleMainFrame = StableAccessibleMainFrame
ui_app.TournamentFrame = StableTournamentFrame
ui_app.AccessibleMatchesPanel = StableAccessibleMatchesPanel
ui_app.TablesPanel = StableTablesPanel
ui_app.RoundsPanel = StableRoundsPanel
ui_app.SettingsDialog = StableSettingsDialog


def _competition_label(value: str) -> str:
    return dict(ui_app.COMPETITION_MODES).get(value, value)


def _format_label(value: str) -> str:
    return dict(ui_app.TOURNAMENT_FORMATS).get(value, value)


def _player_brief(player: Player) -> str:
    city = (player.city or "").strip()
    return f"{player.full_name}, {city}" if city else player.full_name


class ScreenReaderMessageDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, title: str, message: str):
        super().__init__(parent, title=title, size=(620, 240))
        self.message_text = wx.TextCtrl(
            self,
            value=message,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_THEME,
        )
        ok_button = wx.Button(self, wx.ID_OK, "Понятно")
        ui_app.bind_accessible_focus(self.message_text, message)
        ui_app.bind_accessible_focus(ok_button, "Закрыть сообщение")
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.message_text, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(ok_button, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_SHOW, self.on_show)

    def on_show(self, event: wx.ShowEvent) -> None:
        if event.IsShown():
            wx.CallAfter(self.message_text.SetFocus)
            wx.CallAfter(ui_app.announce_action, self, self.message_text.GetValue())
        event.Skip()


class CleanTournamentPickerDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, context):
        super().__init__(parent, title="Открыть турнир", size=(760, 460))
        self.context = context
        self.selected_tournament: Optional[Tournament] = None
        self.tournament_ids: List[int] = []
        self.list_ctrl = wx.ListBox(self)
        self.status_text = wx.StaticText(self, label="Список турниров загружается.")
        self.details_text = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_THEME)
        self.open_button = wx.Button(self, label="Открыть")
        self.refresh_button = wx.Button(self, label="Обновить")
        self.cancel_button = wx.Button(self, label="Отмена")
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            self,
            label="Выберите турнир стрелками вверх и вниз, затем нажмите Enter или кнопку Открыть.",
        )
        intro.Wrap(700)
        root.Add(intro, 0, wx.ALL | wx.EXPAND, 12)

        ui_app.bind_accessible_focus(self.list_ctrl, "Список сохраненных турниров")
        self.list_ctrl.Bind(wx.EVT_LISTBOX, self.on_select_item)
        self.list_ctrl.Bind(wx.EVT_LISTBOX_DCLICK, self.on_activate)
        self.list_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_key_navigation)
        root.Add(self.list_ctrl, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        ui_app.bind_accessible_focus(self.status_text, "Текущий выбранный турнир")
        root.Add(self.status_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        ui_app.bind_accessible_focus(self.details_text, "Подробности выбранного турнира")
        root.Add(self.details_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for button, label, handler in [
            (self.open_button, "Открыть выбранный турнир", self.on_ok),
            (self.refresh_button, "Обновить список турниров", self.on_refresh),
            (self.cancel_button, "Закрыть окно открытия турнира", self.on_cancel),
        ]:
            ui_app.bind_accessible_focus(button, label)
            button.Bind(wx.EVT_BUTTON, handler)
            buttons.Add(button, 0, wx.RIGHT, 8)
        root.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_SHOW, self.on_show)

    def on_show(self, event: wx.ShowEvent) -> None:
        if event.IsShown():
            self._populate()
            wx.CallAfter(self.list_ctrl.SetFocus)
            wx.CallAfter(self._announce_selection)
        event.Skip()

    def _populate(self) -> None:
        tournaments = self.context.tournament_service.list_tournaments()
        self.list_ctrl.Clear()
        self.tournament_ids = []
        for tournament in tournaments:
            self.tournament_ids.append(tournament.id or 0)
            self.list_ctrl.Append(
                f"{tournament.name} | {tournament.event_date} | {tournament.location or 'место не указано'}"
            )
        if tournaments:
            self.list_ctrl.SetSelection(0)
            self._announce_selection()
        else:
            self.status_text.SetLabel("Сохраненных турниров пока нет.")
            self.details_text.SetValue("Создайте турнир в главном окне, затем вернитесь в этот раздел.")
            ui_app.set_accessible_name(self.list_ctrl, "Список турниров пуст")

    def _announce_selection(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        tournament = self.context.tournament_service.get_tournament(self.tournament_ids[index])
        self.status_text.SetLabel(f"Выбран: {tournament.name}")
        details = (
            f"Название: {tournament.name}\n"
            f"Дата: {tournament.event_date}\n"
            f"Место: {tournament.location or 'не указано'}\n"
            f"Тип: {_format_label(tournament.tournament_format)}\n"
            f"Система: {_competition_label(tournament.competition_mode)}\n"
            f"Столов: {tournament.table_count}\n"
            f"Создан: {tournament.created_at[:19].replace('T', ' ')}"
        )
        self.details_text.SetValue(details)
        ui_app.set_accessible_name(self.list_ctrl, f"Список турниров. Текущий турнир: {tournament.name}")
        ui_app.set_accessible_name(self.status_text, f"Выбран турнир: {tournament.name}")
        ui_app.set_accessible_name(self.details_text, details.replace("\n", ". "))
        ui_app.announce_action(self, f"Выбран турнир {tournament.name}.")

    def on_select_item(self, event: wx.CommandEvent) -> None:
        self._announce_selection()
        event.Skip()

    def on_activate(self, event: wx.CommandEvent) -> None:
        self.on_ok(event)

    def on_key_navigation(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_ok(wx.CommandEvent())
            return
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()

    def on_refresh(self, event: wx.CommandEvent) -> None:
        del event
        self._populate()
        ui_app.announce_action(self, "Список турниров обновлен.")

    def on_cancel(self, event: wx.CommandEvent) -> None:
        del event
        self.EndModal(wx.ID_CANCEL)

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            ui_app.error_message(self, "Выберите турнир.")
            return
        self.selected_tournament = self.context.tournament_service.get_tournament(self.tournament_ids[index])
        self.EndModal(wx.ID_OK)


class CleanTournamentDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, tournament: Tournament):
        super().__init__(parent, title="Создание турнира", size=(640, 560))
        self.tournament = tournament
        self.format_map = {label: value for value, label in ui_app.TOURNAMENT_FORMATS}
        self.competition_mode_map = {label: value for value, label in ui_app.COMPETITION_MODES}
        self.seeding_map = {label: value for value, label in ui_app.SEEDING_MODES}
        self.match_format_map = {label: value for value, label in ui_app.MATCH_FORMAT_CHOICES}
        self._build_ui()

    def _text_field(self, parent: wx.Window, sizer: wx.FlexGridSizer, label: str, value: str) -> wx.TextCtrl:
        ctrl = wx.TextCtrl(parent, value=value)
        ui_app.bind_accessible_focus(ctrl, label)
        sizer.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(ctrl, 1, wx.EXPAND)
        return ctrl

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        content = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)

        self.name_ctrl = self._text_field(panel, form, "Название турнира", self.tournament.name)
        self.date_ctrl = self._text_field(panel, form, "Дата турнира", self.tournament.event_date or date.today().isoformat())
        self.location_ctrl = self._text_field(panel, form, "Место проведения", self.tournament.location)

        format_label = next((label for value, label in ui_app.TOURNAMENT_FORMATS if value == self.tournament.tournament_format), ui_app.TOURNAMENT_FORMATS[0][1])
        self.format_choice = wx.Choice(panel, choices=[label for _, label in ui_app.TOURNAMENT_FORMATS])
        self.format_choice.SetStringSelection(format_label)
        ui_app.bind_accessible_focus(self.format_choice, "Тип турнира")
        form.Add(wx.StaticText(panel, label="Тип турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.format_choice, 1, wx.EXPAND)

        competition_label = next((label for value, label in ui_app.COMPETITION_MODES if value == self.tournament.competition_mode), ui_app.COMPETITION_MODES[0][1])
        self.competition_mode_choice = wx.Choice(panel, choices=[label for _, label in ui_app.COMPETITION_MODES])
        self.competition_mode_choice.SetStringSelection(competition_label)
        ui_app.bind_accessible_focus(self.competition_mode_choice, "Система турнира")
        form.Add(wx.StaticText(panel, label="Система турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.competition_mode_choice, 1, wx.EXPAND)

        self.table_count_ctrl = self._text_field(panel, form, "Количество игровых столов", str(self.tournament.table_count or 1))

        seeding_label = next((label for value, label in ui_app.SEEDING_MODES if value == self.tournament.seeding_mode), ui_app.SEEDING_MODES[0][1])
        self.seeding_choice = wx.Choice(panel, choices=[label for _, label in ui_app.SEEDING_MODES])
        self.seeding_choice.SetStringSelection(seeding_label)
        ui_app.bind_accessible_focus(self.seeding_choice, "Тип посева")
        form.Add(wx.StaticText(panel, label="Тип посева"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.seeding_choice, 1, wx.EXPAND)

        match_format_label = next((label for value, label in ui_app.MATCH_FORMAT_CHOICES if value == self.tournament.match_format), ui_app.MATCH_FORMAT_CHOICES[1][1])
        self.match_format_choice = wx.Choice(panel, choices=[label for _, label in ui_app.MATCH_FORMAT_CHOICES])
        self.match_format_choice.SetStringSelection(match_format_label)
        ui_app.bind_accessible_focus(self.match_format_choice, "Формат матча")
        form.Add(wx.StaticText(panel, label="Формат матча"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.match_format_choice, 1, wx.EXPAND)

        self.match_duration_ctrl = self._text_field(panel, form, "Минут на матч", str(self.tournament.match_duration_minutes or 30))
        self.day_start_ctrl = self._text_field(panel, form, "Начало игрового дня", self.tournament.day_start_time or "09:00")

        self.lunch_enabled = wx.CheckBox(panel, label="Есть обеденный перерыв")
        self.lunch_enabled.SetValue(self.tournament.lunch_break_enabled)
        ui_app.bind_accessible_focus(self.lunch_enabled, "Есть обеденный перерыв")
        self.lunch_enabled.Bind(wx.EVT_CHECKBOX, self.on_toggle_lunch)
        form.Add(wx.StaticText(panel, label="Обеденный перерыв"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.lunch_enabled, 1, wx.EXPAND)

        self.lunch_panel = wx.Panel(panel)
        lunch_form = wx.FlexGridSizer(0, 2, 8, 8)
        lunch_form.AddGrowableCol(1, 1)
        self.lunch_start_ctrl = self._text_field(self.lunch_panel, lunch_form, "Начало обеда", self.tournament.lunch_start_time)
        self.lunch_end_ctrl = self._text_field(self.lunch_panel, lunch_form, "Конец обеда", self.tournament.lunch_end_time)
        self.lunch_panel.SetSizer(lunch_form)

        content.Add(form, 0, wx.EXPAND | wx.ALL, 12)
        content.Add(self.lunch_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        panel.SetSizer(content)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(panel, 1, wx.EXPAND)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self._update_lunch_visibility()
        wx.CallLater(150, self.name_ctrl.SetFocus)

    def _update_lunch_visibility(self) -> None:
        enabled = self.lunch_enabled.GetValue()
        self.lunch_panel.Show(enabled)
        self.lunch_panel.Enable(enabled)
        self.Layout()

    def on_toggle_lunch(self, event: wx.CommandEvent) -> None:
        self._update_lunch_visibility()
        event.Skip()

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        if not self.name_ctrl.GetValue().strip():
            ui_app.error_message(self, "Название турнира обязательно.")
            return
        try:
            table_count = int(self.table_count_ctrl.GetValue().strip())
            match_duration = int(self.match_duration_ctrl.GetValue().strip())
        except ValueError:
            ui_app.error_message(self, "Количество столов и минут на матч должны быть целыми числами.")
            return
        if table_count < 1:
            ui_app.error_message(self, "Количество игровых столов должно быть не меньше 1.")
            return
        if match_duration < 1 or match_duration > 120:
            ui_app.error_message(self, "Длительность одного матча должна быть от 1 до 120 минут.")
            return
        if self.lunch_enabled.GetValue() and (not self.lunch_start_ctrl.GetValue().strip() or not self.lunch_end_ctrl.GetValue().strip()):
            ui_app.error_message(self, "Если обеденный перерыв включен, укажите его начало и конец.")
            return
        self.EndModal(wx.ID_OK)

    def get_value(self) -> Tournament:
        self.tournament.name = self.name_ctrl.GetValue().strip()
        self.tournament.event_date = self.date_ctrl.GetValue().strip()
        self.tournament.location = self.location_ctrl.GetValue().strip()
        self.tournament.tournament_format = self.format_map[self.format_choice.GetStringSelection()]
        self.tournament.competition_mode = self.competition_mode_map[self.competition_mode_choice.GetStringSelection()]
        self.tournament.table_count = int(self.table_count_ctrl.GetValue().strip())
        self.tournament.seeding_mode = self.seeding_map[self.seeding_choice.GetStringSelection()]
        self.tournament.match_format = self.match_format_map[self.match_format_choice.GetStringSelection()]
        self.tournament.rule_mode = "standard_ibsa"
        self.tournament.time_limit_enabled = False
        self.tournament.time_limit_minutes = 0
        self.tournament.match_duration_minutes = int(self.match_duration_ctrl.GetValue().strip())
        self.tournament.day_start_time = self.day_start_ctrl.GetValue().strip() or "09:00"
        self.tournament.lunch_break_enabled = self.lunch_enabled.GetValue()
        self.tournament.lunch_start_time = self.lunch_start_ctrl.GetValue().strip() if self.lunch_enabled.GetValue() else ""
        self.tournament.lunch_end_time = self.lunch_end_ctrl.GetValue().strip() if self.lunch_enabled.GetValue() else ""
        self.tournament.reports_path = "reports"
        self.tournament.comment = ""
        return self.tournament


class CleanAccessiblePlayersPanel(ui_app.AccessiblePlayersPanel):
    def refresh(self) -> None:
        current_player_id = None
        player = self.selected_player()
        if player:
            current_player_id = player.id
        self.list_ctrl.Clear()
        self.player_ids = []
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        self.players_cache = {item.id or 0: item for item in players}
        for player in players:
            self.player_ids.append(player.id or 0)
            status_label = next((label for value, label in ui_app.PLAYER_STATUS_CHOICES if value == player.status), player.status)
            rating_label = f"рейтинг {player.rating}" if player.rating is not None else "без рейтинга"
            city_label = player.city or "город не указан"
            self.list_ctrl.Append(f"{player.full_name} | {city_label} | {rating_label} | {status_label}")
        if self.list_ctrl.GetCount() > 0:
            selection = 0
            if current_player_id and current_player_id in self.player_ids:
                selection = self.player_ids.index(current_player_id)
            self.list_ctrl.SetSelection(selection)
            self._announce_selected_player()
        elif self.selection_status:
            self.selection_status.SetLabel("Игроки не добавлены.")
            if self.selection_details:
                self.selection_details.SetValue("Список игроков пуст.")
            ui_app.set_accessible_name(self.list_ctrl, "Список игроков пуст")

    def _announce_selected_player(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        player = self.selected_player()
        if not player:
            return
        text = self.list_ctrl.GetString(index)
        compact = _player_brief(player)
        ui_app.set_accessible_name(self.list_ctrl, f"Список игроков. Текущий игрок: {compact}")
        if self.selection_status:
            self.selection_status.SetLabel(f"Выбран: {compact}")
        if self.selection_details:
            self.selection_details.SetValue(
                f"Текущий игрок турнира:\n{text}\n\nИспользуйте стрелки вверх и вниз для перехода по игрокам."
            )
            ui_app.set_accessible_name(self.selection_details, "Подробности выбранного игрока")


class CleanMainFrame(StableAccessibleMainFrame):
    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            panel,
            label="Приложение для ведения турниров по Showdown и внесения результатов в формате, удобном для скринридеров.",
        )
        intro.Wrap(680)
        intro.SetFont(wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        ui_app.clear_accessibility(intro)
        root.Add(intro, 0, wx.ALL | wx.EXPAND, 18)

        buttons = [
            ("Создать новый турнир", self.on_new_tournament),
            ("Открыть турнир", self.on_open_tournament),
            ("Настройки", self.on_settings),
            ("Выход", self.on_exit),
        ]
        for label, handler in buttons:
            button = wx.Button(panel, label=label)
            ui_app.bind_accessible_focus(button, label)
            button.Bind(wx.EVT_BUTTON, handler)
            if self.primary_button is None:
                self.primary_button = button
            root.Add(button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 18)

        signature = ui_app.SignaturePanel(panel, self.context.settings)
        root.AddStretchSpacer()
        root.Add(signature, 1, wx.EXPAND)
        panel.SetSizer(root)
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        accel = wx.AcceleratorTable([(wx.ACCEL_CTRL, ord("N"), wx.ID_NEW), (wx.ACCEL_CTRL, ord("O"), wx.ID_OPEN)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, self.on_new_tournament, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.on_open_tournament, id=wx.ID_OPEN)
        if self.GetStatusBar() is None:
            self.CreateStatusBar()
        self.SetStatusText("Главное меню. Доступны создание и открытие турнира.")

    def on_new_tournament(self, event: wx.CommandEvent) -> None:
        del event
        dialog = CleanTournamentDialog(self, ui_app.default_tournament())
        if dialog.ShowModal() == wx.ID_OK:
            tournament = self.context.tournament_service.create_tournament(dialog.get_value())
            announcement = (
                f"Турнир «{tournament.name}» успешно создан. "
                "Теперь откройте раздел «Открыть турнир», выберите этот турнир в списке и продолжайте проведение."
            )
            self.SetStatusText(announcement)
            notice = ScreenReaderMessageDialog(self, "Турнир создан", announcement)
            notice.ShowModal()
            notice.Destroy()
            if self.primary_button:
                self.primary_button.SetFocus()
        dialog.Destroy()

    def on_open_tournament(self, event: wx.CommandEvent) -> None:
        del event
        dialog = CleanTournamentPickerDialog(self, self.context)
        if dialog.ShowModal() == wx.ID_OK and dialog.selected_tournament:
            tournament = dialog.selected_tournament
            self.open_tournament_frame(tournament)
            ui_app.announce_action(self, f"Открыт турнир {tournament.name}.")
        else:
            ui_app.announce_action(self, "Открытие турнира отменено.")
        dialog.Destroy()


class FinalTournamentDialog(CleanTournamentDialog):
    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        content = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)

        self.name_ctrl = self._text_field(panel, form, "Название турнира", self.tournament.name)
        self.date_ctrl = self._text_field(panel, form, "Дата турнира", self.tournament.event_date or date.today().isoformat())
        self.location_ctrl = self._text_field(panel, form, "Место проведения", self.tournament.location)

        format_label = next((label for value, label in ui_app.TOURNAMENT_FORMATS if value == self.tournament.tournament_format), ui_app.TOURNAMENT_FORMATS[0][1])
        self.format_choice = wx.Choice(panel, choices=[label for _, label in ui_app.TOURNAMENT_FORMATS])
        self.format_choice.SetStringSelection(format_label)
        ui_app.bind_accessible_focus(self.format_choice, "Тип турнира")
        form.Add(wx.StaticText(panel, label="Тип турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.format_choice, 1, wx.EXPAND)

        competition_label = next((label for value, label in ui_app.COMPETITION_MODES if value == self.tournament.competition_mode), ui_app.COMPETITION_MODES[0][1])
        self.competition_mode_choice = wx.Choice(panel, choices=[label for _, label in ui_app.COMPETITION_MODES])
        self.competition_mode_choice.SetStringSelection(competition_label)
        ui_app.bind_accessible_focus(self.competition_mode_choice, "Система турнира")
        form.Add(wx.StaticText(panel, label="Система турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.competition_mode_choice, 1, wx.EXPAND)

        self.table_count_ctrl = self._text_field(panel, form, "Количество игровых столов", str(self.tournament.table_count or 1))

        match_format_label = next((label for value, label in ui_app.MATCH_FORMAT_CHOICES if value == self.tournament.match_format), ui_app.MATCH_FORMAT_CHOICES[1][1])
        self.match_format_choice = wx.Choice(panel, choices=[label for _, label in ui_app.MATCH_FORMAT_CHOICES])
        self.match_format_choice.SetStringSelection(match_format_label)
        ui_app.bind_accessible_focus(self.match_format_choice, "Формат матча")
        form.Add(wx.StaticText(panel, label="Формат матча"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.match_format_choice, 1, wx.EXPAND)

        self.match_duration_ctrl = self._text_field(panel, form, "Минут на матч", str(self.tournament.match_duration_minutes or 30))
        self.day_start_ctrl = self._text_field(panel, form, "Начало игрового дня", self.tournament.day_start_time or "09:00")

        self.lunch_enabled = wx.CheckBox(panel, label="Есть обеденный перерыв")
        self.lunch_enabled.SetValue(self.tournament.lunch_break_enabled)
        ui_app.bind_accessible_focus(self.lunch_enabled, "Есть обеденный перерыв")
        self.lunch_enabled.Bind(wx.EVT_CHECKBOX, self.on_toggle_lunch)
        form.Add(wx.StaticText(panel, label="Обеденный перерыв"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.lunch_enabled, 1, wx.EXPAND)

        self.lunch_panel = wx.Panel(panel)
        lunch_form = wx.FlexGridSizer(0, 2, 8, 8)
        lunch_form.AddGrowableCol(1, 1)
        self.lunch_start_ctrl = self._text_field(self.lunch_panel, lunch_form, "Начало обеда", self.tournament.lunch_start_time)
        self.lunch_end_ctrl = self._text_field(self.lunch_panel, lunch_form, "Конец обеда", self.tournament.lunch_end_time)
        self.lunch_panel.SetSizer(lunch_form)

        content.Add(form, 0, wx.EXPAND | wx.ALL, 12)
        content.Add(self.lunch_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        panel.SetSizer(content)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(panel, 1, wx.EXPAND)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self._update_lunch_visibility()
        wx.CallLater(150, self.name_ctrl.SetFocus)

    def get_value(self) -> Tournament:
        self.tournament.name = self.name_ctrl.GetValue().strip()
        self.tournament.event_date = self.date_ctrl.GetValue().strip()
        self.tournament.location = self.location_ctrl.GetValue().strip()
        self.tournament.tournament_format = self.format_map[self.format_choice.GetStringSelection()]
        self.tournament.competition_mode = self.competition_mode_map[self.competition_mode_choice.GetStringSelection()]
        self.tournament.table_count = int(self.table_count_ctrl.GetValue().strip())
        self.tournament.seeding_mode = self.tournament.seeding_mode or "snake"
        selected_match_format = self.match_format_map[self.match_format_choice.GetStringSelection()]
        self.tournament.match_format = 1 if self.tournament.tournament_format == "team" else max(5, selected_match_format)
        self.tournament.rule_mode = "standard_ibsa"
        self.tournament.time_limit_enabled = False
        self.tournament.time_limit_minutes = 0
        self.tournament.match_duration_minutes = int(self.match_duration_ctrl.GetValue().strip())
        self.tournament.day_start_time = self.day_start_ctrl.GetValue().strip() or "09:00"
        self.tournament.lunch_break_enabled = self.lunch_enabled.GetValue()
        self.tournament.lunch_start_time = self.lunch_start_ctrl.GetValue().strip() if self.lunch_enabled.GetValue() else ""
        self.tournament.lunch_end_time = self.lunch_end_ctrl.GetValue().strip() if self.lunch_enabled.GetValue() else ""
        self.tournament.reports_path = "reports"
        self.tournament.comment = ""
        return self.tournament


class FinalTablesPanel(StableTablesPanel):
    def _current_table_announcement(self) -> str:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return ""
        return self.list_ctrl.GetString(index)

    def _announce_current_item(self) -> None:
        current = self._current_table_announcement()
        if not current:
            return
        if self.selection_status:
            self.selection_status.SetLabel(current)
            ui_app.set_accessible_name(self.selection_status, "Текущий пункт списка столов")
        details = "Используйте цифры для быстрого перехода к столу."
        match_id = self._selected_match_id() if hasattr(self, "_selected_match_id") else None
        if match_id:
            match = self.context.match_service.get_match(match_id)
            state = self.context.match_service.load_state(match_id)
            details = (
                f"Стадия: {match.stage or 'не указана'}\n"
                f"Счет по сетам: {state.sets_won_a}:{state.sets_won_b}"
            )
        if self.selection_details:
            self.selection_details.SetValue(details)
            ui_app.set_accessible_name(self.selection_details, "Подробности выбранного пункта списка столов")

    def on_select_item(self, event: wx.CommandEvent) -> None:
        self._announce_current_item()
        event.Skip()

    def on_focus_list(self, event: wx.FocusEvent) -> None:
        self._announce_current_item()
        event.Skip()

    def on_extra_key_navigation(self, event: wx.KeyEvent) -> None:
        key_code = event.GetKeyCode()
        if key_code == wx.WXK_F5:
            current = self._current_table_announcement()
            if current:
                self._announce_current_item()
                ui_app.announce_action(self, current)
            return
        if ord("0") <= key_code <= ord("9") and self.view_choice and self.view_choice.GetSelection() == 0:
            self._table_jump_buffer += chr(key_code)
            if self._table_jump_reset:
                self._table_jump_reset.Stop()
            self._table_jump_reset = wx.CallLater(1200, self._reset_table_jump_buffer)
            for index in range(self.list_ctrl.GetCount()):
                line = self.list_ctrl.GetString(index)
                parts = [part for part in line.replace("-", " ").split() if part.isdigit()]
                if parts and parts[0] == self._table_jump_buffer:
                    self.list_ctrl.SetSelection(index)
                    self._announce_current_item()
                    current = self._current_table_announcement()
                    if current:
                        ui_app.announce_action(self, current)
                    return
            return
        event.Skip()

    def _reset_table_jump_buffer(self) -> None:
        self._table_jump_buffer = ""


class FinalMainFrame(CleanMainFrame):
    def _build_ui(self) -> None:
        super()._build_ui()
        self.Bind(wx.EVT_CHAR_HOOK, self.on_main_key_navigation)
        main_hotkey_id = int(wx.NewIdRef())
        self.Bind(wx.EVT_MENU, self.on_announce_current_context, id=main_hotkey_id)
        self.SetAcceleratorTable(
            wx.AcceleratorTable(
                [
                    (wx.ACCEL_CTRL, ord("N"), wx.ID_NEW),
                    (wx.ACCEL_CTRL, ord("O"), wx.ID_OPEN),
                    (wx.ACCEL_NORMAL, wx.WXK_F5, main_hotkey_id),
                ]
            )
        )

    def on_main_key_navigation(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_F5:
            self.on_announce_current_context(wx.CommandEvent())
            return
        event.Skip()

    def on_announce_current_context(self, event: wx.CommandEvent) -> None:
        del event
        ui_app.announce_action(self, "Главное меню. Доступны создание и открытие турнира.")

    def on_new_tournament(self, event: wx.CommandEvent) -> None:
        del event
        dialog = FinalTournamentDialog(self, ui_app.default_tournament())
        if dialog.ShowModal() == wx.ID_OK:
            tournament = self.context.tournament_service.create_tournament(dialog.get_value())
            announcement = (
                f"Турнир «{tournament.name}» успешно создан. "
                "Теперь откройте раздел «Открыть турнир», выберите этот турнир в списке и продолжайте проведение."
            )
            self.SetStatusText(announcement)
            notice = ScreenReaderMessageDialog(self, "Турнир создан", announcement)
            notice.ShowModal()
            notice.Destroy()
            if self.primary_button:
                self.primary_button.SetFocus()
        dialog.Destroy()


class ErrorDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, text: str):
        super().__init__(parent, title="Ошибка", size=(620, 240))
        self.message_text = wx.TextCtrl(
            self,
            value=f"Ошибка.\n{text}",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_THEME,
        )
        close_button = wx.Button(self, wx.ID_OK, "Закрыть")
        ui_app.bind_accessible_focus(self.message_text, f"Ошибка. {text}")
        ui_app.bind_accessible_focus(close_button, "Закрыть окно ошибки")
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.message_text, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(close_button, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_SHOW, self.on_show)

    def on_show(self, event: wx.ShowEvent) -> None:
        if event.IsShown():
            wx.CallAfter(self.message_text.SetFocus)
            wx.CallAfter(ui_app.announce_action, self, self.message_text.GetValue(), True)
        event.Skip()


def _final_error_message(parent: wx.Window, text: str) -> None:
    dialog = ErrorDialog(parent, text)
    dialog.ShowModal()
    dialog.Destroy()


class FinalAccessiblePlayersPanel(CleanAccessiblePlayersPanel):
    def _build_ui(self) -> None:
        super()._build_ui()
        self.list_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_key_navigation)

    def on_key_navigation(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_F5:
            self._announce_selected_player()
            return
        event.Skip()


class FinalAccessibleMatchesPanel(StableAccessibleMatchesPanel):
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)

        ui_app.bind_accessible_focus(self.list_ctrl, "Список матчей")
        self.list_ctrl.Bind(wx.EVT_CHOICE, self.on_select_match)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_list_focus)
        self.list_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_list_key_navigation)
        root.Add(self.list_ctrl, 0, wx.ALL | wx.EXPAND, 12)

        result_button = wx.Button(self, label="Внести результат")
        ui_app.bind_accessible_focus(result_button, "Внести итоговый результат для выбранного матча")
        result_button.Bind(wx.EVT_BUTTON, self.on_record_result)
        root.Add(result_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        if self.primary_button is None:
            self.primary_button = result_button

        self.selection_status = wx.StaticText(self, label="Матчи не созданы")
        ui_app.bind_accessible_focus(self.selection_status, "Текущий матч")
        root.Add(self.selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.selection_details = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE)
        ui_app.bind_accessible_focus(self.selection_details, "Подробности выбранного матча")
        root.Add(self.selection_details, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        actions = [
            ("Сформировать следующий тур", "Сформировать следующий тур автоматически", self.on_generate_next_stage),
            ("Сохранить отчет", "Сохранить текстовый отчет", self.on_report),
            ("Удалить матч", "Удалить выбранный матч", self.on_delete_match),
            ("Обновить список", "Обновить список матчей", self.on_refresh),
            ("Создать матч", "Создать матч вручную", self.on_add_match),
        ]
        for label, accessible_label, handler in actions:
            button = wx.Button(self, label=label)
            ui_app.bind_accessible_focus(button, accessible_label)
            button.Bind(wx.EVT_BUTTON, handler)
            root.Add(button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        options_row = wx.BoxSizer(wx.HORIZONTAL)
        seeding_label = wx.StaticText(self, label="Тип посева")
        ui_app.clear_accessibility(seeding_label)
        options_row.Add(seeding_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.seeding_choice = wx.Choice(self, choices=[label for _, label in ui_app.SEEDING_MODES])
        ui_app.bind_accessible_focus(self.seeding_choice, "Тип посева для автоматического формирования матчей")
        self.seeding_choice.Bind(wx.EVT_CHOICE, self.on_change_seeding_mode)
        options_row.Add(self.seeding_choice, 0)
        root.Add(options_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        generate_button = wx.Button(self, label="Сформировать матчи")
        ui_app.bind_accessible_focus(generate_button, "Сформировать матчи автоматически по выбранному типу посева")
        generate_button.Bind(wx.EVT_BUTTON, self.on_generate_matches)
        root.Add(generate_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        root.AddStretchSpacer()
        self.SetSizer(root)

    def on_list_key_navigation(self, event: wx.KeyEvent) -> None:
        key_code = event.GetKeyCode()
        if key_code == wx.WXK_F5:
            self._announce_selected_match()
            return
        if key_code == wx.WXK_DELETE:
            self.on_delete_match(wx.CommandEvent())
            return
        event.Skip()

    def on_record_result(self, event: wx.CommandEvent) -> None:
        match_id = self.selected_match_id()
        super().on_record_result(event)
        if match_id:
            self.refresh(preserve_selected=True)
            if match_id in self.match_ids:
                self.list_ctrl.SetSelection(self.match_ids.index(match_id))
                self._announce_selected_match()


class FinalTournamentFrame(StableTournamentFrame):
    def on_announce_current_context(self, event: wx.CommandEvent) -> None:
        del event
        if not self.notebook:
            return
        page = self.notebook.GetCurrentPage()
        if page is None:
            self._announce_current_tab()
            return
        for method_name in ("_announce_selected_match", "_announce_current_item", "_announce_selected_player"):
            announcer = getattr(page, method_name, None)
            if callable(announcer):
                announcer()
                return
        self._announce_current_tab()


class FinalRoundsPanel(StableRoundsPanel):
    def on_extra_key_navigation(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_F5:
            self._announce_current_item()
            return
        event.Skip()


def _final_hotkeys_help_text(settings: AppSettings) -> str:
    lines = [
        "Поддерживаемый формат записи: Ctrl+N, Ctrl+O, F5.",
        "Доступны только реально работающие горячие клавиши приложения.",
        "",
    ]
    for key in VISIBLE_SETTINGS_KEYS:
        title = ui_app.HOTKEY_LABELS.get(key, key)
        value = settings.hotkeys.get(key, "")
        description = {
            "new_tournament": "Создать новый турнир.",
            "open_tournament": "Открыть список сохраненных турниров.",
            "announce_score": "Озвучить текущий выбранный пункт или текущую вкладку.",
        }.get(key, "")
        lines.append(f"{title}: {value}. {description}")
    return "\n".join(lines)


ui_app.TournamentPickerDialog = CleanTournamentPickerDialog
ui_app.AccessibleTournamentDialog = FinalTournamentDialog
ui_app.AccessiblePlayersPanel = FinalAccessiblePlayersPanel
ui_app.AccessibleMatchesPanel = FinalAccessibleMatchesPanel
ui_app.TablesPanel = FinalTablesPanel
ui_app.RoundsPanel = FinalRoundsPanel
ui_app.AccessibleMainFrame = FinalMainFrame
ui_app.TournamentFrame = FinalTournamentFrame
ui_app.error_message = _final_error_message
_hotkeys_help_text = _final_hotkeys_help_text

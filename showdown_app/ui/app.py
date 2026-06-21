from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

import wx

from showdown_app.application.services import COMPETITION_MODES, SEEDING_MODES, TOURNAMENT_FORMATS, default_tournament
from showdown_app.bootstrap import AppContext
from showdown_app.domain.models import (
    EVENT_BALL_BREAK,
    EVENT_BAT_BREAK,
    EVENT_DEFAULT_LOSS,
    EVENT_ERROR,
    EVENT_FINISH_MATCH,
    EVENT_GOAL,
    EVENT_LOST_BALL,
    EVENT_MATCH_READY,
    EVENT_MEDICAL_TIMEOUT,
    EVENT_PENALTY,
    EVENT_PLAYER_TIMEOUT,
    EVENT_REFEREE_TIMEOUT,
    EVENT_REPLAY_SERVE,
    EVENT_RESUME,
    EVENT_SWITCH_SIDES,
    EVENT_WARNING,
    MATCH_STATUS_COMPLETED,
    MATCH_STATUS_DEFAULTED,
    MatchCommand,
    MatchState,
    Player,
    Tournament,
)
from showdown_app.domain.scoring import MatchValidationError, state_summary
from showdown_app.settings import AppSettings


class NamedAccessible(wx.Accessible):
    def __init__(self, name: str, role: int, description: str = "", control: Optional[wx.Window] = None):
        super().__init__()
        self._name = name
        self._role = role
        self._description = description or name
        self._control = control

    def GetName(self, childId: int):
        return wx.ACC_OK, self._name

    def GetDescription(self, childId: int):
        return wx.ACC_OK, self._description

    def GetRole(self, childId: int):
        return wx.ACC_OK, self._role

    def GetState(self, childId: int):
        state = 0
        if isinstance(self._control, wx.CheckBox) and self._control.GetValue():
            state |= wx.ACC_STATE_CHECKED
        return wx.ACC_OK, state


def set_accessible_name(control: wx.Window, name: str) -> None:
    control.SetName(name)
    if hasattr(control, "SetHelpText"):
        control.SetHelpText(name)
    if hasattr(control, "SetToolTip"):
        control.SetToolTip(name)
    accessible = getattr(control, "_named_accessible", None)
    if isinstance(accessible, NamedAccessible):
        accessible._name = name
        accessible._description = name


def _role_for_control(control: wx.Window) -> int:
    if isinstance(control, wx.TextCtrl):
        return wx.ROLE_SYSTEM_TEXT
    if isinstance(control, wx.Button):
        return wx.ROLE_SYSTEM_PUSHBUTTON
    if isinstance(control, wx.CheckBox):
        return wx.ROLE_SYSTEM_CHECKBUTTON
    if isinstance(control, wx.Choice):
        return wx.ROLE_SYSTEM_COMBOBOX
    if isinstance(control, wx.ListBox):
        return wx.ROLE_SYSTEM_LIST
    if isinstance(control, wx.Notebook):
        return wx.ROLE_SYSTEM_PAGETABLIST
    return wx.ROLE_SYSTEM_CLIENT


def bind_accessible_focus(control: wx.Window, name: str) -> None:
    set_accessible_name(control, name)
    accessible = NamedAccessible(name, _role_for_control(control), name, control)
    control.SetAccessible(accessible)
    setattr(control, "_named_accessible", accessible)

    def _restore_accessibility(event: wx.FocusEvent) -> None:
        current_name = control.GetName() or name
        set_accessible_name(control, current_name)
        control.SetAccessible(accessible)
        event.Skip()

    control.Bind(wx.EVT_SET_FOCUS, _restore_accessibility)


def schedule_initial_focus(control: wx.Window, delay_ms: int = 200) -> None:
    def _focus() -> None:
        if control and control.IsShownOnScreen():
            control.SetFocus()

    wx.CallLater(delay_ms, _focus)

def clear_accessibility(control: wx.Window) -> None:
    control.SetName("")


HOTKEY_LABELS = {
    "new_tournament": "Новый турнир",
    "open_tournament": "Открыть турнир",
    "new_match": "Новый матч",
    "save": "Сохранить",
    "undo": "Отменить последнее действие",
    "redo": "Повторить действие",
    "announce_score": "Озвучить текущий счет",
    "focus_journal": "Перейти к журналу",
    "goal_a": "Гол игрока A",
    "goal_b": "Гол игрока B",
    "error_a": "Ошибка игрока A",
    "error_b": "Ошибка игрока B",
    "penalty_a": "Штраф игроку A",
    "penalty_b": "Штраф игроку B",
    "timeouts": "Меню тайм-аутов",
    "switch_sides": "Смена сторон",
    "replay_serve": "Повторная подача",
    "lost_ball": "Потеря мяча",
}


PLAYER_STATUS_CHOICES = [
    ("active", "Активный"),
    ("withdrawn", "Снялся"),
    ("disqualified", "Дисквалифицирован"),
    ("not_allowed", "Не допущен"),
]

MATCH_STATUS_LABELS = {
    "not_started": "Не начат",
    "in_progress": "Идет",
    "paused": "Приостановлен",
    "completed": "Завершен",
    "defaulted": "Завершен по умолчанию",
    "cancelled": "Отменен",
}


def message(parent: wx.Window, text: str, caption: str = "ShowdownApp") -> None:
    announce_action(parent, text)
    wx.MessageBox(text, caption, wx.OK | wx.ICON_INFORMATION, parent)


def error_message(parent: wx.Window, text: str) -> None:
    wx.MessageBox(text, "Ошибка", wx.OK | wx.ICON_ERROR, parent)


def confirm(parent: wx.Window, text: str, caption: str = "Подтверждение") -> bool:
    return wx.MessageBox(text, caption, wx.YES_NO | wx.ICON_QUESTION, parent) == wx.YES


HOTKEY_LABELS = {
    "new_tournament": "Новый турнир",
    "open_tournament": "Открыть турнир",
    "new_match": "Новый матч",
    "save": "Сохранить",
    "undo": "Отменить последнее действие",
    "redo": "Повторить действие",
    "announce_score": "Озвучить текущий счет",
    "focus_journal": "Перейти к журналу",
    "goal_a": "Гол игрока A",
    "goal_b": "Гол игрока B",
    "error_a": "Ошибка игрока A",
    "error_b": "Ошибка игрока B",
    "penalty_a": "Штраф игроку A",
    "penalty_b": "Штраф игроку B",
    "timeouts": "Меню тайм-аутов",
    "switch_sides": "Смена сторон",
    "replay_serve": "Повторная подача",
    "lost_ball": "Потеря мяча",
}

PLAYER_STATUS_CHOICES = [
    ("active", "Активный"),
    ("withdrawn", "Снялся"),
    ("disqualified", "Дисквалифицирован"),
    ("not_allowed", "Не допущен"),
]

MATCH_STATUS_LABELS = {
    "not_started": "Не начат",
    "in_progress": "Идет",
    "paused": "Приостановлен",
    "completed": "Завершен",
    "defaulted": "Завершен по умолчанию",
    "cancelled": "Отменен",
}


def error_message(parent: wx.Window, text: str) -> None:
    announce_action(parent, text, beep=True)
    wx.MessageBox(text, "Ошибка", wx.OK | wx.ICON_ERROR, parent)


def confirm(parent: wx.Window, text: str, caption: str = "Подтверждение") -> bool:
    announce_action(parent, text)
    return wx.MessageBox(text, caption, wx.YES_NO | wx.ICON_QUESTION, parent) == wx.YES


def announce_action(parent: Optional[wx.Window], text: str, beep: bool = False) -> None:
    if not text:
        return
    if beep:
        wx.Bell()
    window = parent if isinstance(parent, wx.Window) else None
    if not window:
        return
    top = window.GetTopLevelParent()
    if isinstance(top, wx.Frame):
        try:
            if top.GetStatusBar() is None:
                top.CreateStatusBar()
            top.SetStatusText(text)
            status_bar = top.GetStatusBar()
            if status_bar:
                set_accessible_name(status_bar, text)
        except Exception:
            pass
    set_accessible_name(window, text)


def parse_hhmm(value: str) -> int:
    hours, minutes = value.split(":")
    return (int(hours) * 60) + int(minutes)


def format_hhmm(total_minutes: int) -> str:
    total_minutes %= 24 * 60
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


MATCH_FORMAT_CHOICES = [
    (3, "Трехсетовый матч, до двух побед"),
    (5, "Пятисетовый матч, до трех побед"),
]


def compact_player_announcement(player: Player) -> str:
    city = player.city.strip() if player.city else ""
    return f"{player.full_name}, {city}" if city else player.full_name


def completed_set_lines(state: MatchState) -> List[str]:
    lines: List[str] = []
    for set_score in state.sets:
        if not set_score.winner_role:
            continue
        lines.append(
            f"Сет {set_score.set_no}: {set_score.score_a}:{set_score.score_b}, "
            f"начинал игрок {set_score.starter_role}"
        )
    return lines


HOTKEY_LABELS = {
    "new_tournament": "Новый турнир",
    "open_tournament": "Открыть турнир",
    "new_match": "Новый матч",
    "save": "Сохранить",
    "undo": "Отменить последнее действие",
    "redo": "Повторить действие",
    "announce_score": "Озвучить текущий счет",
    "focus_journal": "Перейти к журналу",
    "goal_a": "Гол игрока A",
    "goal_b": "Гол игрока B",
    "error_a": "Ошибка игрока A",
    "error_b": "Ошибка игрока B",
    "penalty_a": "Штраф игроку A",
    "penalty_b": "Штраф игроку B",
    "timeouts": "Меню тайм-аутов",
    "switch_sides": "Смена сторон",
    "replay_serve": "Повторная подача",
    "lost_ball": "Потеря мяча",
}

PLAYER_STATUS_CHOICES = [
    ("active", "Активный"),
    ("withdrawn", "Снялся"),
    ("disqualified", "Дисквалифицирован"),
    ("not_allowed", "Не допущен"),
]

MATCH_STATUS_LABELS = {
    "not_started": "Не начат",
    "in_progress": "Идет",
    "paused": "Приостановлен",
    "completed": "Завершен",
    "defaulted": "Завершен по умолчанию",
    "cancelled": "Отменен",
}


def error_message(parent: wx.Window, text: str) -> None:
    wx.MessageBox(text, "Ошибка", wx.OK | wx.ICON_ERROR, parent)


def confirm(parent: wx.Window, text: str, caption: str = "Подтверждение") -> bool:
    return wx.MessageBox(text, caption, wx.YES_NO | wx.ICON_QUESTION, parent) == wx.YES


class SignaturePanel(wx.Panel):
    def __init__(self, parent: wx.Window, settings: AppSettings):
        super().__init__(parent)
        self.settings = settings
        clear_accessibility(self)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

    def AcceptsFocus(self) -> bool:
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:
        return False

    def on_paint(self, event: wx.PaintEvent) -> None:
        del event
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        if not self.settings.show_author_signature:
            return
        width, height = self.GetClientSize()
        dc.SetTextForeground(wx.Colour(90, 90, 90))
        font = self.GetFont()
        font.SetPointSize(max(8, font.GetPointSize() - 1))
        dc.SetFont(font)
        lines = [
            "Developed by Nikita Chuyev, a blind software engineer",
            "Telegram: @nikita_chuyev",
        ]
        y = height - 36
        for line in lines:
            text_w, _ = dc.GetTextExtent(line)
            dc.DrawText(line, max(8, width - text_w - 12), y)
            y += 16


class ShowdownWxApp(wx.App):
    def __init__(self, redirect: bool, context: AppContext):
        self.context = context
        super().__init__(redirect=redirect)

    def OnInit(self) -> bool:
        frame = AccessibleMainFrame(self.context)
        self.SetTopWindow(frame)
        frame.Show()
        return True


class MainFrame(wx.Frame):
    def __init__(self, context: AppContext):
        super().__init__(None, title="ShowdownApp", size=(760, 520))
        self.context = context
        self.current_tournament_frame: Optional[TournamentFrame] = None
        self.primary_button: Optional[wx.Button] = None
        self._build_ui()
        self.Centre()
        wx.CallAfter(self._set_initial_focus)

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            panel,
            label=(
                "Portable-приложение для ведения турниров и судейского подсчета "
                "результатов по Showdown"
            ),
        )
        intro.Wrap(680)
        intro.SetFont(wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        clear_accessibility(intro)
        root.Add(intro, 0, wx.ALL | wx.EXPAND, 18)

        buttons = [
            ("Создать новый турнир", self.on_new_tournament),
            ("Открыть турнир", self.on_open_tournament),
            ("Настройки", self.on_settings),
            ("Выход", self.on_exit),
        ]
        for label, handler in buttons:
            button = wx.Button(panel, label=label)
            bind_accessible_focus(button, label)
            button.Bind(wx.EVT_BUTTON, handler)
            if self.primary_button is None:
                self.primary_button = button
            root.Add(button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 18)

        signature = SignaturePanel(panel, self.context.settings)
        root.AddStretchSpacer()
        root.Add(signature, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 0)
        panel.SetSizer(root)
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        accel = wx.AcceleratorTable(
            [
                (wx.ACCEL_CTRL, ord("N"), wx.ID_NEW),
                (wx.ACCEL_CTRL, ord("O"), wx.ID_OPEN),
            ]
        )
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, self.on_new_tournament, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.on_open_tournament, id=wx.ID_OPEN)

    def _set_initial_focus(self) -> None:
        if self.primary_button:
            self.primary_button.SetFocus()

    def open_tournament_frame(self, tournament: Tournament) -> None:
        if self.current_tournament_frame and self.current_tournament_frame:
            self.current_tournament_frame.Destroy()
        self.current_tournament_frame = TournamentFrame(self, self.context, tournament)
        self.current_tournament_frame.Show()
        self.current_tournament_frame.Raise()

    def on_new_tournament(self, event: wx.CommandEvent) -> None:
        del event
        dialog = AccessibleTournamentDialog(self, default_tournament())
        if dialog.ShowModal() == wx.ID_OK:
            tournament = self.context.tournament_service.create_tournament(dialog.get_value())
            self.open_tournament_frame(tournament)
        dialog.Destroy()

    def on_open_tournament(self, event: wx.CommandEvent) -> None:
        del event
        dialog = TournamentPickerDialog(self, self.context)
        if dialog.ShowModal() == wx.ID_OK and dialog.selected_tournament:
            self.open_tournament_frame(dialog.selected_tournament)
        dialog.Destroy()

    def on_settings(self, event: wx.CommandEvent) -> None:
        del event
        dialog = SettingsDialog(self, self.context.settings)
        if dialog.ShowModal() == wx.ID_OK:
            self.context.settings = dialog.get_value()
            self.context.settings.save(self.context.paths)
            self.Refresh()
        dialog.Destroy()

    def on_exit(self, event: wx.CommandEvent) -> None:
        del event
        self.Close(True)


class AccessibleMainFrame(MainFrame):
    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            panel,
            label="Приложение для ведения турниров по Showdown и внесения результатов в доступном для скринридера виде",
        )
        intro.Wrap(680)
        intro.SetFont(wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        clear_accessibility(intro)
        root.Add(intro, 0, wx.ALL | wx.EXPAND, 18)
        buttons = [
            ("Создать новый турнир", self.on_new_tournament),
            ("Открыть турнир", self.on_open_tournament),
            ("Настройки", self.on_settings),
            ("Выход", self.on_exit),
        ]
        for label, handler in buttons:
            button = wx.Button(panel, label=label)
            bind_accessible_focus(button, label)
            button.Bind(wx.EVT_BUTTON, handler)
            if self.primary_button is None:
                self.primary_button = button
            root.Add(button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 18)
        signature = SignaturePanel(panel, self.context.settings)
        root.AddStretchSpacer()
        root.Add(signature, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 0)
        panel.SetSizer(root)
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)
        accel = wx.AcceleratorTable([(wx.ACCEL_CTRL, ord("N"), wx.ID_NEW), (wx.ACCEL_CTRL, ord("O"), wx.ID_OPEN)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, self.on_new_tournament, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.on_open_tournament, id=wx.ID_OPEN)

    def on_open_tournament(self, event: wx.CommandEvent) -> None:
        del event
        dialog = TournamentPickerDialog(self, self.context)
        dialog.SetTitle("Открыть турнир")
        if dialog.ShowModal() == wx.ID_OK and dialog.selected_tournament:
            self.open_tournament_frame(dialog.selected_tournament)
        dialog.Destroy()


class TournamentPickerDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, context: AppContext):
        super().__init__(parent, title="Открыть турнир", size=(700, 400))
        self.context = context
        self.selected_tournament: Optional[Tournament] = None
        self.tournament_ids: List[int] = []
        self.list_ctrl = wx.ListBox(self)
        bind_accessible_focus(self.list_ctrl, "Список турниров")
        self._populate()
        self.list_ctrl.Bind(wx.EVT_LISTBOX_DCLICK, self.on_activate)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.list_ctrl, 1, wx.ALL | wx.EXPAND, 12)
        sizer.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(sizer)
        wx.CallLater(150, self.list_ctrl.SetFocus)

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

    def on_activate(self, event: wx.CommandEvent) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        self.selected_tournament = self.context.tournament_service.get_tournament(self.tournament_ids[index])
        self.EndModal(wx.ID_OK)

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            error_message(self, "Выберите турнир.")
            return
        self.selected_tournament = self.context.tournament_service.get_tournament(self.tournament_ids[index])
        self.EndModal(wx.ID_OK)


class TournamentDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, tournament: Tournament):
        super().__init__(parent, title="\u0421\u043e\u0437\u0434\u0430\u043d\u0438\u0435 \u0442\u0443\u0440\u043d\u0438\u0440\u0430", size=(620, 420))
        self.tournament = tournament
        self.format_map = {label: value for value, label in TOURNAMENT_FORMATS}
        self.competition_mode_map = {label: value for value, label in COMPETITION_MODES}
        self.seeding_map = {label: value for value, label in SEEDING_MODES}
        self.match_format_map = {label: value for value, label in MATCH_FORMAT_CHOICES}
        self._build_ui()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)
        self.name_ctrl = self._text_field(panel, form, "\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0442\u0443\u0440\u043d\u0438\u0440\u0430", self.tournament.name)
        self.date_ctrl = self._text_field(panel, form, "\u0414\u0430\u0442\u0430 \u0442\u0443\u0440\u043d\u0438\u0440\u0430", self.tournament.event_date or date.today().isoformat())
        self.location_ctrl = self._text_field(panel, form, "\u041c\u0435\u0441\u0442\u043e \u043f\u0440\u043e\u0432\u0435\u0434\u0435\u043d\u0438\u044f", self.tournament.location)
        format_label = next((label for value, label in TOURNAMENT_FORMATS if value == self.tournament.tournament_format), TOURNAMENT_FORMATS[0][1])
        self.format_choice = wx.Choice(panel, choices=[label for _, label in TOURNAMENT_FORMATS])
        self.format_choice.SetStringSelection(format_label)
        bind_accessible_focus(self.format_choice, "\u0422\u0438\u043f \u0442\u0443\u0440\u043d\u0438\u0440\u0430")
        form.Add(wx.StaticText(panel, label="\u0422\u0438\u043f \u0442\u0443\u0440\u043d\u0438\u0440\u0430"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.format_choice, 1, wx.EXPAND)
        competition_mode_label = next(
            (label for value, label in COMPETITION_MODES if value == self.tournament.competition_mode),
            COMPETITION_MODES[0][1],
        )
        self.competition_mode_choice = wx.Choice(panel, choices=[label for _, label in COMPETITION_MODES])
        self.competition_mode_choice.SetStringSelection(competition_mode_label)
        bind_accessible_focus(self.competition_mode_choice, "Система проведения турнира")
        form.Add(wx.StaticText(panel, label="Система турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.competition_mode_choice, 1, wx.EXPAND)
        self.table_count_ctrl = self._text_field(panel, form, "\u041a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e \u0438\u0433\u0440\u043e\u0432\u044b\u0445 \u0441\u0442\u043e\u043b\u043e\u0432", str(self.tournament.table_count or 1))
        seeding_label = next(
            (label for value, label in SEEDING_MODES if value == self.tournament.seeding_mode),
            SEEDING_MODES[0][1],
        )
        self.seeding_choice = wx.Choice(panel, choices=[label for _, label in SEEDING_MODES])
        self.seeding_choice.SetStringSelection(seeding_label)
        bind_accessible_focus(self.seeding_choice, "Тип посева для автоматического создания матчей")
        form.Add(wx.StaticText(panel, label="Тип посева"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.seeding_choice, 1, wx.EXPAND)
        panel_root = wx.BoxSizer(wx.VERTICAL)
        panel_root.Add(form, 1, wx.EXPAND)
        panel.SetSizer(panel_root)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(panel, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        wx.CallLater(150, self.name_ctrl.SetFocus)

    def _text_field(self, panel: wx.Panel, sizer: wx.FlexGridSizer, label: str, value: str) -> wx.TextCtrl:
        ctrl = wx.TextCtrl(panel, value=value)
        bind_accessible_focus(ctrl, label)
        sizer.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(ctrl, 1, wx.EXPAND)
        return ctrl

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        if not self.name_ctrl.GetValue().strip():
            error_message(self, "\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0442\u0443\u0440\u043d\u0438\u0440\u0430 \u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u043e.")
            return
        try:
            table_count = int(self.table_count_ctrl.GetValue().strip())
        except ValueError:
            error_message(self, "\u041a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e \u0438\u0433\u0440\u043e\u0432\u044b\u0445 \u0441\u0442\u043e\u043b\u043e\u0432 \u0434\u043e\u043b\u0436\u043d\u043e \u0431\u044b\u0442\u044c \u0446\u0435\u043b\u044b\u043c \u0447\u0438\u0441\u043b\u043e\u043c.")
            return
        if table_count < 1:
            error_message(self, "\u041a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e \u0438\u0433\u0440\u043e\u0432\u044b\u0445 \u0441\u0442\u043e\u043b\u043e\u0432 \u0434\u043e\u043b\u0436\u043d\u043e \u0431\u044b\u0442\u044c \u043d\u0435 \u043c\u0435\u043d\u044c\u0448\u0435 1.")
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
        self.tournament.match_format = 3
        self.tournament.rule_mode = "standard_ibsa"
        self.tournament.time_limit_enabled = False
        self.tournament.time_limit_minutes = 0
        self.tournament.reports_path = "reports"
        self.tournament.comment = ""
        return self.tournament


class EnhancedTournamentDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, tournament: Tournament):
        super().__init__(parent, title="Создание турнира", size=(620, 520))
        self.tournament = tournament
        self.format_map = {label: value for value, label in TOURNAMENT_FORMATS}
        self.competition_mode_map = {label: value for value, label in COMPETITION_MODES}
        self.seeding_map = {label: value for value, label in SEEDING_MODES}
        self._build_ui()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)
        self.name_ctrl = self._text_field(panel, form, "Название турнира", self.tournament.name)
        self.date_ctrl = self._text_field(panel, form, "Дата турнира", self.tournament.event_date or date.today().isoformat())
        self.location_ctrl = self._text_field(panel, form, "Место проведения", self.tournament.location)
        format_label = next((label for value, label in TOURNAMENT_FORMATS if value == self.tournament.tournament_format), TOURNAMENT_FORMATS[0][1])
        self.format_choice = wx.Choice(panel, choices=[label for _, label in TOURNAMENT_FORMATS])
        self.format_choice.SetStringSelection(format_label)
        bind_accessible_focus(self.format_choice, "Тип турнира")
        form.Add(wx.StaticText(panel, label="Тип турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.format_choice, 1, wx.EXPAND)
        competition_mode_label = next((label for value, label in COMPETITION_MODES if value == self.tournament.competition_mode), COMPETITION_MODES[0][1])
        self.competition_mode_choice = wx.Choice(panel, choices=[label for _, label in COMPETITION_MODES])
        self.competition_mode_choice.SetStringSelection(competition_mode_label)
        bind_accessible_focus(self.competition_mode_choice, "Система проведения турнира")
        form.Add(wx.StaticText(panel, label="Система турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.competition_mode_choice, 1, wx.EXPAND)
        self.table_count_ctrl = self._text_field(panel, form, "Количество игровых столов", str(self.tournament.table_count or 1))
        seeding_label = next((label for value, label in SEEDING_MODES if value == self.tournament.seeding_mode), SEEDING_MODES[0][1])
        self.seeding_choice = wx.Choice(panel, choices=[label for _, label in SEEDING_MODES])
        self.seeding_choice.SetStringSelection(seeding_label)
        bind_accessible_focus(self.seeding_choice, "Тип посева")
        form.Add(wx.StaticText(panel, label="Тип посева"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.seeding_choice, 1, wx.EXPAND)
        match_format_label = next(
            (label for value, label in MATCH_FORMAT_CHOICES if value == self.tournament.match_format),
            MATCH_FORMAT_CHOICES[0][1],
        )
        self.match_format_choice = wx.Choice(panel, choices=[label for _, label in MATCH_FORMAT_CHOICES])
        self.match_format_choice.SetStringSelection(match_format_label)
        bind_accessible_focus(self.match_format_choice, "Формат матча")
        form.Add(wx.StaticText(panel, label="Формат матча"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.match_format_choice, 1, wx.EXPAND)

        self.match_duration_ctrl = self._text_field(panel, form, "Минут на матч", str(self.tournament.match_duration_minutes or 30))
        self.day_start_ctrl = self._text_field(panel, form, "Начало игрового дня", self.tournament.day_start_time or "09:00")
        self.lunch_enabled = wx.CheckBox(panel, label="Добавить обеденный перерыв")
        self.lunch_enabled.SetValue(self.tournament.lunch_break_enabled)
        bind_accessible_focus(self.lunch_enabled, "Добавить обеденный перерыв")
        form.Add(wx.StaticText(panel, label="Обеденный перерыв"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.lunch_enabled, 1, wx.EXPAND)
        self.lunch_start_ctrl = self._text_field(panel, form, "Начало обеда", self.tournament.lunch_start_time)
        self.lunch_end_ctrl = self._text_field(panel, form, "Конец обеда", self.tournament.lunch_end_time)
        root_panel = wx.BoxSizer(wx.VERTICAL)
        root_panel.Add(form, 1, wx.EXPAND)
        panel.SetSizer(root_panel)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(panel, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        wx.CallLater(150, self.name_ctrl.SetFocus)

    def _text_field(self, panel: wx.Panel, sizer: wx.FlexGridSizer, label: str, value: str) -> wx.TextCtrl:
        ctrl = wx.TextCtrl(panel, value=value)
        bind_accessible_focus(ctrl, label)
        sizer.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(ctrl, 1, wx.EXPAND)
        return ctrl

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        if not self.name_ctrl.GetValue().strip():
            error_message(self, "Название турнира обязательно.")
            return
        try:
            table_count = int(self.table_count_ctrl.GetValue().strip())
            match_duration = int(self.match_duration_ctrl.GetValue().strip())
        except ValueError:
            error_message(self, "Количество столов и минут на матч должны быть целыми числами.")
            return
        if table_count < 1:
            error_message(self, "Количество игровых столов должно быть не меньше 1.")
            return
        if match_duration < 1 or match_duration > 120:
            error_message(self, "Длительность одного матча должна быть от 1 до 120 минут.")
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
        self.tournament.lunch_start_time = self.lunch_start_ctrl.GetValue().strip()
        self.tournament.lunch_end_time = self.lunch_end_ctrl.GetValue().strip()
        self.tournament.reports_path = "reports"
        self.tournament.comment = ""
        return self.tournament


class ScheduleSettingsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, tournament: Tournament):
        super().__init__(parent, title="Настройка времени", size=(520, 320))
        self.tournament = tournament
        self._build_ui()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)
        self.match_duration_ctrl = wx.TextCtrl(panel, value=str(self.tournament.match_duration_minutes or 30))
        bind_accessible_focus(self.match_duration_ctrl, "Минут на матч")
        form.Add(wx.StaticText(panel, label="Минут на матч"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.match_duration_ctrl, 1, wx.EXPAND)
        self.day_start_ctrl = wx.TextCtrl(panel, value=self.tournament.day_start_time or "09:00")
        bind_accessible_focus(self.day_start_ctrl, "Начало игрового дня")
        form.Add(wx.StaticText(panel, label="Начало игрового дня"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.day_start_ctrl, 1, wx.EXPAND)
        self.lunch_enabled = wx.CheckBox(panel, label="Обеденный перерыв")
        self.lunch_enabled.SetValue(self.tournament.lunch_break_enabled)
        bind_accessible_focus(self.lunch_enabled, "Обеденный перерыв")
        form.Add(wx.StaticText(panel, label="Есть ли обед"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.lunch_enabled, 1, wx.EXPAND)
        self.lunch_start_ctrl = wx.TextCtrl(panel, value=self.tournament.lunch_start_time)
        bind_accessible_focus(self.lunch_start_ctrl, "Начало обеда")
        form.Add(wx.StaticText(panel, label="Начало обеда"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.lunch_start_ctrl, 1, wx.EXPAND)
        self.lunch_end_ctrl = wx.TextCtrl(panel, value=self.tournament.lunch_end_time)
        bind_accessible_focus(self.lunch_end_ctrl, "Конец обеда")
        form.Add(wx.StaticText(panel, label="Конец обеда"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.lunch_end_ctrl, 1, wx.EXPAND)
        panel_root = wx.BoxSizer(wx.VERTICAL)
        panel_root.Add(form, 1, wx.EXPAND)
        panel.SetSizer(panel_root)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(panel, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        try:
            duration = int(self.match_duration_ctrl.GetValue().strip())
        except ValueError:
            error_message(self, "Минуты на матч должны быть целым числом.")
            return
        if duration < 1 or duration > 120:
            error_message(self, "Длительность одного матча должна быть от 1 до 120 минут.")
            return
        self.EndModal(wx.ID_OK)

    def get_value(self) -> Tournament:
        self.tournament.match_duration_minutes = int(self.match_duration_ctrl.GetValue().strip())
        self.tournament.day_start_time = self.day_start_ctrl.GetValue().strip() or "09:00"
        self.tournament.lunch_break_enabled = self.lunch_enabled.GetValue()
        self.tournament.lunch_start_time = self.lunch_start_ctrl.GetValue().strip()
        self.tournament.lunch_end_time = self.lunch_end_ctrl.GetValue().strip()
        return self.tournament


class AccessibleTournamentDialog(EnhancedTournamentDialog):
    def __init__(self, parent: wx.Window, tournament: Tournament):
        super().__init__(parent, tournament)
        self.SetTitle("Создание турнира")

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)
        self.name_ctrl = self._text_field(panel, form, "Название турнира", self.tournament.name)
        self.date_ctrl = self._text_field(panel, form, "Дата турнира", self.tournament.event_date or date.today().isoformat())
        self.location_ctrl = self._text_field(panel, form, "Место проведения", self.tournament.location)
        format_label = next((label for value, label in TOURNAMENT_FORMATS if value == self.tournament.tournament_format), TOURNAMENT_FORMATS[0][1])
        self.format_choice = wx.Choice(panel, choices=[label for _, label in TOURNAMENT_FORMATS])
        self.format_choice.SetStringSelection(format_label)
        bind_accessible_focus(self.format_choice, "Тип турнира")
        form.Add(wx.StaticText(panel, label="Тип турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.format_choice, 1, wx.EXPAND)
        competition_mode_label = next((label for value, label in COMPETITION_MODES if value == self.tournament.competition_mode), COMPETITION_MODES[0][1])
        self.competition_mode_choice = wx.Choice(panel, choices=[label for _, label in COMPETITION_MODES])
        self.competition_mode_choice.SetStringSelection(competition_mode_label)
        bind_accessible_focus(self.competition_mode_choice, "Система турнира")
        form.Add(wx.StaticText(panel, label="Система турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.competition_mode_choice, 1, wx.EXPAND)
        self.table_count_ctrl = self._text_field(panel, form, "Количество игровых столов", str(self.tournament.table_count or 1))
        seeding_label = next((label for value, label in SEEDING_MODES if value == self.tournament.seeding_mode), SEEDING_MODES[0][1])
        self.seeding_choice = wx.Choice(panel, choices=[label for _, label in SEEDING_MODES])
        self.seeding_choice.SetStringSelection(seeding_label)
        bind_accessible_focus(self.seeding_choice, "Тип посева")
        form.Add(wx.StaticText(panel, label="Тип посева"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.seeding_choice, 1, wx.EXPAND)
        self.match_duration_ctrl = self._text_field(panel, form, "Минут на матч", str(self.tournament.match_duration_minutes or 30))
        self.day_start_ctrl = self._text_field(panel, form, "Начало игрового дня", self.tournament.day_start_time or "09:00")
        self.lunch_enabled = wx.CheckBox(panel, label="Обеденный перерыв")
        self.lunch_enabled.SetValue(self.tournament.lunch_break_enabled)
        bind_accessible_focus(self.lunch_enabled, self._lunch_checkbox_label())
        self.lunch_enabled.Bind(wx.EVT_CHECKBOX, self.on_toggle_lunch)
        form.Add(wx.StaticText(panel, label="Есть ли обед"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.lunch_enabled, 1, wx.EXPAND)
        self.lunch_panel = wx.Panel(panel)
        lunch_form = wx.FlexGridSizer(0, 2, 8, 8)
        lunch_form.AddGrowableCol(1, 1)
        self.lunch_start_ctrl = self._text_field(self.lunch_panel, lunch_form, "Начало обеда", self.tournament.lunch_start_time)
        self.lunch_end_ctrl = self._text_field(self.lunch_panel, lunch_form, "Конец обеда", self.tournament.lunch_end_time)
        self.lunch_panel.SetSizer(lunch_form)
        root.Add(form, 0, wx.EXPAND | wx.ALL, 12)
        root.Add(self.lunch_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        panel.SetSizer(root)
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.Add(panel, 1, wx.EXPAND)
        self.SetSizer(frame)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self._update_lunch_visibility()
        wx.CallLater(150, self.name_ctrl.SetFocus)

    def _lunch_checkbox_label(self) -> str:
        return f"Обеденный перерыв, {'отмечено' if self.lunch_enabled.GetValue() else 'не отмечено'}"

    def _update_lunch_visibility(self) -> None:
        show = self.lunch_enabled.GetValue()
        self.lunch_panel.Show(show)
        self.lunch_panel.Enable(show)
        set_accessible_name(self.lunch_enabled, self._lunch_checkbox_label())
        self.Layout()
        self.FitInside()

    def on_toggle_lunch(self, event: wx.CommandEvent) -> None:
        del event
        self._update_lunch_visibility()

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        if not self.name_ctrl.GetValue().strip():
            error_message(self, "Название турнира обязательно.")
            return
        try:
            table_count = int(self.table_count_ctrl.GetValue().strip())
            match_duration = int(self.match_duration_ctrl.GetValue().strip())
        except ValueError:
            error_message(self, "Количество столов и минут на матч должны быть целыми числами.")
            return
        if table_count < 1:
            error_message(self, "Количество игровых столов должно быть не меньше 1.")
            return
        if match_duration < 1 or match_duration > 120:
            error_message(self, "Длительность одного матча должна быть от 1 до 120 минут.")
            return
        if self.lunch_enabled.GetValue() and (not self.lunch_start_ctrl.GetValue().strip() or not self.lunch_end_ctrl.GetValue().strip()):
            error_message(self, "Если обеденный перерыв включен, укажите его начало и конец.")
            return
        self.EndModal(wx.ID_OK)


class ScheduleSettingsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, tournament: Tournament):
        super().__init__(parent, title="Настройка времени", size=(520, 360))
        self.tournament = tournament
        self._build_ui()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        content = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)

        self.match_duration_ctrl = wx.TextCtrl(panel, value=str(self.tournament.match_duration_minutes or 30))
        bind_accessible_focus(self.match_duration_ctrl, "Минут на матч")
        form.Add(wx.StaticText(panel, label="Минут на матч"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.match_duration_ctrl, 1, wx.EXPAND)

        self.day_start_ctrl = wx.TextCtrl(panel, value=self.tournament.day_start_time or "09:00")
        bind_accessible_focus(self.day_start_ctrl, "Начало игрового дня")
        form.Add(wx.StaticText(panel, label="Начало игрового дня"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.day_start_ctrl, 1, wx.EXPAND)

        self.lunch_enabled = wx.CheckBox(panel, label="Обеденный перерыв")
        self.lunch_enabled.SetValue(self.tournament.lunch_break_enabled)
        bind_accessible_focus(self.lunch_enabled, self._lunch_checkbox_label())
        self.lunch_enabled.Bind(wx.EVT_CHECKBOX, self.on_toggle_lunch)
        form.Add(wx.StaticText(panel, label="Есть ли обед"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.lunch_enabled, 1, wx.EXPAND)

        self.lunch_panel = wx.Panel(panel)
        lunch_form = wx.FlexGridSizer(0, 2, 8, 8)
        lunch_form.AddGrowableCol(1, 1)
        self.lunch_start_ctrl = wx.TextCtrl(self.lunch_panel, value=self.tournament.lunch_start_time)
        bind_accessible_focus(self.lunch_start_ctrl, "Начало обеда")
        lunch_form.Add(wx.StaticText(self.lunch_panel, label="Начало обеда"), 0, wx.ALIGN_CENTER_VERTICAL)
        lunch_form.Add(self.lunch_start_ctrl, 1, wx.EXPAND)
        self.lunch_end_ctrl = wx.TextCtrl(self.lunch_panel, value=self.tournament.lunch_end_time)
        bind_accessible_focus(self.lunch_end_ctrl, "Конец обеда")
        lunch_form.Add(wx.StaticText(self.lunch_panel, label="Конец обеда"), 0, wx.ALIGN_CENTER_VERTICAL)
        lunch_form.Add(self.lunch_end_ctrl, 1, wx.EXPAND)
        self.lunch_panel.SetSizer(lunch_form)

        content.Add(form, 0, wx.EXPAND)
        content.Add(self.lunch_panel, 0, wx.TOP | wx.EXPAND, 8)
        panel_root = wx.BoxSizer(wx.VERTICAL)
        panel_root.Add(content, 1, wx.EXPAND)
        panel.SetSizer(panel_root)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(panel, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self._update_lunch_visibility()

    def _lunch_checkbox_label(self) -> str:
        return f"Обеденный перерыв, {'отмечено' if self.lunch_enabled.GetValue() else 'не отмечено'}"

    def _update_lunch_visibility(self) -> None:
        enabled = self.lunch_enabled.GetValue()
        self.lunch_panel.Show(enabled)
        self.lunch_panel.Enable(enabled)
        set_accessible_name(self.lunch_enabled, self._lunch_checkbox_label())
        self.Layout()
        self.SendSizeEvent()

    def on_toggle_lunch(self, event: wx.CommandEvent) -> None:
        self._update_lunch_visibility()
        event.Skip()

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        try:
            duration = int(self.match_duration_ctrl.GetValue().strip())
        except ValueError:
            error_message(self, "Минуты на матч должны быть целым числом.")
            return
        if duration < 1 or duration > 120:
            error_message(self, "Длительность одного матча должна быть от 1 до 120 минут.")
            return
        if self.lunch_enabled.GetValue() and (not self.lunch_start_ctrl.GetValue().strip() or not self.lunch_end_ctrl.GetValue().strip()):
            error_message(self, "Если обеденный перерыв включен, укажите его начало и конец.")
            return
        self.EndModal(wx.ID_OK)

    def get_value(self) -> Tournament:
        self.tournament.match_duration_minutes = int(self.match_duration_ctrl.GetValue().strip())
        self.tournament.day_start_time = self.day_start_ctrl.GetValue().strip() or "09:00"
        self.tournament.lunch_break_enabled = self.lunch_enabled.GetValue()
        self.tournament.lunch_start_time = self.lunch_start_ctrl.GetValue().strip() if self.lunch_enabled.GetValue() else ""
        self.tournament.lunch_end_time = self.lunch_end_ctrl.GetValue().strip() if self.lunch_enabled.GetValue() else ""
        return self.tournament


class AccessibleTournamentDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, tournament: Tournament):
        super().__init__(parent, title="Создание турнира", size=(620, 540))
        self.tournament = tournament
        self.format_map = {label: value for value, label in TOURNAMENT_FORMATS}
        self.competition_mode_map = {label: value for value, label in COMPETITION_MODES}
        self.seeding_map = {label: value for value, label in SEEDING_MODES}
        self._build_ui()

    def _text_field(self, panel: wx.Panel, sizer: wx.FlexGridSizer, label: str, value: str) -> wx.TextCtrl:
        ctrl = wx.TextCtrl(panel, value=value)
        bind_accessible_focus(ctrl, label)
        sizer.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
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

        format_label = next((label for value, label in TOURNAMENT_FORMATS if value == self.tournament.tournament_format), TOURNAMENT_FORMATS[0][1])
        self.format_choice = wx.Choice(panel, choices=[label for _, label in TOURNAMENT_FORMATS])
        self.format_choice.SetStringSelection(format_label)
        bind_accessible_focus(self.format_choice, "Тип турнира")
        form.Add(wx.StaticText(panel, label="Тип турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.format_choice, 1, wx.EXPAND)

        competition_mode_label = next((label for value, label in COMPETITION_MODES if value == self.tournament.competition_mode), COMPETITION_MODES[0][1])
        self.competition_mode_choice = wx.Choice(panel, choices=[label for _, label in COMPETITION_MODES])
        self.competition_mode_choice.SetStringSelection(competition_mode_label)
        bind_accessible_focus(self.competition_mode_choice, "Система турнира")
        form.Add(wx.StaticText(panel, label="Система турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.competition_mode_choice, 1, wx.EXPAND)

        self.table_count_ctrl = self._text_field(panel, form, "Количество игровых столов", str(self.tournament.table_count or 1))

        seeding_label = next((label for value, label in SEEDING_MODES if value == self.tournament.seeding_mode), SEEDING_MODES[0][1])
        self.seeding_choice = wx.Choice(panel, choices=[label for _, label in SEEDING_MODES])
        self.seeding_choice.SetStringSelection(seeding_label)
        bind_accessible_focus(self.seeding_choice, "Тип посева")
        form.Add(wx.StaticText(panel, label="Тип посева"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.seeding_choice, 1, wx.EXPAND)

        self.match_duration_ctrl = self._text_field(panel, form, "Минут на матч", str(self.tournament.match_duration_minutes or 30))
        self.day_start_ctrl = self._text_field(panel, form, "Начало игрового дня", self.tournament.day_start_time or "09:00")

        self.lunch_enabled = wx.CheckBox(panel, label="Обеденный перерыв")
        self.lunch_enabled.SetValue(self.tournament.lunch_break_enabled)
        bind_accessible_focus(self.lunch_enabled, self._lunch_checkbox_label())
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
        schedule_initial_focus(self.name_ctrl)

    def _lunch_checkbox_label(self) -> str:
        return f"Обеденный перерыв, {'отмечено' if self.lunch_enabled.GetValue() else 'не отмечено'}"

    def _update_lunch_visibility(self) -> None:
        enabled = self.lunch_enabled.GetValue()
        self.lunch_panel.Show(enabled)
        self.lunch_panel.Enable(enabled)
        set_accessible_name(self.lunch_enabled, self._lunch_checkbox_label())
        self.Layout()
        self.SendSizeEvent()

    def on_toggle_lunch(self, event: wx.CommandEvent) -> None:
        self._update_lunch_visibility()
        event.Skip()

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        if not self.name_ctrl.GetValue().strip():
            error_message(self, "Название турнира обязательно.")
            return
        try:
            table_count = int(self.table_count_ctrl.GetValue().strip())
            match_duration = int(self.match_duration_ctrl.GetValue().strip())
        except ValueError:
            error_message(self, "Количество столов и минут на матч должны быть целыми числами.")
            return
        if table_count < 1:
            error_message(self, "Количество игровых столов должно быть не меньше 1.")
            return
        if match_duration < 1 or match_duration > 120:
            error_message(self, "Длительность одного матча должна быть от 1 до 120 минут.")
            return
        if self.lunch_enabled.GetValue() and (not self.lunch_start_ctrl.GetValue().strip() or not self.lunch_end_ctrl.GetValue().strip()):
            error_message(self, "Если обеденный перерыв включен, укажите его начало и конец.")
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
        self.tournament.match_format = 1 if self.tournament.tournament_format == "team" else 5
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


class SettingsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, settings: AppSettings):
        super().__init__(parent, title="Настройки", size=(680, 560))
        self.settings = AppSettings(
            reports_path=settings.reports_path,
            include_event_details_in_report=settings.include_event_details_in_report,
            hotkeys=dict(settings.hotkeys),
            show_author_signature=settings.show_author_signature,
        )
        self.hotkey_fields: Dict[str, wx.TextCtrl] = {}
        self.first_focus_control: Optional[wx.Window] = None
        self._build_ui()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel_root = wx.BoxSizer(wx.VERTICAL)
        self.signature_check = wx.CheckBox(panel, label="Показывать визуальный информационный блок автора")
        self.signature_check.SetValue(self.settings.show_author_signature)
        bind_accessible_focus(self.signature_check, "Показывать визуальный информационный блок автора")
        self.first_focus_control = self.signature_check

        panel_root.Add(self.signature_check, 0, wx.BOTTOM | wx.EXPAND, 16)

        hotkeys_title = wx.StaticText(panel, label="Горячие клавиши")
        panel_root.Add(hotkeys_title, 0, wx.BOTTOM, 8)
        hotkeys = wx.FlexGridSizer(0, 2, 6, 8)
        hotkeys.AddGrowableCol(1, 1)
        for key, value in self.settings.hotkeys.items():
            label = wx.StaticText(panel, label=HOTKEY_LABELS.get(key, key))
            hotkeys.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            field = wx.TextCtrl(panel, value=value)
            bind_accessible_focus(field, f"Горячая клавиша: {HOTKEY_LABELS.get(key, key)}")
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
        self.settings.reports_path = "reports"
        self.settings.include_event_details_in_report = False
        self.settings.show_author_signature = self.signature_check.GetValue()
        for key, ctrl in self.hotkey_fields.items():
            self.settings.hotkeys[key] = ctrl.GetValue().strip() or self.settings.hotkeys[key]
        return self.settings


class TournamentFrame(wx.Frame):
    def __init__(self, parent: wx.Window, context: AppContext, tournament: Tournament):
        super().__init__(parent, title=f"\u0422\u0443\u0440\u043d\u0438\u0440: {tournament.name}", size=(1040, 720))
        self.context = context
        self.tournament = tournament
        self.notebook: Optional[wx.Notebook] = None
        self.players_panel: Optional[PlayersPanel] = None
        self.matches_panel: Optional[MatchesPanel] = None
        self.tables_panel: Optional[TablesPanel] = None
        self.rounds_panel: Optional[RoundsPanel] = None
        self._build_ui()
        self.Centre()
        wx.CallAfter(self._set_initial_focus)

    def _build_ui(self) -> None:
        self.notebook = wx.Notebook(self)
        bind_accessible_focus(self.notebook, "\u0412\u043a\u043b\u0430\u0434\u043a\u0438 \u0442\u0443\u0440\u043d\u0438\u0440\u0430: \u0443\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u0438, \u043c\u0430\u0442\u0447\u0438, \u0441\u0442\u043e\u043b\u044b, \u0442\u0443\u0440\u044b")
        self.players_panel = AccessiblePlayersPanel(self.notebook, self.context, self.tournament)
        self.matches_panel = AccessibleMatchesPanel(self.notebook, self.context, self.tournament, self.players_panel)
        self.tables_panel = TablesPanel(self.notebook, self.context, self.tournament)
        self.rounds_panel = RoundsPanel(self.notebook, self.context, self.tournament)
        set_accessible_name(self.players_panel, "\u0412\u043a\u043b\u0430\u0434\u043a\u0430 \u0443\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u043e\u0432 \u0442\u0443\u0440\u043d\u0438\u0440\u0430")
        set_accessible_name(self.matches_panel, "\u0412\u043a\u043b\u0430\u0434\u043a\u0430 \u043c\u0430\u0442\u0447\u0435\u0439 \u0442\u0443\u0440\u043d\u0438\u0440\u0430")
        set_accessible_name(self.tables_panel, "Вкладка списка столов")
        set_accessible_name(self.rounds_panel, "Вкладка списка туров")
        self.notebook.AddPage(self.players_panel, "\u0423\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u0438 \u0442\u0443\u0440\u043d\u0438\u0440\u0430")
        self.notebook.AddPage(self.matches_panel, "\u041c\u0430\u0442\u0447\u0438 \u0442\u0443\u0440\u043d\u0438\u0440\u0430")
        self.notebook.AddPage(self.tables_panel, "Список столов")
        self.notebook.AddPage(self.rounds_panel, "Список туров")
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(self.notebook, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        accel = wx.AcceleratorTable(
            [
                (wx.ACCEL_CTRL, ord("N"), wx.ID_NEW),
                (wx.ACCEL_CTRL, ord("O"), wx.ID_OPEN),
                (wx.ACCEL_NORMAL, wx.WXK_F5, wx.ID_REFRESH),
            ]
        )
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, self.GetParent().on_new_tournament, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.GetParent().on_open_tournament, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self.on_announce_current_context, id=wx.ID_REFRESH)
        self.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_change_tab)
        if self.GetStatusBar() is None:
            self.CreateStatusBar()
        self.SetStatusText(f"Турнир открыт: {self.tournament.name}")

    def _set_initial_focus(self) -> None:
        if self.players_panel:
            self.players_panel.focus_primary_control()

    def refresh_all(self) -> None:
        if self.players_panel:
            self.players_panel.refresh()
        if self.matches_panel:
            self.matches_panel.refresh()
        if self.tables_panel:
            self.tables_panel.refresh()
        if self.rounds_panel:
            self.rounds_panel.refresh()

    def on_change_tab(self, event: wx.BookCtrlEvent) -> None:
        self._announce_current_tab()
        event.Skip()

    def on_announce_current_context(self, event: wx.CommandEvent) -> None:
        del event
        self._announce_current_tab()

    def _announce_current_tab(self) -> None:
        if not self.notebook:
            return
        page = self.notebook.GetCurrentPage()
        if page is None:
            return
        set_accessible_name(self.notebook, f"Вкладка турнира: {self.notebook.GetPageText(self.notebook.GetSelection())}")
        for method_name in ("_announce_current_item", "_announce_selected_match", "_announce_selected_player"):
            method = getattr(page, method_name, None)
            if callable(method):
                method()
                return


class PlayersPanel(wx.Panel):
    def __init__(self, parent: wx.Window, context: AppContext, tournament: Tournament):
        super().__init__(parent)
        self.context = context
        self.tournament = tournament
        self.player_ids: List[int] = []
        self.players_cache: Dict[int, Player] = {}
        self.list_ctrl = wx.Choice(self)
        self.primary_button: Optional[wx.Button] = None
        self.selection_status: Optional[wx.StaticText] = None
        self.selection_details: Optional[wx.TextCtrl] = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        bind_accessible_focus(self.list_ctrl, "Список игроков")
        self.list_ctrl.Bind(wx.EVT_CHOICE, self.on_select_player)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_list_focus)
        root.Add(self.list_ctrl, 0, wx.ALL | wx.EXPAND, 12)
        self.selection_status = wx.StaticText(self, label="Игроки не добавлены")
        bind_accessible_focus(self.selection_status, "Текущий игрок")
        root.Add(self.selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.selection_details = wx.TextCtrl(
            self,
            value="",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE,
        )
        bind_accessible_focus(self.selection_details, "Подробности выбранного игрока")
        root.Add(self.selection_details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [
            ("Добавить", self.on_add),
            ("Редактировать", self.on_edit),
            ("Удалить", self.on_delete),
            ("Обновить", self.on_refresh),
        ]:
            button = wx.Button(self, label=label)
            bind_accessible_focus(button, label)
            button.Bind(wx.EVT_BUTTON, handler)
            if self.primary_button is None:
                self.primary_button = button
            buttons.Add(button, 0, wx.RIGHT, 8)
        root.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(root)

    def focus_primary_control(self) -> None:
        self.list_ctrl.SetFocus()
        if self.list_ctrl.GetCount() > 0 and self.list_ctrl.GetSelection() == wx.NOT_FOUND:
            self.list_ctrl.SetSelection(0)

    def selected_player(self) -> Optional[Player]:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return None
        player_id = self.player_ids[index]
        return self.players_cache.get(player_id)

    def refresh(self) -> None:
        self.list_ctrl.Clear()
        self.player_ids = []
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        self.players_cache = {player.id or 0: player for player in players}
        for player in players:
            self.player_ids.append(player.id or 0)
            status_label = next(
                (label for value, label in PLAYER_STATUS_CHOICES if value == player.status),
                player.status,
            )
            rating_label = f"\u0440\u0435\u0439\u0442\u0438\u043d\u0433 {player.rating}" if player.rating is not None else "\u0431\u0435\u0437 \u0440\u0435\u0439\u0442\u0438\u043d\u0433\u0430"
            city_label = player.city or "город не указан"
            self.list_ctrl.Append(f"{player.full_name} | {city_label} | {rating_label} | {status_label}")
        if self.list_ctrl.GetCount() > 0:
            self.list_ctrl.SetSelection(0)
            self._announce_selected_player()
        elif self.selection_status:
            self.selection_status.SetLabel("\u0418\u0433\u0440\u043e\u043a\u0438 \u043d\u0435 \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u044b")
            set_accessible_name(self.list_ctrl, "\u0421\u043f\u0438\u0441\u043e\u043a \u0438\u0433\u0440\u043e\u043a\u043e\u0432 \u043f\u0443\u0441\u0442")

    def _announce_selected_player(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        text = self.list_ctrl.GetString(index)
        set_accessible_name(self.list_ctrl, f"Список игроков. Текущий игрок: {compact}")
        if self.selection_status:
            self.selection_status.SetLabel(f"Выбран: {compact}")
        if self.selection_details:
            self.selection_details.SetValue(
                f"Текущий игрок турнира:\n{text}\n\n"
                "Используйте стрелки вверх и вниз для перехода по игрокам."
            )

    def on_select_player(self, event: wx.CommandEvent) -> None:
        self._announce_selected_player()
        event.Skip()

    def on_list_focus(self, event: wx.FocusEvent) -> None:
        self._announce_selected_player()
        event.Skip()

    def on_add(self, event: wx.CommandEvent) -> None:
        del event
        dialog = PlayerDialog(self, Player(id=None, tournament_id=self.tournament.id or 0, full_name=""))
        if dialog.ShowModal() == wx.ID_OK:
            self.context.tournament_service.save_player(dialog.get_value())
            self.refresh()
        dialog.Destroy()

    def on_edit(self, event: wx.CommandEvent) -> None:
        del event
        player = self.selected_player()
        if not player:
            error_message(self, "Выберите игрока.")
            return
        dialog = PlayerDialog(self, player)
        if dialog.ShowModal() == wx.ID_OK:
            self.context.tournament_service.save_player(dialog.get_value())
            self.refresh()
        dialog.Destroy()

    def on_delete(self, event: wx.CommandEvent) -> None:
        del event
        player = self.selected_player()
        if not player:
            error_message(self, "Выберите игрока.")
            return
        if confirm(self, f"Удалить игрока {player.full_name}?"):
            self.context.tournament_service.delete_player(player.id or 0)
            self.refresh()

    def on_refresh(self, event: wx.CommandEvent) -> None:
        del event
        self.refresh()


class AccessiblePlayersPanel(PlayersPanel):
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        bind_accessible_focus(self.list_ctrl, "Список игроков")
        self.list_ctrl.Bind(wx.EVT_CHOICE, self.on_select_player)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_list_focus)
        root.Add(self.list_ctrl, 0, wx.ALL | wx.EXPAND, 12)
        self.selection_status = wx.StaticText(self, label="Игроки не добавлены")
        bind_accessible_focus(self.selection_status, "Текущий игрок")
        root.Add(self.selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.selection_details = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE)
        bind_accessible_focus(self.selection_details, "Подробности выбранного игрока")
        root.Add(self.selection_details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [("Добавить", self.on_add), ("Редактировать", self.on_edit), ("Удалить", self.on_delete), ("Обновить", self.on_refresh)]:
            button = wx.Button(self, label=label)
            bind_accessible_focus(button, label)
            button.Bind(wx.EVT_BUTTON, handler)
            if self.primary_button is None:
                self.primary_button = button
            buttons.Add(button, 0, wx.RIGHT, 8)
        root.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(root)

    def refresh(self) -> None:
        current_player_id = None
        player = self.selected_player()
        if player:
            current_player_id = player.id
        self.list_ctrl.Clear()
        self.player_ids = []
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        self.players_cache = {player.id or 0: player for player in players}
        for player in players:
            self.player_ids.append(player.id or 0)
            status_label = next((label for value, label in PLAYER_STATUS_CHOICES if value == player.status), player.status)
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
            self.selection_status.SetLabel("Игроки не добавлены")
            if self.selection_details:
                self.selection_details.SetValue("Список игроков пуст.")
            set_accessible_name(self.list_ctrl, "Список игроков пуст")

    def _announce_selected_player(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        player = self.selected_player()
        if not player:
            return
        text = self.list_ctrl.GetString(index)
        compact = compact_player_announcement(player)
        set_accessible_name(self.list_ctrl, f"Список игроков. Текущий игрок: {compact}")
        if self.selection_status:
            self.selection_status.SetLabel(f"Выбран: {compact}")
        if self.selection_details:
            self.selection_details.SetValue(
                f"Текущий игрок турнира:\n{text}\n\nИспользуйте стрелки вверх и вниз для перехода по игрокам."
            )

    def on_edit(self, event: wx.CommandEvent) -> None:
        del event
        player = self.selected_player()
        if not player:
            error_message(self, "Выберите игрока.")
            return
        dialog = PlayerDialog(self, player)
        if dialog.ShowModal() == wx.ID_OK:
            self.context.tournament_service.save_player(dialog.get_value())
            self.refresh()
        dialog.Destroy()

    def on_delete(self, event: wx.CommandEvent) -> None:
        del event
        player = self.selected_player()
        if not player:
            error_message(self, "Выберите игрока.")
            return
        if confirm(self, f"Удалить игрока {player.full_name}?"):
            self.context.tournament_service.delete_player(player.id or 0)
            self.refresh()


class PlayerDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, player: Player):
        super().__init__(parent, title="\u0418\u0433\u0440\u043e\u043a", size=(560, 500))
        self.player = player
        self._build_ui()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)
        self.full_name = self._add_text(panel, form, "\u0424\u0418\u041e", self.player.full_name)
        self.rating = self._add_text(panel, form, "\u0420\u0435\u0439\u0442\u0438\u043d\u0433", "" if self.player.rating is None else str(self.player.rating))
        self.city = self._add_text(panel, form, "Город", self.player.city)
        help_text = wx.StaticText(panel, label="\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0424\u0418\u041e, \u0433\u043e\u0440\u043e\u0434 \u0438 \u043f\u0440\u0438 \u043d\u0430\u043b\u0438\u0447\u0438\u0438 \u0440\u0435\u0439\u0442\u0438\u043d\u0433.")
        self.status_map = {label: value for value, label in PLAYER_STATUS_CHOICES}
        self.status = wx.Choice(panel, choices=[label for _, label in PLAYER_STATUS_CHOICES])
        bind_accessible_focus(self.status, "\u0421\u0442\u0430\u0442\u0443\u0441 \u0438\u0433\u0440\u043e\u043a\u0430")
        form.Add(wx.StaticText(panel, label="\u0421\u0442\u0430\u0442\u0443\u0441"), 0, wx.ALIGN_CENTER_VERTICAL)
        current_status_label = next((label for value, label in PLAYER_STATUS_CHOICES if value == self.player.status), PLAYER_STATUS_CHOICES[0][1])
        self.status.SetStringSelection(current_status_label)
        form.Add(self.status, 1, wx.EXPAND)
        panel_root = wx.BoxSizer(wx.VERTICAL)
        panel_root.Add(form, 1, wx.EXPAND)
        panel_root.Add(help_text, 0, wx.TOP, 10)
        panel.SetSizer(panel_root)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(panel, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        wx.CallLater(150, self.full_name.SetFocus)

    def _add_text(self, panel: wx.Panel, sizer: wx.FlexGridSizer, label: str, value: str) -> wx.TextCtrl:
        ctrl = wx.TextCtrl(panel, value=value)
        bind_accessible_focus(ctrl, label)
        sizer.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(ctrl, 1, wx.EXPAND)
        return ctrl

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        if not self.full_name.GetValue().strip():
            error_message(self, "\u0424\u0418\u041e \u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u043e.")
            return
        rating_raw = self.rating.GetValue().strip()
        if rating_raw:
            try:
                int(rating_raw)
            except ValueError:
                error_message(self, "\u0420\u0435\u0439\u0442\u0438\u043d\u0433 \u0434\u043e\u043b\u0436\u0435\u043d \u0431\u044b\u0442\u044c \u0446\u0435\u043b\u044b\u043c \u0447\u0438\u0441\u043b\u043e\u043c.")
                return
        self.EndModal(wx.ID_OK)

    def get_value(self) -> Player:
        self.player.full_name = self.full_name.GetValue().strip()
        self.player.rating = int(self.rating.GetValue().strip()) if self.rating.GetValue().strip() else None
        self.player.city = self.city.GetValue().strip()
        self.player.organization = ""
        self.player.gender = ""
        self.player.birth_date = ""
        self.player.comment = ""
        self.player.status = self.status_map[self.status.GetStringSelection()]
        return self.player


class MatchesPanel(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        context: AppContext,
        tournament: Tournament,
        players_panel: PlayersPanel,
    ):
        super().__init__(parent)
        self.context = context
        self.tournament = tournament
        self.players_panel = players_panel
        self.match_ids: List[int] = []
        self.player_names: Dict[int, str] = {}
        self.list_ctrl = wx.Choice(self)
        self.seeding_map = {label: value for value, label in SEEDING_MODES}
        self.seeding_choice: Optional[wx.Choice] = None
        self.primary_button: Optional[wx.Button] = None
        self.selection_status: Optional[wx.StaticText] = None
        self.selection_details: Optional[wx.TextCtrl] = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        options_row = wx.BoxSizer(wx.HORIZONTAL)
        seeding_label = wx.StaticText(self, label="Тип посева")
        clear_accessibility(seeding_label)
        options_row.Add(seeding_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.seeding_choice = wx.Choice(self, choices=[label for _, label in SEEDING_MODES])
        bind_accessible_focus(self.seeding_choice, "Тип посева для автоматического формирования матчей")
        self.seeding_choice.Bind(wx.EVT_CHOICE, self.on_change_seeding_mode)
        options_row.Add(self.seeding_choice, 0)
        root.Add(options_row, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 12)
        bind_accessible_focus(self.list_ctrl, "Список матчей")
        self.list_ctrl.Bind(wx.EVT_CHOICE, self.on_select_match)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_list_focus)
        root.Add(self.list_ctrl, 0, wx.ALL | wx.EXPAND, 12)
        self.selection_status = wx.StaticText(self, label="Матчи не созданы")
        bind_accessible_focus(self.selection_status, "Текущий матч")
        root.Add(self.selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.selection_details = wx.TextCtrl(
            self,
            value="",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE,
        )
        bind_accessible_focus(self.selection_details, "Подробности выбранного матча")
        root.Add(self.selection_details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        buttons = wx.GridSizer(0, 4, 8, 8)
        for label, accessible_label, handler in [
            ("Сформировать матчи", "Сформировать матчи автоматически по выбранному типу посева", self.on_generate_matches),
            ("Следующий этап", "Сформировать следующий этап автоматически", self.on_generate_next_stage),
            ("Добавить матч", "Создать матч вручную", self.on_add_match),
            ("Внести результат", "Внести итоговый результат выбранного матча", self.on_record_result),
            ("Открыть лайв-режим", "Открыть выбранный матч для лайв-судейства", self.on_open_match),
            ("Сохранить отчет", "Сохранить текстовый отчет по турниру", self.on_report),
            ("Удалить матч", "Удалить выбранный матч", self.on_delete_match),
            ("Обновить список", "Обновить список матчей", self.on_refresh),
        ]:
            button = wx.Button(self, label=label)
            bind_accessible_focus(button, accessible_label)
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

    def _player_name(self, player_id: int) -> str:
        for player in self.context.tournament_service.list_players(self.tournament.id or 0):
            if player.id == player_id:
                return player.full_name
        return str(player_id)

    def refresh(self) -> None:
        if self.seeding_choice:
            seeding_label = next(
                (label for value, label in SEEDING_MODES if value == self.tournament.seeding_mode),
                SEEDING_MODES[0][1],
            )
            self.seeding_choice.SetStringSelection(seeding_label)
        self.list_ctrl.Clear()
        self.match_ids = []
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        self.player_names = {player.id or 0: player.full_name for player in players}
        matches = self.context.match_service.list_matches(self.tournament.id or 0)
        for match in matches:
            self.match_ids.append(match.id or 0)
            status_label = MATCH_STATUS_LABELS.get(match.status, match.status)
            self.list_ctrl.Append(
                f"{self._player_name(match.player_a_id)} против {self._player_name(match.player_b_id)} | "
                f"{match.stage or 'Стадия не указана'} | {status_label}"
            )
        if self.list_ctrl.GetCount() > 0:
            self.list_ctrl.SetSelection(0)
            self._announce_selected_match()
        elif self.selection_status:
            self.selection_status.SetLabel("Матчи не созданы")
            if self.selection_details:
                self.selection_details.SetValue(
                    "Матчи еще не созданы.\n\n"
                    "Выберите тип посева и нажмите «Сформировать матчи», "
                    "либо добавьте матч вручную."
                )
            set_accessible_name(self.list_ctrl, "Список матчей пуст")

    def selected_match_id(self) -> Optional[int]:
        index = self.list_ctrl.GetSelection()
        return None if index == wx.NOT_FOUND else self.match_ids[index]

    def _announce_selected_match(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        match_id = self.match_ids[index]
        match = self.context.match_service.get_match(match_id)
        state = self.context.match_service.load_state(match_id)
        summary = self._match_summary(match, state)
        set_accessible_name(
            self.list_ctrl,
            f"Список матчей. Текущий матч: {self._player_name(match.player_a_id)} против {self._player_name(match.player_b_id)}",
        )
        if self.selection_status:
            self.selection_status.SetLabel(summary)
        if self.selection_details:
            self.selection_details.SetValue(self._match_details(match, state))

    def _match_summary(self, match, state: MatchState) -> str:
        return (
            f"{self._player_name(match.player_a_id)} против {self._player_name(match.player_b_id)}. "
            f"Стадия: {match.stage or 'не указана'}. "
            f"Стол {match.table_no or 'не указан'}. "
            f"Статус: {MATCH_STATUS_LABELS.get(match.status, match.status)}. "
            f"Счет по сетам {state.sets_won_a}:{state.sets_won_b}."
        )

    def _match_details(self, match, state: MatchState) -> str:
        competition_label = next(
            (label for value, label in COMPETITION_MODES if value == self.tournament.competition_mode),
            self.tournament.competition_mode,
        )
        lines = [
            f"Текущий матч турнира: {self._player_name(match.player_a_id)} против {self._player_name(match.player_b_id)}",
            "",
            f"Система турнира: {competition_label}",
            f"Игрок слева: {self._player_name(match.player_a_id)}",
            f"Игрок справа: {self._player_name(match.player_b_id)}",
            f"Стадия: {match.stage or 'не указана'}",
            f"Стол: {match.table_no or 'не указан'}",
            f"Статус: {MATCH_STATUS_LABELS.get(match.status, match.status)}",
            f"Счет по сетам: {state.sets_won_a}:{state.sets_won_b}",
            f"Текущий сет {state.current_set_no}: {state.current_set.score_a}:{state.current_set.score_b}",
        ]
        if state.winner_role:
            winner_id = match.player_a_id if state.winner_role == "A" else match.player_b_id
            lines.append(f"Победитель: {self._player_name(winner_id)}")
        set_lines = completed_set_lines(state)
        if set_lines:
            lines.append("Сеты:")
            lines.extend(set_lines)
        lines.extend(
            [
                "",
                "Используйте стрелки вверх и вниз для выбора другого матча.",
                "Тип посева применяется при автоматическом формировании матчей.",
            ]
        )
        return "\n".join(lines)

    def on_change_seeding_mode(self, event: wx.CommandEvent) -> None:
        del event
        if not self.seeding_choice:
            return
        self.tournament.seeding_mode = self.seeding_map[self.seeding_choice.GetStringSelection()]
        self.context.tournament_service.update_tournament(self.tournament)

    def on_select_match(self, event: wx.CommandEvent) -> None:
        self._announce_selected_match()
        event.Skip()

    def on_list_focus(self, event: wx.FocusEvent) -> None:
        self._announce_selected_match()
        event.Skip()

    def on_generate_matches(self, event: wx.CommandEvent) -> None:
        del event
        has_matches = bool(self.context.match_service.list_matches(self.tournament.id or 0))
        overwrite_existing = False
        if has_matches:
            overwrite_existing = confirm(self, "Матчи уже созданы. Пересоздать сетку и заменить текущие матчи?")
            if not overwrite_existing:
                return
        try:
            created = self.context.tournament_service.generate_group_stage(
                self.tournament.id or 0,
                overwrite_existing=overwrite_existing,
            )
        except Exception as exc:
            error_message(self, str(exc))
            return
        self.refresh()
        if self.selection_status:
            self.selection_status.SetLabel(f"Сформировано матчей: {created}")
        return
        seeding_label = next(
            (label for value, label in SEEDING_MODES if value == self.tournament.seeding_mode),
            SEEDING_MODES[0][1],
        )
        competition_label = next(
            (label for value, label in COMPETITION_MODES if value == self.tournament.competition_mode),
            self.tournament.competition_mode,
        )
        message(self, f"Сформировано матчей: {created}\nСистема турнира: {competition_label}\nТип посева: {seeding_label}")

    def on_generate_next_stage(self, event: wx.CommandEvent) -> None:
        del event
        try:
            created = self.context.tournament_service.generate_next_stage(self.tournament.id or 0)
        except Exception as exc:
            error_message(self, str(exc))
            return
        self.refresh()
        if self.selection_status:
            self.selection_status.SetLabel(f"Сформировано матчей следующего этапа: {created}")
        return
        message(self, f"\u0421\u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u043d\u043e \u043c\u0430\u0442\u0447\u0435\u0439 \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0433\u043e \u044d\u0442\u0430\u043f\u0430: {created}")

    def on_add_match(self, event: wx.CommandEvent) -> None:
        del event
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        if len(players) < 2:
            error_message(self, "Сначала добавьте минимум двух игроков.")
            return
        dialog = MatchDialog(self, self.tournament, players)
        if dialog.ShowModal() == wx.ID_OK:
            data = dialog.get_value()
            self.context.match_service.create_match(
                self.tournament,
                data.player_a_id,
                data.player_b_id,
                data.stage,
                data.table_no,
                data.referee,
                data.secretary,
            )
            self.refresh()
        dialog.Destroy()

    def on_open_match(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self.selected_match_id()
        if not match_id:
            error_message(self, "Выберите матч.")
            return
        frame = MatchScoringFrame(self, self.context, self.tournament, match_id)
        frame.Show()

    def on_record_result(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self.selected_match_id()
        if not match_id:
            error_message(self, "Выберите матч.")
            return
        match = self.context.match_service.get_match(match_id)
        dialog = ManualResultDialog(
            self,
            self.tournament,
            self._player_name(match.player_a_id),
            self._player_name(match.player_b_id),
        )
        if dialog.ShowModal() == wx.ID_OK:
            payload = dialog.get_value()
            self.context.match_service.record_match_result(
                match_id,
                payload["set_scores"],
                payload["winner_role"],
            )
            self.refresh()
            message(self, "Результат матча сохранен.")
        dialog.Destroy()

    def on_report(self, event: wx.CommandEvent) -> None:
        del event
        reports_dir = Path(self.context.settings.reports_path)
        if not reports_dir.is_absolute():
            reports_dir = self.context.paths.root / reports_dir
        target = self.context.report_service.generate_report(
            self.tournament.id or 0,
            reports_dir,
            False,
        )
        message(self, f"TXT-отчет сохранен:\n{target}")

    def on_delete_match(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self.selected_match_id()
        if not match_id:
            error_message(self, "Выберите матч.")
            return
        if confirm(self, "Удалить матч?"):
            with self.context.db.connection() as conn:
                conn.execute("DELETE FROM match_events WHERE match_id = ?", (match_id,))
                conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))
            self.refresh()

    def on_refresh(self, event: wx.CommandEvent) -> None:
        del event
        self.refresh()


class AccessibleMatchesPanel(MatchesPanel):
    def __init__(self, parent: wx.Window, context: AppContext, tournament: Tournament, players_panel: PlayersPanel):
        self.selected_match_memory: Optional[int] = None
        super().__init__(parent, context, tournament, players_panel)

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        options_row = wx.BoxSizer(wx.HORIZONTAL)
        seeding_label = wx.StaticText(self, label="Тип посева")
        clear_accessibility(seeding_label)
        options_row.Add(seeding_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.seeding_choice = wx.Choice(self, choices=[label for _, label in SEEDING_MODES])
        bind_accessible_focus(self.seeding_choice, "Тип посева для автоматического формирования матчей")
        self.seeding_choice.Bind(wx.EVT_CHOICE, self.on_change_seeding_mode)
        options_row.Add(self.seeding_choice, 0)
        root.Add(options_row, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 12)
        bind_accessible_focus(self.list_ctrl, "Список текущих матчей")
        self.list_ctrl.Bind(wx.EVT_CHOICE, self.on_select_match)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_list_focus)
        root.Add(self.list_ctrl, 0, wx.ALL | wx.EXPAND, 12)
        self.selection_status = wx.StaticText(self, label="Матчи не созданы")
        bind_accessible_focus(self.selection_status, "Текущий матч")
        root.Add(self.selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.selection_details = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE)
        bind_accessible_focus(self.selection_details, "Подробности выбранного матча")
        root.Add(self.selection_details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        buttons = wx.GridSizer(0, 4, 8, 8)
        for label, accessible_label, handler in [
            ("Сформировать матчи", "Сформировать матчи автоматически", self.on_generate_matches),
            ("Создать следующий тур", "Создать следующий тур или этап", self.on_generate_next_stage),
            ("Добавить матч", "Создать матч вручную", self.on_add_match),
            ("Внести результат", "Внести результат выбранного матча", self.on_record_result),
            ("Сохранить отчет", "Сохранить текстовый отчет по турниру", self.on_report),
            ("Удалить матч", "Удалить выбранный матч", self.on_delete_match),
            ("Обновить список", "Обновить список матчей", self.on_refresh),
        ]:
            button = wx.Button(self, label=label)
            bind_accessible_focus(button, accessible_label)
            button.Bind(wx.EVT_BUTTON, handler)
            if self.primary_button is None:
                self.primary_button = button
            buttons.Add(button, 0, wx.EXPAND)
        root.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.SetSizer(root)

    def refresh(self, preserve_selected: bool = True) -> None:
        remember_match_id = self.selected_match_id() if preserve_selected else None
        if self.seeding_choice:
            seeding_label = next((label for value, label in SEEDING_MODES if value == self.tournament.seeding_mode), SEEDING_MODES[0][1])
            self.seeding_choice.SetStringSelection(seeding_label)
        self.list_ctrl.Clear()
        self.match_ids = []
        matches = self.context.match_service.list_matches(self.tournament.id or 0)
        for match in matches:
            self.match_ids.append(match.id or 0)
            status_label = MATCH_STATUS_LABELS.get(match.status, match.status)
            label = f"{match.stage or 'Стадия не указана'} | стол {match.table_no or 'не указан'} | {self._player_name(match.player_a_id)} - {self._player_name(match.player_b_id)} | {status_label}"
            self.list_ctrl.Append(label)
        if self.list_ctrl.GetCount() > 0:
            selection_index = 0
            if remember_match_id and remember_match_id in self.match_ids:
                selection_index = self.match_ids.index(remember_match_id)
            self.list_ctrl.SetSelection(selection_index)
            self._announce_selected_match()
        elif self.selection_status:
            self.selection_status.SetLabel("Матчи не созданы")
            if self.selection_details:
                self.selection_details.SetValue("Матчи еще не созданы.")
            set_accessible_name(self.list_ctrl, "Список матчей пуст")

    def _match_details(self, match, state: MatchState, list_text: str) -> str:
        lines = [
            f"Текущий матч турнира: {list_text}",
            "",
            f"Игрок слева: {self._player_name(match.player_a_id)}",
            f"Игрок справа: {self._player_name(match.player_b_id)}",
            f"Стадия: {match.stage or 'не указана'}",
            f"Стол: {match.table_no or 'не указан'}",
            f"Статус: {MATCH_STATUS_LABELS.get(match.status, match.status)}",
            f"Счет по сетам: {state.sets_won_a}:{state.sets_won_b}",
        ]
        completed_sets = []
        for set_score in state.sets:
            if not set_score.winner_role:
                continue
            starter_name = self._player_name(match.player_a_id) if set_score.starter_role == "A" else self._player_name(match.player_b_id)
            completed_sets.append(
                f"Сет {set_score.set_no}: {set_score.score_a}:{set_score.score_b}, начинал {starter_name}"
            )
        if completed_sets:
            lines.append("")
            lines.append("Все сеты:")
            lines.extend(completed_sets)
        if state.winner_role:
            winner_id = match.player_a_id if state.winner_role == "A" else match.player_b_id
            lines.append("")
            lines.append(f"Победитель: {self._player_name(winner_id)}")
        return "\n".join(lines)

    def _match_summary(self, match, state: MatchState) -> str:
        return (
            f"{self._player_name(match.player_a_id)} против {self._player_name(match.player_b_id)}. "
            f"Стадия: {match.stage or 'не указана'}. "
            f"Стол {match.table_no or 'не указан'}. "
            f"Статус: {MATCH_STATUS_LABELS.get(match.status, match.status)}. "
            f"Счет по сетам {state.sets_won_a}:{state.sets_won_b}."
        )

    def on_record_result(self, event: wx.CommandEvent) -> None:
        self.selected_match_memory = self.selected_match_id()
        super().on_record_result(event)
        self.refresh(preserve_selected=True)

    def on_generate_matches(self, event: wx.CommandEvent) -> None:
        super().on_generate_matches(event)
        parent = self.GetParent().GetParent()
        if parent and hasattr(parent, "refresh_all"):
            parent.refresh_all()

    def on_generate_next_stage(self, event: wx.CommandEvent) -> None:
        super().on_generate_next_stage(event)
        parent = self.GetParent().GetParent()
        if parent and hasattr(parent, "refresh_all"):
            parent.refresh_all()

    def on_add_match(self, event: wx.CommandEvent) -> None:
        del event
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        if len(players) < 2:
            error_message(self, "Сначала добавьте минимум двух игроков.")
            return
        dialog = MatchDialog(self, self.tournament, players)
        if dialog.ShowModal() == wx.ID_OK:
            data = dialog.get_value()
            self.context.match_service.create_match(
                self.tournament,
                data.player_a_id,
                data.player_b_id,
                data.stage,
                data.table_no,
                data.referee,
                data.secretary,
            )
            self.refresh()
        parent = self.GetParent().GetParent()
        if parent and hasattr(parent, "refresh_all"):
            parent.refresh_all()

    def on_delete_match(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self.selected_match_id()
        if not match_id:
            error_message(self, "Выберите матч.")
            return
        if confirm(self, "Удалить матч?"):
            with self.context.db.connection() as conn:
                conn.execute("DELETE FROM match_events WHERE match_id = ?", (match_id,))
                conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))
            self.refresh()
        parent = self.GetParent().GetParent()
        if parent and hasattr(parent, "refresh_all"):
            parent.refresh_all()


class TablesPanel(wx.Panel):
    def __init__(self, parent: wx.Window, context: AppContext, tournament: Tournament):
        super().__init__(parent)
        self.context = context
        self.tournament = tournament
        self.items: List[str] = []
        self.player_names: Dict[int, str] = {}
        self.list_ctrl = wx.ListBox(self)
        self.view_choice: Optional[wx.Choice] = None
        self._table_jump_buffer = ""
        self._table_jump_reset = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        top = wx.BoxSizer(wx.HORIZONTAL)
        label = wx.StaticText(self, label="Вид списка")
        clear_accessibility(label)
        top.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.view_choice = wx.Choice(self, choices=["По столам", "По группам"])
        self.view_choice.SetSelection(0)
        bind_accessible_focus(self.view_choice, "Вид списка матчей")
        self.view_choice.Bind(wx.EVT_CHOICE, lambda event: self.refresh())
        top.Add(self.view_choice, 0)
        schedule_button = wx.Button(self, label="Настроить время")
        bind_accessible_focus(schedule_button, "Настроить время матчей и обеденный перерыв")
        schedule_button.Bind(wx.EVT_BUTTON, self.on_edit_schedule)
        top.Add(schedule_button, 0, wx.LEFT, 8)
        root.Add(top, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        bind_accessible_focus(self.list_ctrl, "Список матчей по столам")
        root.Add(self.list_ctrl, 1, wx.ALL | wx.EXPAND, 12)
        self.selection_status = wx.StaticText(self, label="")
        bind_accessible_focus(self.selection_status, "Текущий пункт списка столов")
        root.Add(self.selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.selection_details = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE)
        bind_accessible_focus(self.selection_details, "Подробности выбранного пункта списка столов")
        root.Add(self.selection_details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.SetSizer(root)
        self.list_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.list_ctrl.Bind(wx.EVT_LISTBOX, self.on_select_item)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_focus_list)

    def _schedule_lines(self, matches: List[object]) -> List[str]:
        try:
            start_minutes = sum(int(part) * value for part, value in zip(self.tournament.day_start_time.split(":"), (60, 1)))
        except Exception:
            start_minutes = 9 * 60
        lunch_start = lunch_end = None
        if self.tournament.lunch_break_enabled and self.tournament.lunch_start_time and self.tournament.lunch_end_time:
            try:
                lunch_start = sum(int(part) * value for part, value in zip(self.tournament.lunch_start_time.split(":"), (60, 1)))
                lunch_end = sum(int(part) * value for part, value in zip(self.tournament.lunch_end_time.split(":"), (60, 1)))
            except Exception:
                lunch_start = lunch_end = None
        mode = self.view_choice.GetStringSelection() if self.view_choice else "По столам"
        grouped: Dict[str, List[object]] = {}
        if mode == "По группам":
            for match in matches:
                key = match.stage or "Без группы"
                grouped.setdefault(key, []).append(match)
        else:
            for match in matches:
                grouped.setdefault(match.table_no or "1", []).append(match)
        lines: List[str] = []
        sort_key = (lambda value: int(value) if value.isdigit() else value) if mode != "По группам" else (lambda value: value)
        for group_key in sorted(grouped, key=sort_key):
            lines.append(f"{'Группа' if mode == 'По группам' else 'Стол'} {group_key}")
            time_cursor = start_minutes
            for match in grouped[group_key]:
                if lunch_start is not None and lunch_end is not None and time_cursor >= lunch_start and time_cursor < lunch_end:
                    lines.append(f"{self.tournament.lunch_start_time} - {self.tournament.lunch_end_time} обеденный перерыв")
                    time_cursor = lunch_end
                lines.append(f"{format_hhmm(time_cursor)} - {self._player_name(match.player_a_id)} - {self._player_name(match.player_b_id)}. Стол {match.table_no or 'не указан'}")
                time_cursor += self.tournament.match_duration_minutes
            lines.append("")
        return lines

    def _player_name(self, player_id: int) -> str:
        return self.player_names.get(player_id, str(player_id))

    def refresh(self) -> None:
        self.list_ctrl.Clear()
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        self.player_names = {player.id or 0: player.full_name for player in players}
        matches = self.context.match_service.list_matches(self.tournament.id or 0)
        for line in self._schedule_lines(matches):
            self.list_ctrl.Append(line)
        if self.list_ctrl.GetCount() > 0:
            self.list_ctrl.SetSelection(0)
            self._announce_current_item()

    def _announce_current_item(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        current = self.list_ctrl.GetString(index)
        set_accessible_name(self.list_ctrl, f"Список матчей. Текущий пункт: {current}")
        if self.selection_status:
            self.selection_status.SetLabel(current)
            set_accessible_name(self.selection_status, f"Текущий пункт списка столов: {current}")
            set_accessible_name(self.selection_status, f"Текущий пункт списка туров: {current}")
            set_accessible_name(self.selection_status, f"Текущий пункт списка столов: {current}")
        if self.selection_details:
            self.selection_details.SetValue(f"Текущий пункт:\n{current}\n\nИспользуйте цифры для быстрого перехода к столу в режиме списка по столам.")
            set_accessible_name(self.selection_details, f"Подробности выбранного пункта списка столов: {current}")

    def on_select_item(self, event: wx.CommandEvent) -> None:
        self._announce_current_item()
        event.Skip()

    def on_focus_list(self, event: wx.FocusEvent) -> None:
        self._announce_current_item()
        event.Skip()

    def on_char_hook(self, event: wx.KeyEvent) -> None:
        key_code = event.GetKeyCode()
        if ord("0") <= key_code <= ord("9") and (self.view_choice and self.view_choice.GetStringSelection() == "По столам"):
            self._table_jump_buffer += chr(key_code)
            if self._table_jump_reset:
                self._table_jump_reset.Stop()
            self._table_jump_reset = wx.CallLater(1200, self._reset_table_jump_buffer)
            target = self._table_jump_buffer
            for index in range(self.list_ctrl.GetCount()):
                if self.list_ctrl.GetString(index).startswith(f"Стол {target}"):
                    self.list_ctrl.SetSelection(index)
                    self._announce_current_item()
                    break
            return
        event.Skip()

    def _reset_table_jump_buffer(self) -> None:
        self._table_jump_buffer = ""

    def on_edit_schedule(self, event: wx.CommandEvent) -> None:
        del event
        dialog = ScheduleSettingsDialog(self, self.tournament)
        if dialog.ShowModal() == wx.ID_OK:
            self.tournament = self.context.tournament_service.update_tournament(dialog.get_value())
            frame = self.GetParent().GetParent()
            if frame and hasattr(frame, "tournament"):
                frame.tournament = self.tournament
            if frame and hasattr(frame, "refresh_all"):
                frame.refresh_all()
        dialog.Destroy()


class RoundsPanel(wx.Panel):
    def __init__(self, parent: wx.Window, context: AppContext, tournament: Tournament):
        super().__init__(parent)
        self.context = context
        self.tournament = tournament
        self.player_names: Dict[int, str] = {}
        self.list_ctrl = wx.ListBox(self)
        self.match_ids: List[Optional[int]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        bind_accessible_focus(self.list_ctrl, "Список туров и матчей")
        root.Add(self.list_ctrl, 1, wx.ALL | wx.EXPAND, 12)
        self.selection_status = wx.StaticText(self, label="")
        bind_accessible_focus(self.selection_status, "Текущий пункт списка туров")
        root.Add(self.selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.selection_details = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE)
        bind_accessible_focus(self.selection_details, "Подробности выбранного пункта списка туров")
        root.Add(self.selection_details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        result_button = wx.Button(self, label="Внести результат")
        bind_accessible_focus(result_button, "Внести результат для выбранного матча из списка туров")
        result_button.Bind(wx.EVT_BUTTON, self.on_record_result)
        buttons.Add(result_button, 0)
        root.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(root)
        self.list_ctrl.Bind(wx.EVT_LISTBOX, self.on_select_item)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_focus_list)

    def refresh(self) -> None:
        self.list_ctrl.Clear()
        self.match_ids = []
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        self.player_names = {player.id or 0: player.full_name for player in players}
        matches = self.context.match_service.list_matches(self.tournament.id or 0, include_archived=True)
        current_round = None
        for match in matches:
            if current_round != match.round_no:
                current_round = match.round_no
                self.list_ctrl.Append(f"Тур {current_round}")
                self.match_ids.append(None)
            status_label = MATCH_STATUS_LABELS.get(match.status, match.status)
            self.list_ctrl.Append(f"{match.stage} | стол {match.table_no} | {self._player_name(match.player_a_id)} - {self._player_name(match.player_b_id)} | {status_label}")
            self.match_ids.append(match.id or 0)
        if self.list_ctrl.GetCount() > 0:
            self.list_ctrl.SetSelection(0)
            self._announce_current_item()

    def _announce_current_item(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        current = self.list_ctrl.GetString(index)
        set_accessible_name(self.list_ctrl, f"Список туров. Текущий пункт: {current}")
        if self.selection_status:
            self.selection_status.SetLabel(current)
            set_accessible_name(self.selection_status, f"Текущий пункт списка туров: {current}")
        details = current
        match_id = self._selected_match_id()
        if match_id:
            match = self.context.match_service.get_match(match_id)
            state = self.context.match_service.load_state(match_id)
            details = (
                f"{current}\n\nИгрок слева: {self._player_name(match.player_a_id)}\n"
                f"Игрок справа: {self._player_name(match.player_b_id)}\n"
                f"Счет по сетам: {state.sets_won_a}:{state.sets_won_b}"
            )
        if self.selection_details:
            self.selection_details.SetValue(details)
            set_accessible_name(self.selection_details, f"Подробности выбранного пункта списка туров: {current}")

    def on_select_item(self, event: wx.CommandEvent) -> None:
        self._announce_current_item()
        event.Skip()

    def on_focus_list(self, event: wx.FocusEvent) -> None:
        self._announce_current_item()
        event.Skip()

    def _player_name(self, player_id: int) -> str:
        return self.player_names.get(player_id, str(player_id))

    def _selected_match_id(self) -> Optional[int]:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return None
        return self.match_ids[index]

    def on_record_result(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self._selected_match_id()
        if not match_id:
            error_message(self, "Выберите матч.")
            return
        match = self.context.match_service.get_match(match_id)
        dialog = ManualResultDialog(self, self.tournament, self._player_name(match.player_a_id), self._player_name(match.player_b_id))
        if dialog.ShowModal() == wx.ID_OK:
            payload = dialog.get_value()
            self.context.match_service.record_match_result(match_id, payload["set_scores"], payload["winner_role"])
            self.refresh()
        dialog.Destroy()


@dataclass
class MatchDraft:
    player_a_id: int
    player_b_id: int
    stage: str
    table_no: str
    referee: str
    secretary: str


class MatchDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, tournament: Tournament, players: List[Player]):
        super().__init__(parent, title="Создать матч", size=(560, 420))
        self.tournament = tournament
        self.players = players
        self.player_by_name = {player.full_name: player for player in players}
        self._build_ui()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            panel,
            label=(
                "Создание матча. Сначала выберите игрока слева и игрока справа, "
                "затем при необходимости заполните стадию, стол, судью и секретаря."
            ),
        )
        intro.Wrap(520)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)
        names = [player.full_name for player in self.players]
        self.player_a = wx.Choice(panel, choices=names)
        self.player_b = wx.Choice(panel, choices=names)
        bind_accessible_focus(self.player_a, "Игрок A, выбор игрока")
        bind_accessible_focus(self.player_b, "Игрок B, выбор игрока")
        self.player_a.SetSelection(0)
        self.player_b.SetSelection(1 if len(names) > 1 else 0)
        self.stage = wx.TextCtrl(panel, value="группа A")
        self.table_no = wx.TextCtrl(panel, value="1")
        self.referee = wx.TextCtrl(panel, value="")
        self.secretary = wx.TextCtrl(panel, value="")
        for label, control in [
            ("Игрок A", self.player_a),
            ("Игрок B", self.player_b),
            ("Стадия", self.stage),
            ("Номер стола", self.table_no),
            ("Судья", self.referee),
            ("Секретарь", self.secretary),
        ]:
            if isinstance(control, wx.TextCtrl):
                bind_accessible_focus(control, label)
            label_widget = wx.StaticText(panel, label=label)
            clear_accessibility(label_widget)
            form.Add(label_widget, 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(control, 1, wx.EXPAND)
        panel_root = wx.BoxSizer(wx.VERTICAL)
        panel_root.Add(intro, 0, wx.BOTTOM | wx.EXPAND, 12)
        panel_root.Add(form, 1, wx.EXPAND)
        panel.SetSizer(panel_root)
        root.Add(panel, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        schedule_initial_focus(self.player_a)

    def on_ok(self, event: wx.CommandEvent) -> None:
        if self.player_a.GetSelection() == self.player_b.GetSelection():
            error_message(self, "Игрок A и игрок B не могут совпадать.")
            return
        self.EndModal(wx.ID_OK)

    def get_value(self) -> MatchDraft:
        player_a = self.player_by_name[self.player_a.GetStringSelection()]
        player_b = self.player_by_name[self.player_b.GetStringSelection()]
        return MatchDraft(
            player_a_id=player_a.id or 0,
            player_b_id=player_b.id or 0,
            stage=self.stage.GetValue().strip(),
            table_no=self.table_no.GetValue().strip(),
            referee=self.referee.GetValue().strip(),
            secretary=self.secretary.GetValue().strip(),
        )


class ManualResultDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, tournament: Tournament, player_a_name: str, player_b_name: str):
        super().__init__(parent, title="\u0417\u0430\u043f\u0438\u0441\u0430\u0442\u044c \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u043c\u0430\u0442\u0447\u0430", size=(620, 560))
        self.tournament = tournament
        self.player_a_name = player_a_name
        self.player_b_name = player_b_name
        self.set_controls: List[tuple[wx.TextCtrl, wx.TextCtrl]] = []
        self.winner_choice: Optional[wx.Choice] = None
        self.first_starter_choice: Optional[wx.Choice] = None
        self._build_ui()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        names = wx.StaticText(panel, label=f"\u0418\u0433\u0440\u043e\u043a A: {self.player_a_name}\n\u0418\u0433\u0440\u043e\u043a B: {self.player_b_name}")
        intro = wx.StaticText(panel, label=(
            "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0441\u0447\u0435\u0442 \u043f\u043e \u0441\u0435\u0442\u0430\u043c \u0432 \u043f\u043e\u0440\u044f\u0434\u043a\u0435 \u0438\u0433\u0440\u043e\u043a A \u0438 \u0438\u0433\u0440\u043e\u043a B. "
            "\u041e\u0442\u0434\u0435\u043b\u044c\u043d\u043e \u0443\u043a\u0430\u0436\u0438\u0442\u0435, \u043a\u0442\u043e \u043d\u0430\u0447\u0438\u043d\u0430\u0435\u0442 \u043f\u0435\u0440\u0432\u044b\u0439 \u0441\u0435\u0442. "
            "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0435 \u0441\u0435\u0442\u044b \u0447\u0435\u0440\u0435\u0434\u0443\u044e\u0442\u0441\u044f \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u043f\u043e \u0440\u0435\u0433\u043b\u0430\u043c\u0435\u043d\u0442\u0443."
        ))
        intro.Wrap(580)
        root.Add(names, 0, wx.ALL | wx.EXPAND, 12)
        root.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        starter_label = wx.StaticText(panel, label="\u041a\u0442\u043e \u043d\u0430\u0447\u0438\u043d\u0430\u0435\u0442 \u043f\u0435\u0440\u0432\u044b\u0439 \u0441\u0435\u0442")
        self.first_starter_choice = wx.Choice(panel, choices=[f"\u0418\u0433\u0440\u043e\u043a A: {self.player_a_name}", f"\u0418\u0433\u0440\u043e\u043a B: {self.player_b_name}"])
        self.first_starter_choice.SetSelection(0)
        bind_accessible_focus(self.first_starter_choice, "\u041a\u0442\u043e \u043d\u0430\u0447\u0438\u043d\u0430\u0435\u0442 \u043f\u0435\u0440\u0432\u044b\u0439 \u0441\u0435\u0442")
        root.Add(starter_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        root.Add(self.first_starter_choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        form = wx.FlexGridSizer(0, 3, 8, 8)
        form.AddGrowableCol(1, 1)
        form.AddGrowableCol(2, 1)
        for set_no in range(1, self.tournament.match_format + 1):
            score_a = wx.TextCtrl(panel, value="")
            score_b = wx.TextCtrl(panel, value="")
            bind_accessible_focus(score_a, f"\u0421\u0435\u0442 {set_no}. \u041e\u0447\u043a\u0438 \u0438\u0433\u0440\u043e\u043a\u0430 A: {self.player_a_name}")
            bind_accessible_focus(score_b, f"\u0421\u0435\u0442 {set_no}. \u041e\u0447\u043a\u0438 \u0438\u0433\u0440\u043e\u043a\u0430 B: {self.player_b_name}")
            form.Add(wx.StaticText(panel, label=f"\u0421\u0435\u0442 {set_no}"), 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(score_a, 1, wx.EXPAND)
            form.Add(score_b, 1, wx.EXPAND)
            self.set_controls.append((score_a, score_b))
        root.Add(form, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.winner_choice = wx.Choice(panel, choices=[f"\u0418\u0433\u0440\u043e\u043a A: {self.player_a_name}", f"\u0418\u0433\u0440\u043e\u043a B: {self.player_b_name}"])
        self.winner_choice.SetSelection(0)
        bind_accessible_focus(self.winner_choice, "\u041f\u043e\u0431\u0435\u0434\u0438\u0442\u0435\u043b\u044c \u043c\u0430\u0442\u0447\u0430")
        root.Add(wx.StaticText(panel, label="\u041f\u043e\u0431\u0435\u0434\u0438\u0442\u0435\u043b\u044c \u043c\u0430\u0442\u0447\u0430"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        root.Add(self.winner_choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        panel.SetSizer(root)
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.Add(panel, 1, wx.EXPAND)
        frame.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(frame)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        schedule_initial_focus(self.set_controls[0][0])

    def on_ok(self, event: wx.CommandEvent) -> None:
        del event
        try:
            payload = self.get_value()
        except ValueError as exc:
            error_message(self, str(exc))
            return
        if not payload["set_scores"]:
            error_message(self, "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0445\u043e\u0442\u044f \u0431\u044b \u043e\u0434\u0438\u043d \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043d\u044b\u0439 \u0441\u0435\u0442.")
            return
        self.EndModal(wx.ID_OK)

    def get_value(self) -> dict:
        set_scores = []
        first_starter = "A" if self.first_starter_choice and self.first_starter_choice.GetSelection() == 0 else "B"
        for index, (score_a_ctrl, score_b_ctrl) in enumerate(self.set_controls, start=1):
            score_a_raw = score_a_ctrl.GetValue().strip()
            score_b_raw = score_b_ctrl.GetValue().strip()
            if not score_a_raw and not score_b_raw:
                continue
            if not score_a_raw or not score_b_raw:
                raise ValueError(f"\u0421\u0435\u0442 {index}: \u043d\u0443\u0436\u043d\u043e \u0437\u0430\u043f\u043e\u043b\u043d\u0438\u0442\u044c \u043e\u0447\u043a\u0438 \u043e\u0431\u043e\u0438\u0445 \u0438\u0433\u0440\u043e\u043a\u043e\u0432.")
            try:
                score_a = int(score_a_raw)
                score_b = int(score_b_raw)
            except ValueError as exc:
                raise ValueError(f"\u0421\u0435\u0442 {index}: \u043e\u0447\u043a\u0438 \u0434\u043e\u043b\u0436\u043d\u044b \u0431\u044b\u0442\u044c \u0446\u0435\u043b\u044b\u043c\u0438 \u0447\u0438\u0441\u043b\u0430\u043c\u0438.") from exc
            if score_a == score_b:
                raise ValueError(f"\u0421\u0435\u0442 {index}: \u043d\u0438\u0447\u044c\u044f \u043d\u0435\u0434\u043e\u043f\u0443\u0441\u0442\u0438\u043c\u0430.")
            starter_role = first_starter if index % 2 == 1 else ("B" if first_starter == "A" else "A")
            starter_score = score_a if starter_role == "A" else score_b
            receiver_score = score_b if starter_role == "A" else score_a
            set_scores.append({"starter_role": starter_role, "starter_score": starter_score, "receiver_score": receiver_score})
        winner_role = "A" if self.winner_choice and self.winner_choice.GetSelection() == 0 else "B"
        return {"set_scores": set_scores, "winner_role": winner_role}


class MatchScoringFrame(wx.Frame):
    def __init__(self, parent: wx.Window, context: AppContext, tournament: Tournament, match_id: int):
        super().__init__(parent, title=f"Live scoring матча #{match_id}", size=(1180, 760))
        self.context = context
        self.tournament = tournament
        self.match_id = match_id
        self.match = self.context.match_service.get_match(match_id)
        self.players = {
            player.id: player
            for player in self.context.tournament_service.list_players(tournament.id or 0)
        }
        self.status_text: Optional[wx.StaticText] = None
        self.score_text: Optional[wx.StaticText] = None
        self.serve_text: Optional[wx.StaticText] = None
        self.mode_text: Optional[wx.StaticText] = None
        self.action_parent: Optional[wx.Window] = None
        self.first_action_button: Optional[wx.Button] = None
        self.exit_button: Optional[wx.Button] = None
        self.journal = wx.ListBox(self)
        self.live_status = wx.StaticText(self, label="")
        self._build_ui()
        self.refresh_view()
        self.Centre()
        wx.CallAfter(self._set_initial_focus)
        self.Bind(wx.EVT_CLOSE, self.on_close_frame)

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        self.action_parent = panel
        root = wx.BoxSizer(wx.VERTICAL)

        quick_help = wx.StaticText(
            panel,
            label=(
                "Быстрый ввод матча. Основные кнопки: Гол игрока A, Гол игрока B, "
                "Ошибка игрока A, Ошибка игрока B, Штрафы, Тайм-ауты, Отмена действия."
            ),
        )
        quick_help.Wrap(1100)
        clear_accessibility(quick_help)
        root.Add(quick_help, 0, wx.ALL | wx.EXPAND, 12)

        info = wx.FlexGridSizer(0, 2, 8, 12)
        info.AddGrowableCol(1, 1)
        self.status_text = wx.StaticText(panel, label="")
        self.score_text = wx.StaticText(panel, label="")
        self.serve_text = wx.StaticText(panel, label="")
        self.mode_text = wx.StaticText(panel, label="")
        for label, control in [
            ("Турнир", wx.StaticText(panel, label=self.tournament.name)),
            ("Стадия", wx.StaticText(panel, label=self.match.stage)),
            ("Игрок слева", wx.StaticText(panel, label=self.players[self.match.player_a_id].full_name)),
            ("Игрок справа", wx.StaticText(panel, label=self.players[self.match.player_b_id].full_name)),
            ("Статус", self.status_text),
            ("Счет", self.score_text),
            ("Подача", self.serve_text),
            ("Режим", self.mode_text),
        ]:
            info.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            info.Add(control, 1, wx.EXPAND)
        root.Add(info, 0, wx.ALL | wx.EXPAND, 12)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        left = wx.BoxSizer(wx.VERTICAL)
        right = wx.BoxSizer(wx.VERTICAL)
        middle = wx.BoxSizer(wx.VERTICAL)

        left_title = wx.StaticText(panel, label="Игрок слева")
        right_title = wx.StaticText(panel, label="Игрок справа")
        middle_title = wx.StaticText(panel, label="Служебные действия")
        left.Add(left_title, 0, wx.BOTTOM, 8)
        middle.Add(middle_title, 0, wx.BOTTOM, 8)
        right.Add(right_title, 0, wx.BOTTOM, 8)

        self._add_action_button(left, "Гол игрока A, добавить 2 очка", lambda: self.apply(MatchCommand(EVENT_GOAL, actor_role="A")))
        self._add_action_button(left, "Ошибка игрока A, добавить 1 очко игроку B", lambda: self.open_error_menu("A"))
        self._add_action_button(left, "Штраф игроку A, добавить 2 очка игроку B", lambda: self.apply(MatchCommand(EVENT_PENALTY, actor_role="A")))
        self._add_action_button(left, "Предупреждение игроку A", lambda: self.open_warning_menu("A"))
        self._add_action_button(left, "Тайм-аут игрока A", lambda: self.apply(MatchCommand(EVENT_PLAYER_TIMEOUT, actor_role="A")))
        self._add_action_button(left, "Поражение по умолчанию игрока A", lambda: self.apply(MatchCommand(EVENT_DEFAULT_LOSS, actor_role="A")))

        self._add_action_button(right, "Гол игрока B, добавить 2 очка", lambda: self.apply(MatchCommand(EVENT_GOAL, actor_role="B")))
        self._add_action_button(right, "Ошибка игрока B, добавить 1 очко игроку A", lambda: self.open_error_menu("B"))
        self._add_action_button(right, "Штраф игроку B, добавить 2 очка игроку A", lambda: self.apply(MatchCommand(EVENT_PENALTY, actor_role="B")))
        self._add_action_button(right, "Предупреждение игроку B", lambda: self.open_warning_menu("B"))
        self._add_action_button(right, "Тайм-аут игрока B", lambda: self.apply(MatchCommand(EVENT_PLAYER_TIMEOUT, actor_role="B")))
        self._add_action_button(right, "Поражение по умолчанию игрока B", lambda: self.apply(MatchCommand(EVENT_DEFAULT_LOSS, actor_role="B")))

        for label, command in [
            ("Начать матч", MatchCommand(EVENT_MATCH_READY)),
            ("Судейский тайм-аут", MatchCommand(EVENT_REFEREE_TIMEOUT)),
            ("Медицинский тайм-аут игрока A", MatchCommand(EVENT_MEDICAL_TIMEOUT, actor_role="A")),
            ("Медицинский тайм-аут игрока B", MatchCommand(EVENT_MEDICAL_TIMEOUT, actor_role="B")),
            ("Смена сторон", MatchCommand(EVENT_SWITCH_SIDES)),
            ("Повторная подача", MatchCommand(EVENT_REPLAY_SERVE)),
            ("Потеря мяча", MatchCommand(EVENT_LOST_BALL)),
            ("Поломка ракетки", MatchCommand(EVENT_BAT_BREAK)),
            ("Поломка мяча", MatchCommand(EVENT_BALL_BREAK)),
            ("Возобновить игру", MatchCommand(EVENT_RESUME)),
            ("Завершить матч", MatchCommand(EVENT_FINISH_MATCH, confirm_override=True)),
            ("Отменить последнее действие", None),
            ("Повторить действие", None),
        ]:
            if label == "Отменить последнее действие":
                self._add_action_button(middle, label, self.on_undo)
            elif label == "Повторить действие":
                self._add_action_button(middle, label, self.on_redo)
            else:
                self._add_action_button(middle, label, lambda cmd=command: self.apply(cmd))

        actions.Add(left, 1, wx.RIGHT | wx.EXPAND, 8)
        actions.Add(middle, 1, wx.RIGHT | wx.EXPAND, 8)
        actions.Add(right, 1, wx.EXPAND)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        exit_row = wx.BoxSizer(wx.HORIZONTAL)
        self.exit_button = wx.Button(panel, label="Выйти из live режима")
        bind_accessible_focus(self.exit_button, "Выйти из live режима")
        self.exit_button.Bind(wx.EVT_BUTTON, self.on_close_live_mode)
        emergency_button = wx.Button(panel, label="Экстренно завершить матч и выйти")
        bind_accessible_focus(
            emergency_button,
            "Экстренно завершить матч и выйти. Все текущие данные матча будут удалены.",
        )
        emergency_button.Bind(wx.EVT_BUTTON, self.on_emergency_finish)
        exit_row.Add(self.exit_button, 0, wx.RIGHT, 8)
        exit_row.Add(emergency_button, 0)
        root.Add(exit_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        root.Add(wx.StaticText(panel, label="Журнал действий"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self.journal = wx.ListBox(panel)
        bind_accessible_focus(self.journal, "Журнал действий матча")
        root.Add(self.journal, 1, wx.ALL | wx.EXPAND, 12)
        self.live_status = wx.StaticText(panel, label="")
        self.live_status.SetName("Статус матча")
        root.Add(self.live_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        panel.SetSizer(root)
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)
        self._bind_hotkeys()

    def _bind_hotkeys(self) -> None:
        hotkey_ids = {
            "goal_a": wx.NewIdRef(),
            "goal_b": wx.NewIdRef(),
            "error_a": wx.NewIdRef(),
            "error_b": wx.NewIdRef(),
            "undo": wx.NewIdRef(),
            "redo": wx.NewIdRef(),
            "announce_score": wx.NewIdRef(),
            "focus_journal": wx.NewIdRef(),
        }
        entries = [
            (wx.ACCEL_ALT, ord("1"), int(hotkey_ids["goal_a"])),
            (wx.ACCEL_ALT, ord("2"), int(hotkey_ids["goal_b"])),
            (wx.ACCEL_ALT, ord("Q"), int(hotkey_ids["error_a"])),
            (wx.ACCEL_ALT, ord("W"), int(hotkey_ids["error_b"])),
            (wx.ACCEL_CTRL, ord("Z"), int(hotkey_ids["undo"])),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("Z"), int(hotkey_ids["redo"])),
            (wx.ACCEL_NORMAL, wx.WXK_F5, int(hotkey_ids["announce_score"])),
            (wx.ACCEL_NORMAL, wx.WXK_F6, int(hotkey_ids["focus_journal"])),
        ]
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))
        self.Bind(wx.EVT_MENU, lambda evt: self.apply(MatchCommand(EVENT_GOAL, actor_role="A")), id=int(hotkey_ids["goal_a"]))
        self.Bind(wx.EVT_MENU, lambda evt: self.apply(MatchCommand(EVENT_GOAL, actor_role="B")), id=int(hotkey_ids["goal_b"]))
        self.Bind(wx.EVT_MENU, lambda evt: self.open_error_menu("A"), id=int(hotkey_ids["error_a"]))
        self.Bind(wx.EVT_MENU, lambda evt: self.open_error_menu("B"), id=int(hotkey_ids["error_b"]))
        self.Bind(wx.EVT_MENU, self.on_undo, id=int(hotkey_ids["undo"]))
        self.Bind(wx.EVT_MENU, self.on_redo, id=int(hotkey_ids["redo"]))
        self.Bind(wx.EVT_MENU, self.on_announce_score, id=int(hotkey_ids["announce_score"]))
        self.Bind(wx.EVT_MENU, lambda evt: self.journal.SetFocus(), id=int(hotkey_ids["focus_journal"]))

    def _add_action_button(self, sizer: wx.BoxSizer, label: str, handler: Callable[[], None]) -> None:
        button = wx.Button(self.action_parent, label=label)
        bind_accessible_focus(button, label)
        button.Bind(wx.EVT_BUTTON, lambda event: handler())
        if self.first_action_button is None:
            self.first_action_button = button
        sizer.Add(button, 0, wx.BOTTOM | wx.EXPAND, 8)

    def _set_initial_focus(self) -> None:
        if self.first_action_button:
            self.first_action_button.SetFocus()

    def open_error_menu(self, actor_role: str) -> None:
        dialog = ErrorSubtypeDialog(self, actor_role)
        if dialog.ShowModal() == wx.ID_OK:
            self.apply(dialog.get_value())
        dialog.Destroy()

    def open_warning_menu(self, actor_role: str) -> None:
        dialog = WarningReasonDialog(self, actor_role)
        if dialog.ShowModal() == wx.ID_OK:
            self.apply(dialog.get_value())
        dialog.Destroy()

    def current_state(self) -> MatchState:
        return self.context.match_service.load_state(self.match_id)

    def apply(self, command: MatchCommand) -> None:
        try:
            if command.event_type == EVENT_FINISH_MATCH and not confirm(
                self, "Подтвердить завершение матча?"
            ):
                return
            state = self.context.match_service.apply_event(self.match_id, command)
            self.refresh_view(state)
            self.live_status.SetLabel(self._build_last_action_announcement(state))
        except MatchValidationError as exc:
            error_message(self, str(exc))
        except Exception as exc:
            error_message(self, f"Не удалось применить событие: {exc}")

    def on_undo(self, event: Optional[wx.CommandEvent] = None) -> None:
        del event
        try:
            state = self.context.match_service.undo(self.match_id)
            self.refresh_view(state)
            self.live_status.SetLabel(f"Последнее действие отменено. {state_summary(state)}")
        except Exception as exc:
            error_message(self, str(exc))

    def on_redo(self, event: Optional[wx.CommandEvent] = None) -> None:
        del event
        try:
            state = self.context.match_service.redo(self.match_id)
            self.refresh_view(state)
            self.live_status.SetLabel(f"Действие повторено. {self._build_last_action_announcement(state)}")
        except Exception as exc:
            error_message(self, str(exc))

    def on_announce_score(self, event: wx.CommandEvent) -> None:
        del event
        state = self.current_state()
        announcement = state_summary(state)
        self.live_status.SetLabel(announcement)
        set_accessible_name(self.live_status, announcement)

    def on_close_live_mode(self, event: wx.CommandEvent) -> None:
        del event
        self.Close()

    def on_emergency_finish(self, event: wx.CommandEvent) -> None:
        del event
        if not confirm(
            self,
            "Вы уверены, что хотите завершить матч? Данные будут удалены.",
            "Завершение матча",
        ):
            return
        try:
            self.context.match_service.cancel_match(self.match_id)
            self._refresh_parent_matches()
            self.Close()
        except Exception as exc:
            error_message(self, f"Не удалось завершить матч: {exc}")

    def on_close_frame(self, event: wx.CloseEvent) -> None:
        self._refresh_parent_matches()
        event.Skip()

    def _refresh_parent_matches(self) -> None:
        parent = self.GetParent()
        if parent and hasattr(parent, "refresh"):
            parent.refresh()

    def _build_last_action_announcement(self, state: MatchState) -> str:
        events = self.context.match_service.list_event_records(self.match_id)
        if not events:
            return state_summary(state)
        last_event = events[-1]
        parts = [f"Выполнено: {last_event.description}"]
        parts.append(f"Счет {state.current_set.score_a}:{state.current_set.score_b} в сете {state.current_set_no}")
        parts.append(f"По сетам {state.sets_won_a}:{state.sets_won_b}")
        parts.append(f"Подает игрок {state.current_server}, подача {state.serve_no}")
        if state.side_switch_pending:
            parts.append("Требуется смена сторон")
        if state.status in {MATCH_STATUS_COMPLETED, MATCH_STATUS_DEFAULTED} and state.winner_role:
            parts.append(f"Победитель: игрок {state.winner_role}")
        return ". ".join(parts)

    def refresh_view(self, state: Optional[MatchState] = None) -> None:
        if state is None:
            state = self.current_state()
        if self.status_text:
            self.status_text.SetLabel(MATCH_STATUS_LABELS.get(state.status, state.status))
        if self.score_text:
            self.score_text.SetLabel(
                f"Сет {state.current_set_no}: {state.current_set.score_a}:{state.current_set.score_b}; "
                f"по сетам {state.sets_won_a}:{state.sets_won_b}"
            )
        if self.serve_text:
            self.serve_text.SetLabel(
                f"Игрок {state.current_server}, подача {state.serve_no}-я"
            )
        if self.mode_text:
            self.mode_text.SetLabel(
                "стандартный IBSA" if self.tournament.rule_mode == "standard_ibsa" else "пользовательский"
            )
        self.journal.Clear()
        for event in self.context.match_service.list_event_records(self.match_id):
            self.journal.Append(
                f"{event.timestamp[11:19]} | Сет {event.set_no} | {event.description}"
            )
        announcement = state_summary(state)
        if state.side_switch_pending:
            announcement += " | Требуется смена сторон"
        if state.status in {MATCH_STATUS_COMPLETED, MATCH_STATUS_DEFAULTED} and state.winner_role:
            announcement += f" | Победитель: игрок {state.winner_role}"
        self.live_status.SetLabel(announcement)
        set_accessible_name(self.live_status, announcement)


class ErrorSubtypeDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, actor_role: str):
        super().__init__(parent, title="Выберите тип ошибки", size=(500, 360))
        self.actor_role = actor_role
        self.choice = wx.Choice(
            self,
            choices=[
                "irregular_serve",
                "center_board",
                "body_touch",
                "illegal_defense",
                "illegal_defense_goal",
                "out",
                "infringement",
                "bat_infraction",
                "ball_infraction",
            ],
        )
        self.choice.SetSelection(0)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label="Официальная категория ошибки"), 0, wx.ALL, 12)
        root.Add(self.choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)

    def get_value(self) -> MatchCommand:
        return MatchCommand(EVENT_ERROR, actor_role=self.actor_role, subtype=self.choice.GetStringSelection())


class WarningReasonDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, actor_role: str):
        super().__init__(parent, title="Основание предупреждения", size=(560, 360))
        self.actor_role = actor_role
        self.choice = wx.Choice(
            self,
            choices=[
                "side_play",
                "illegal_non_playing_hand_contact",
                "grabbing_ball",
                "pushing_table",
                "bat_noise",
                "talking",
                "body_outside_goal",
                "feet_off_floor",
                "other_interference",
            ],
        )
        self.choice.SetSelection(0)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label="Нарушение группы 19.3"), 0, wx.ALL, 12)
        root.Add(self.choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)

    def get_value(self) -> MatchCommand:
        return MatchCommand(EVENT_WARNING, actor_role=self.actor_role, reason=self.choice.GetStringSelection())


class TablesPanel(TablesPanel):
    def _announce_current_item(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        current = self.list_ctrl.GetString(index)
        set_accessible_name(self.list_ctrl, f"Список матчей. Текущий пункт: {current}")
        if self.selection_status:
            self.selection_status.SetLabel(current)
            set_accessible_name(self.selection_status, f"Текущий пункт списка столов: {current}")
        if self.selection_details:
            self.selection_details.SetValue(
                f"Текущий пункт:\n{current}\n\nИспользуйте цифры для быстрого перехода к столу в режиме списка по столам."
            )
            set_accessible_name(self.selection_details, f"Подробности выбранного пункта списка столов: {current}")

    def on_char_hook(self, event: wx.KeyEvent) -> None:
        key_code = event.GetKeyCode()
        digit = None
        if ord("0") <= key_code <= ord("9"):
            digit = chr(key_code)
        elif wx.WXK_NUMPAD0 <= key_code <= wx.WXK_NUMPAD9:
            digit = str(key_code - wx.WXK_NUMPAD0)
        if digit is not None and (self.view_choice and self.view_choice.GetStringSelection() == "По столам"):
            self._table_jump_buffer += digit
            if self._table_jump_reset:
                self._table_jump_reset.Stop()
            self._table_jump_reset = wx.CallLater(1200, self._reset_table_jump_buffer)
            target = self._table_jump_buffer
            for index in range(self.list_ctrl.GetCount()):
                if self.list_ctrl.GetString(index).startswith(f"Стол {target}"):
                    self.list_ctrl.SetSelection(index)
                    self._announce_current_item()
                    break
            return
        event.Skip()


class AccessibleMatchesPanel(MatchesPanel):
    def __init__(self, parent: wx.Window, context: AppContext, tournament: Tournament, players_panel: PlayersPanel):
        self.selected_match_memory: Optional[int] = None
        super().__init__(parent, context, tournament, players_panel)

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        bind_accessible_focus(self.list_ctrl, "Список текущих матчей")
        self.list_ctrl.Bind(wx.EVT_CHOICE, self.on_select_match)
        self.list_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_list_focus)
        root.Add(self.list_ctrl, 0, wx.ALL | wx.EXPAND, 12)

        result_button = wx.Button(self, label="Внести итоговый результат")
        bind_accessible_focus(result_button, "Внести итоговый результат для выбранного матча")
        result_button.Bind(wx.EVT_BUTTON, self.on_record_result)
        self.primary_button = result_button
        root.Add(result_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.selection_details = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE)
        bind_accessible_focus(self.selection_details, "Подробности выбранного матча")
        root.Add(self.selection_details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.selection_status = wx.StaticText(self, label="Матчи не созданы")
        bind_accessible_focus(self.selection_status, "Статус вкладки матчей")
        root.Add(self.selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        buttons = wx.GridSizer(0, 3, 8, 8)
        for label, accessible_label, handler in [
            ("Создать следующий тур", "Сформировать следующий тур автоматически", self.on_generate_next_stage),
            ("Сохранить отчет", "Сохранить текстовый отчет", self.on_report),
            ("Удалить матч", "Удалить выбранный матч", self.on_delete_match),
            ("Обновить список", "Обновить список матчей", self.on_refresh),
            ("Создать матч", "Создать матч вручную", self.on_add_match),
        ]:
            button = wx.Button(self, label=label)
            bind_accessible_focus(button, accessible_label)
            button.Bind(wx.EVT_BUTTON, handler)
            buttons.Add(button, 0, wx.EXPAND)
        root.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        seeding_panel = wx.Panel(self)
        seeding_sizer = wx.BoxSizer(wx.HORIZONTAL)
        seeding_label = wx.StaticText(seeding_panel, label="Тип посева")
        clear_accessibility(seeding_label)
        seeding_sizer.Add(seeding_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.seeding_choice = wx.Choice(seeding_panel, choices=[label for _, label in SEEDING_MODES])
        bind_accessible_focus(self.seeding_choice, "Тип посева для автоматического формирования матчей")
        self.seeding_choice.Bind(wx.EVT_CHOICE, self.on_change_seeding_mode)
        seeding_sizer.Add(self.seeding_choice, 1, wx.RIGHT, 8)
        generate_button = wx.Button(seeding_panel, label="Сформировать матчи")
        bind_accessible_focus(generate_button, "Сформировать матчи автоматически по выбранному типу посева")
        generate_button.Bind(wx.EVT_BUTTON, self.on_generate_matches)
        seeding_sizer.Add(generate_button, 0)
        seeding_panel.SetSizer(seeding_sizer)
        root.Add(seeding_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.SetSizer(root)

    def _set_status(self, text: str) -> None:
        if self.selection_status:
            self.selection_status.SetLabel(text)
            set_accessible_name(self.selection_status, text)

    def on_record_result(self, event: wx.CommandEvent) -> None:
        self.selected_match_memory = self.selected_match_id()
        super().on_record_result(event)
        self.refresh(preserve_selected=True)
        self._set_status("Итоговый результат сохранен.")

    def on_generate_matches(self, event: wx.CommandEvent) -> None:
        super().on_generate_matches(event)
        parent = self.GetParent().GetParent()
        if parent and hasattr(parent, "refresh_all"):
            parent.refresh_all()
        self._set_status("Матчи сформированы автоматически.")

    def on_generate_next_stage(self, event: wx.CommandEvent) -> None:
        super().on_generate_next_stage(event)
        parent = self.GetParent().GetParent()
        if parent and hasattr(parent, "refresh_all"):
            parent.refresh_all()
        self._set_status("Следующий тур сформирован.")

    def on_report(self, event: wx.CommandEvent) -> None:
        super().on_report(event)
        self._set_status("Текстовый отчет сохранен.")

    def on_refresh(self, event: wx.CommandEvent) -> None:
        super().on_refresh(event)
        self._set_status("Список матчей обновлен.")


class TablesPanel(TablesPanel):
    def __init__(self, parent: wx.Window, context: AppContext, tournament: Tournament):
        self.item_match_ids: List[Optional[int]] = []
        super().__init__(parent, context, tournament)

    def _build_ui(self) -> None:
        super()._build_ui()
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        result_button = wx.Button(self, label="Внести результат")
        bind_accessible_focus(result_button, "Внести итоговый результат для выбранного матча из списка столов")
        result_button.Bind(wx.EVT_BUTTON, self.on_record_result)
        buttons.Add(result_button, 0, wx.RIGHT, 8)
        refresh_button = wx.Button(self, label="Обновить")
        bind_accessible_focus(refresh_button, "Обновить список столов")
        refresh_button.Bind(wx.EVT_BUTTON, self.on_refresh)
        buttons.Add(refresh_button, 0)
        self.GetSizer().Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.Layout()

    def _schedule_lines(self, matches: List[object]) -> List[tuple[str, Optional[int]]]:
        try:
            start_minutes = sum(int(part) * value for part, value in zip(self.tournament.day_start_time.split(":"), (60, 1)))
        except Exception:
            start_minutes = 9 * 60
        lunch_start = lunch_end = None
        if self.tournament.lunch_break_enabled and self.tournament.lunch_start_time and self.tournament.lunch_end_time:
            try:
                lunch_start = sum(int(part) * value for part, value in zip(self.tournament.lunch_start_time.split(":"), (60, 1)))
                lunch_end = sum(int(part) * value for part, value in zip(self.tournament.lunch_end_time.split(":"), (60, 1)))
            except Exception:
                lunch_start = lunch_end = None
        mode = self.view_choice.GetStringSelection() if self.view_choice else "По столам"
        grouped: Dict[str, List[object]] = {}
        if mode == "По группам":
            for match in matches:
                key = match.stage or "Без группы"
                grouped.setdefault(key, []).append(match)
        else:
            for match in matches:
                grouped.setdefault(match.table_no or "1", []).append(match)
        lines: List[tuple[str, Optional[int]]] = []
        sort_key = (lambda value: int(value) if value.isdigit() else value) if mode != "По группам" else (lambda value: value)
        for group_key in sorted(grouped, key=sort_key):
            lines.append((f"{'Группа' if mode == 'По группам' else 'Стол'} {group_key}", None))
            time_cursor = start_minutes
            for match in grouped[group_key]:
                if lunch_start is not None and lunch_end is not None and lunch_start <= time_cursor < lunch_end:
                    lines.append((f"{self.tournament.lunch_start_time} - {self.tournament.lunch_end_time} обеденный перерыв", None))
                    time_cursor = lunch_end
                lines.append((f"{format_hhmm(time_cursor)} - {self._player_name(match.player_a_id)} - {self._player_name(match.player_b_id)}. Стол {match.table_no or 'не указан'}", match.id or 0))
                time_cursor += self.tournament.match_duration_minutes
            lines.append(("", None))
        return lines

    def refresh(self) -> None:
        self.list_ctrl.Clear()
        self.item_match_ids = []
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        self.player_names = {player.id or 0: player.full_name for player in players}
        matches = self.context.match_service.list_matches(self.tournament.id or 0)
        for line, match_id in self._schedule_lines(matches):
            self.list_ctrl.Append(line)
            self.item_match_ids.append(match_id)
        if self.list_ctrl.GetCount() > 0:
            self.list_ctrl.SetSelection(0)
            self._announce_current_item()

    def _selected_match_id(self) -> Optional[int]:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self.item_match_ids):
            return None
        return self.item_match_ids[index]

    def _announce_current_item(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        current = self.list_ctrl.GetString(index)
        set_accessible_name(self.list_ctrl, f"Список матчей. Текущий пункт: {current}")
        if self.selection_status:
            self.selection_status.SetLabel(current)
            set_accessible_name(self.selection_status, f"Текущий пункт списка столов: {current}")
        details = f"Текущий пункт:\n{current}\n\nИспользуйте цифры для быстрого перехода к столу."
        match_id = self._selected_match_id()
        if match_id:
            match = self.context.match_service.get_match(match_id)
            state = self.context.match_service.load_state(match_id)
            details = f"{current}\n\nСтадия: {match.stage or 'не указана'}\nСчет по сетам: {state.sets_won_a}:{state.sets_won_b}"
        if self.selection_details:
            self.selection_details.SetValue(details)
            set_accessible_name(self.selection_details, f"Подробности выбранного пункта списка столов: {current}")

    def on_record_result(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self._selected_match_id()
        if not match_id:
            error_message(self, "Выберите строку с матчем.")
            return
        match = self.context.match_service.get_match(match_id)
        dialog = ManualResultDialog(self, self.tournament, self._player_name(match.player_a_id), self._player_name(match.player_b_id))
        if dialog.ShowModal() == wx.ID_OK:
            payload = dialog.get_value()
            self.context.match_service.record_match_result(match_id, payload["set_scores"], payload["winner_role"])
            frame = self.GetParent().GetParent()
            if frame and hasattr(frame, "refresh_all"):
                frame.refresh_all()
            else:
                self.refresh()
            if self.selection_status:
                self.selection_status.SetLabel("Результат матча сохранен.")
                set_accessible_name(self.selection_status, "Результат матча сохранен.")
        dialog.Destroy()

    def on_refresh(self, event: wx.CommandEvent) -> None:
        del event
        self.refresh()
        if self.selection_status:
            self.selection_status.SetLabel("Список столов обновлен.")
            set_accessible_name(self.selection_status, "Список столов обновлен.")


class RoundsPanel(RoundsPanel):
    def _build_ui(self) -> None:
        super()._build_ui()
        row = wx.BoxSizer(wx.HORIZONTAL)
        refresh_button = wx.Button(self, label="Обновить")
        bind_accessible_focus(refresh_button, "Обновить список туров")
        refresh_button.Bind(wx.EVT_BUTTON, self.on_refresh)
        row.Add(refresh_button, 0)
        self.GetSizer().Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.Layout()

    def refresh(self, preserve_selected: bool = True) -> None:
        remember_match_id = self._selected_match_id() if preserve_selected else None
        self.list_ctrl.Clear()
        self.match_ids = []
        matches = self.context.match_service.list_matches(self.tournament.id or 0, include_archived=True)
        current_round = None
        for match in matches:
            if current_round != match.round_no:
                current_round = match.round_no
                self.list_ctrl.Append(f"Тур {current_round}")
                self.match_ids.append(None)
            status_label = MATCH_STATUS_LABELS.get(match.status, match.status)
            self.list_ctrl.Append(f"{match.stage} | стол {match.table_no} | {self._player_name(match.player_a_id)} - {self._player_name(match.player_b_id)} | {status_label}")
            self.match_ids.append(match.id or 0)
        if self.list_ctrl.GetCount() > 0:
            selection = 0
            if remember_match_id and remember_match_id in self.match_ids:
                selection = self.match_ids.index(remember_match_id)
            self.list_ctrl.SetSelection(selection)
            self._announce_current_item()

    def on_record_result(self, event: wx.CommandEvent) -> None:
        del event
        match_id = self._selected_match_id()
        if not match_id:
            error_message(self, "Выберите матч.")
            return
        match = self.context.match_service.get_match(match_id)
        dialog = ManualResultDialog(self, self.tournament, self._player_name(match.player_a_id), self._player_name(match.player_b_id))
        if dialog.ShowModal() == wx.ID_OK:
            payload = dialog.get_value()
            self.context.match_service.record_match_result(match_id, payload["set_scores"], payload["winner_role"])
            frame = self.GetParent().GetParent()
            if frame and hasattr(frame, "refresh_all"):
                frame.refresh_all()
            else:
                self.refresh()
            if self.selection_status:
                self.selection_status.SetLabel("Результат матча сохранен.")
                set_accessible_name(self.selection_status, "Результат матча сохранен.")
        dialog.Destroy()

    def on_refresh(self, event: wx.CommandEvent) -> None:
        del event
        self.refresh()
        if self.selection_status:
            self.selection_status.SetLabel("Список туров обновлен.")
            set_accessible_name(self.selection_status, "Список туров обновлен.")


class AccessibleTournamentDialog(AccessibleTournamentDialog):
    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        content = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(0, 2, 8, 8)
        form.AddGrowableCol(1, 1)

        self.name_ctrl = self._text_field(panel, form, "Название турнира", self.tournament.name)
        self.date_ctrl = self._text_field(panel, form, "Дата турнира", self.tournament.event_date or date.today().isoformat())
        self.location_ctrl = self._text_field(panel, form, "Место проведения", self.tournament.location)

        format_label = next((label for value, label in TOURNAMENT_FORMATS if value == self.tournament.tournament_format), TOURNAMENT_FORMATS[0][1])
        self.format_choice = wx.Choice(panel, choices=[label for _, label in TOURNAMENT_FORMATS])
        self.format_choice.SetStringSelection(format_label)
        bind_accessible_focus(self.format_choice, "Тип турнира")
        form.Add(wx.StaticText(panel, label="Тип турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.format_choice, 1, wx.EXPAND)

        competition_mode_label = next((label for value, label in COMPETITION_MODES if value == self.tournament.competition_mode), COMPETITION_MODES[0][1])
        self.competition_mode_choice = wx.Choice(panel, choices=[label for _, label in COMPETITION_MODES])
        self.competition_mode_choice.SetStringSelection(competition_mode_label)
        bind_accessible_focus(self.competition_mode_choice, "Система турнира")
        form.Add(wx.StaticText(panel, label="Система турнира"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.competition_mode_choice, 1, wx.EXPAND)

        self.table_count_ctrl = self._text_field(panel, form, "Количество игровых столов", str(self.tournament.table_count or 1))

        seeding_label = next((label for value, label in SEEDING_MODES if value == self.tournament.seeding_mode), SEEDING_MODES[0][1])
        self.seeding_choice = wx.Choice(panel, choices=[label for _, label in SEEDING_MODES])
        self.seeding_choice.SetStringSelection(seeding_label)
        bind_accessible_focus(self.seeding_choice, "Тип посева")
        form.Add(wx.StaticText(panel, label="Тип посева"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.seeding_choice, 1, wx.EXPAND)

        match_format_label = next((label for value, label in MATCH_FORMAT_CHOICES if value == self.tournament.match_format), MATCH_FORMAT_CHOICES[0][1])
        self.match_format_choice = wx.Choice(panel, choices=[label for _, label in MATCH_FORMAT_CHOICES])
        self.match_format_choice.SetStringSelection(match_format_label)
        bind_accessible_focus(self.match_format_choice, "Формат матча")
        form.Add(wx.StaticText(panel, label="Формат матча"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.match_format_choice, 1, wx.EXPAND)

        self.match_duration_ctrl = self._text_field(panel, form, "Минут на матч", str(self.tournament.match_duration_minutes or 30))
        self.day_start_ctrl = self._text_field(panel, form, "Начало игрового дня", self.tournament.day_start_time or "09:00")

        self.lunch_enabled = wx.CheckBox(panel, label="Обеденный перерыв")
        self.lunch_enabled.SetValue(self.tournament.lunch_break_enabled)
        bind_accessible_focus(self.lunch_enabled, self._lunch_checkbox_label())
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
        schedule_initial_focus(self.name_ctrl)

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


class AccessiblePlayersPanel(AccessiblePlayersPanel):
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
            status_label = next((label for value, label in PLAYER_STATUS_CHOICES if value == player.status), player.status)
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
            self.selection_status.SetLabel("Игроки не добавлены")
            if self.selection_details:
                self.selection_details.SetValue("Список игроков пуст.")
            set_accessible_name(self.list_ctrl, "Список игроков пуст")

    def _announce_selected_player(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        player = self.selected_player()
        if not player:
            return
        text = self.list_ctrl.GetString(index)
        compact = compact_player_announcement(player)
        set_accessible_name(self.list_ctrl, f"Список игроков. Текущий игрок: {compact}")
        if self.selection_status:
            self.selection_status.SetLabel(f"Выбран: {compact}")
        if self.selection_details:
            self.selection_details.SetValue(
                f"Текущий игрок турнира:\n{text}\n\nИспользуйте стрелки вверх и вниз для перехода по игрокам."
            )
            set_accessible_name(self.selection_details, "Подробности выбранного игрока")


class AccessibleMatchesPanel(AccessibleMatchesPanel):
    def refresh(self, preserve_selected: bool = False) -> None:
        remember_match_id = self.selected_match_id() if preserve_selected else None
        if self.seeding_choice:
            seeding_label = next(
                (label for value, label in SEEDING_MODES if value == self.tournament.seeding_mode),
                SEEDING_MODES[0][1],
            )
            self.seeding_choice.SetStringSelection(seeding_label)
        self.list_ctrl.Clear()
        self.match_ids = []
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        self.player_names = {player.id or 0: player.full_name for player in players}
        matches = self.context.match_service.list_matches(self.tournament.id or 0)
        for match in matches:
            self.match_ids.append(match.id or 0)
            status_label = MATCH_STATUS_LABELS.get(match.status, match.status)
            self.list_ctrl.Append(
                f"{self._player_name(match.player_a_id)} против {self._player_name(match.player_b_id)} | "
                f"{match.stage or 'Стадия не указана'} | {status_label}"
            )
        if self.list_ctrl.GetCount() > 0:
            selection = 0
            if remember_match_id and remember_match_id in self.match_ids:
                selection = self.match_ids.index(remember_match_id)
            self.list_ctrl.SetSelection(selection)
            self._announce_selected_match()
        elif self.selection_status:
            self.selection_status.SetLabel("Матчи не созданы")
            if self.selection_details:
                self.selection_details.SetValue(
                    "Матчи еще не созданы.\n\nВыберите тип посева и нажмите «Сформировать матчи», либо добавьте матч вручную."
                )
            set_accessible_name(self.list_ctrl, "Список матчей пуст")

    def _player_name(self, player_id: int) -> str:
        return self.player_names.get(player_id, str(player_id))

    def _announce_selected_match(self) -> None:
        index = self.list_ctrl.GetSelection()
        if index == wx.NOT_FOUND:
            return
        match_id = self.match_ids[index]
        match = self.context.match_service.get_match(match_id)
        state = self.context.match_service.load_state(match_id)
        summary = self._match_summary(match, state)
        set_accessible_name(
            self.list_ctrl,
            f"Список матчей. Текущий матч: {self._player_name(match.player_a_id)} против {self._player_name(match.player_b_id)}",
        )
        if self.selection_status:
            self.selection_status.SetLabel(summary)
        if self.selection_details:
            self.selection_details.SetValue(self._match_details(match, state))
            set_accessible_name(self.selection_details, "Подробности выбранного матча")

    def _match_details(self, match, state: MatchState) -> str:
        competition_label = next(
            (label for value, label in COMPETITION_MODES if value == self.tournament.competition_mode),
            self.tournament.competition_mode,
        )
        lines = [
            f"Текущий матч турнира: {self._player_name(match.player_a_id)} против {self._player_name(match.player_b_id)}",
            "",
            f"Система турнира: {competition_label}",
            f"Игрок слева: {self._player_name(match.player_a_id)}",
            f"Игрок справа: {self._player_name(match.player_b_id)}",
            f"Стадия: {match.stage or 'не указана'}",
            f"Стол: {match.table_no or 'не указан'}",
            f"Статус: {MATCH_STATUS_LABELS.get(match.status, match.status)}",
            f"Счет по сетам: {state.sets_won_a}:{state.sets_won_b}",
        ]
        set_lines = completed_set_lines(state)
        if set_lines:
            lines.append("Сеты:")
            lines.extend(set_lines)
        else:
            lines.append(f"Текущий сет {state.current_set_no}: {state.current_set.score_a}:{state.current_set.score_b}")
        if state.winner_role:
            winner_id = match.player_a_id if state.winner_role == "A" else match.player_b_id
            lines.append(f"Победитель: {self._player_name(winner_id)}")
        lines.extend(
            [
                "",
                "Используйте стрелки вверх и вниз для выбора другого матча.",
                "Тип посева применяется при автоматическом формировании матчей.",
            ]
        )
        return "\n".join(lines)

    def on_generate_matches(self, event: wx.CommandEvent) -> None:
        del event
        has_matches = bool(self.context.match_service.list_matches(self.tournament.id or 0))
        overwrite_existing = False
        if has_matches:
            overwrite_existing = confirm(self, "Матчи уже созданы. Пересоздать сетку и заменить текущие матчи?")
            if not overwrite_existing:
                return
        try:
            created = self.context.tournament_service.generate_group_stage(
                self.tournament.id or 0,
                overwrite_existing=overwrite_existing,
            )
        except Exception as exc:
            error_message(self, str(exc))
            return
        parent = self.GetParent().GetParent()
        if parent and hasattr(parent, "refresh_all"):
            parent.refresh_all()
        else:
            self.refresh()
        self._set_status(f"Сформировано матчей: {created}")


class TablesPanel(TablesPanel):
    def refresh(self) -> None:
        self.list_ctrl.Clear()
        self.item_match_ids = []
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        self.player_names = {player.id or 0: player.full_name for player in players}
        matches = self.context.match_service.list_matches(self.tournament.id or 0)
        for line, match_id in self._schedule_lines(matches):
            self.list_ctrl.Append(line)
            self.item_match_ids.append(match_id)
        if self.list_ctrl.GetCount() > 0:
            self.list_ctrl.SetSelection(0)
            self._announce_current_item()


class RoundsPanel(RoundsPanel):
    def refresh(self, preserve_selected: bool = True) -> None:
        remember_match_id = self._selected_match_id() if preserve_selected else None
        self.list_ctrl.Clear()
        self.match_ids = []
        players = self.context.tournament_service.list_players(self.tournament.id or 0)
        self.player_names = {player.id or 0: player.full_name for player in players}
        matches = self.context.match_service.list_matches(self.tournament.id or 0, include_archived=True)
        current_round = None
        for match in matches:
            if current_round != match.round_no:
                current_round = match.round_no
                self.list_ctrl.Append(f"Тур {current_round}")
                self.match_ids.append(None)
            status_label = MATCH_STATUS_LABELS.get(match.status, match.status)
            self.list_ctrl.Append(f"{match.stage} | стол {match.table_no} | {self._player_name(match.player_a_id)} - {self._player_name(match.player_b_id)} | {status_label}")
            self.match_ids.append(match.id or 0)
        if self.list_ctrl.GetCount() > 0:
            selection = 0
            if remember_match_id and remember_match_id in self.match_ids:
                selection = self.match_ids.index(remember_match_id)
            self.list_ctrl.SetSelection(selection)
            self._announce_current_item()

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


RULE_MODE_STANDARD = "standard_ibsa"
RULE_MODE_CUSTOM = "custom"

MATCH_STATUS_NOT_STARTED = "not_started"
MATCH_STATUS_IN_PROGRESS = "in_progress"
MATCH_STATUS_PAUSED = "paused"
MATCH_STATUS_COMPLETED = "completed"
MATCH_STATUS_DEFAULTED = "defaulted"
MATCH_STATUS_CANCELLED = "cancelled"

PLAYER_STATUS_ACTIVE = "active"
PLAYER_STATUS_WITHDRAWN = "withdrawn"
PLAYER_STATUS_DISQUALIFIED = "disqualified"
PLAYER_STATUS_NOT_ALLOWED = "not_allowed"

ROLE_A = "A"
ROLE_B = "B"

EVENT_GOAL = "goal"
EVENT_ERROR = "error"
EVENT_PENALTY = "penalty"
EVENT_WARNING = "warning"
EVENT_PLAYER_TIMEOUT = "player_timeout"
EVENT_MEDICAL_TIMEOUT = "medical_timeout"
EVENT_REFEREE_TIMEOUT = "referee_timeout"
EVENT_SWITCH_SIDES = "switch_sides"
EVENT_REPLAY_SERVE = "replay_serve"
EVENT_LOST_BALL = "lost_ball"
EVENT_BALL_BREAK = "ball_break"
EVENT_BAT_BREAK = "bat_break"
EVENT_DEFAULT_LOSS = "default_loss"
EVENT_FINISH_SET = "finish_set"
EVENT_FINISH_MATCH = "finish_match"
EVENT_MATCH_READY = "match_ready"
EVENT_RESUME = "resume"
EVENT_TIME_EXPIRED = "time_expired"
EVENT_NOTE = "note"

ERROR_SUBTYPES = {
    "irregular_serve": "Неправильная подача",
    "center_board": "Центральный экран",
    "body_touch": "Касание тела",
    "illegal_defense": "Неправильная защита",
    "illegal_defense_goal": "Неправильная защита с голом",
    "out": "Аут",
    "infringement": "Нарушение",
    "bat_infraction": "Нарушение ракеткой",
    "ball_infraction": "Нарушение мячом",
}

GROUP_19_3_REASONS = {
    "side_play": "Игра сбоку от стола",
    "illegal_non_playing_hand_contact": "Запрещенное касание стола неигровой рукой",
    "grabbing_ball": "Захват мяча пальцами игровой руки",
    "pushing_table": "Чрезмерное толкание стола",
    "bat_noise": "Шумовые помехи ракеткой",
    "talking": "Разговоры во время игры или перерыва",
    "body_outside_goal": "Помещение части тела в область ворот снаружи",
    "feet_off_floor": "Игра без касания пола хотя бы одной ногой",
    "other_interference": "Иные действия, мешающие игре",
}

IMMEDIATE_PENALTY_REASONS = {
    "mask_touch": "Касание маски без разрешения судьи",
    "phone_signal": "Сигнал мобильного телефона или иного устройства",
    "coach_advice": "Подсказки тренера игроку",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def other_role(role: str) -> str:
    return ROLE_B if role == ROLE_A else ROLE_A


@dataclass
class Tournament:
    id: Optional[int]
    name: str
    event_date: str
    location: str = ""
    tournament_format: str = "individual"
    competition_mode: str = "group_playoff"
    table_count: int = 1
    seeding_mode: str = "snake"
    match_format: int = 3
    rule_mode: str = RULE_MODE_STANDARD
    time_limit_enabled: bool = False
    time_limit_minutes: int = 0
    match_duration_minutes: int = 30
    day_start_time: str = "09:00"
    lunch_break_enabled: bool = False
    lunch_start_time: str = ""
    lunch_end_time: str = ""
    reports_path: str = "reports"
    comment: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class Player:
    id: Optional[int]
    tournament_id: int
    full_name: str
    rating: Optional[int] = None
    organization: str = ""
    city: str = ""
    gender: str = ""
    birth_date: str = ""
    comment: str = ""
    status: str = PLAYER_STATUS_ACTIVE


@dataclass
class Match:
    id: Optional[int]
    tournament_id: int
    player_a_id: int
    player_b_id: int
    stage: str = ""
    table_no: str = ""
    referee: str = ""
    secretary: str = ""
    status: str = MATCH_STATUS_NOT_STARTED
    match_format: int = 3
    rule_mode: str = RULE_MODE_STANDARD
    winner_role: str = ""
    finish_reason: str = ""
    started_at: str = ""
    ended_at: str = ""
    current_state_json: str = ""
    event_cursor: int = 0
    round_no: int = 1
    display_order: int = 0
    archived: bool = False


@dataclass
class MatchEventRecord:
    id: Optional[int]
    match_id: int
    seq_no: int
    set_no: int
    timestamp: str
    event_type: str
    event_subtype: str = ""
    actor_role: str = ""
    beneficiary_role: str = ""
    points_awarded: int = 0
    score_a_after: int = 0
    score_b_after: int = 0
    server_after: str = ""
    serve_no_after: int = 1
    description: str = ""
    is_official_event: bool = True
    state_before_json: str = ""
    state_after_json: str = ""


@dataclass
class MatchCommand:
    event_type: str
    actor_role: str = ""
    subtype: str = ""
    reason: str = ""
    note: str = ""
    confirm_override: bool = False


@dataclass
class SetScore:
    set_no: int
    starter_role: str = ROLE_A
    score_a: int = 0
    score_b: int = 0
    winner_role: str = ""
    started_at: str = field(default_factory=now_iso)
    ended_at: str = ""
    side_switched: bool = False
    switch_pending: bool = False


@dataclass
class MatchState:
    match_id: int = 0
    tournament_id: int = 0
    match_format: int = 3
    rule_mode: str = RULE_MODE_STANDARD
    time_limit_enabled: bool = False
    time_limit_minutes: int = 0
    status: str = MATCH_STATUS_NOT_STARTED
    started_at: str = ""
    ended_at: str = ""
    current_set_no: int = 1
    sets: List[SetScore] = field(default_factory=lambda: [SetScore(set_no=1)])
    sets_won_a: int = 0
    sets_won_b: int = 0
    first_set_starter_role: str = ROLE_A
    current_server: str = ROLE_A
    serve_no: int = 1
    side_switch_pending: bool = False
    current_timeout_owner: str = ""
    timer_state: str = ""
    player_timeouts_used: Dict[str, Dict[str, bool]] = field(default_factory=lambda: {})
    medical_timeouts_used: Dict[str, bool] = field(default_factory=lambda: {})
    referee_timeout_count: int = 0
    warnings_total: Dict[str, int] = field(default_factory=lambda: {ROLE_A: 0, ROLE_B: 0})
    penalties_total: Dict[str, int] = field(default_factory=lambda: {ROLE_A: 0, ROLE_B: 0})
    group_19_3_counts: Dict[str, int] = field(default_factory=lambda: {ROLE_A: 0, ROLE_B: 0})
    winner_role: str = ""
    finish_reason: str = ""
    decided_next_point_mode: bool = False
    log_lines: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "MatchState":
        payload = dict(payload)
        sets = [SetScore(**set_payload) for set_payload in payload.get("sets", [])]
        if not sets:
            starter = payload.get("first_set_starter_role", ROLE_A)
            sets = [SetScore(set_no=1, starter_role=starter)]
        payload["sets"] = sets
        payload.setdefault("first_set_starter_role", sets[0].starter_role if sets else ROLE_A)
        return cls(**payload)

    @property
    def current_set(self) -> SetScore:
        return self.sets[self.current_set_no - 1]

    def points_for(self, role: str) -> int:
        return self.current_set.score_a if role == ROLE_A else self.current_set.score_b

    def set_points(self, role: str, value: int) -> None:
        if role == ROLE_A:
            self.current_set.score_a = value
        else:
            self.current_set.score_b = value

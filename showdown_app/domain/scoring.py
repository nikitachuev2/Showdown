from __future__ import annotations

from dataclasses import replace
from typing import Tuple

from showdown_app.domain.models import (
    ERROR_SUBTYPES,
    EVENT_BALL_BREAK,
    EVENT_BAT_BREAK,
    EVENT_DEFAULT_LOSS,
    EVENT_ERROR,
    EVENT_FINISH_MATCH,
    EVENT_FINISH_SET,
    EVENT_GOAL,
    EVENT_LOST_BALL,
    EVENT_MATCH_READY,
    EVENT_MEDICAL_TIMEOUT,
    EVENT_NOTE,
    EVENT_PENALTY,
    EVENT_PLAYER_TIMEOUT,
    EVENT_REFEREE_TIMEOUT,
    EVENT_REPLAY_SERVE,
    EVENT_RESUME,
    EVENT_SWITCH_SIDES,
    EVENT_TIME_EXPIRED,
    EVENT_WARNING,
    GROUP_19_3_REASONS,
    IMMEDIATE_PENALTY_REASONS,
    MATCH_STATUS_COMPLETED,
    MATCH_STATUS_DEFAULTED,
    MATCH_STATUS_IN_PROGRESS,
    MATCH_STATUS_NOT_STARTED,
    MATCH_STATUS_PAUSED,
    MatchCommand,
    MatchEventRecord,
    MatchState,
    ROLE_A,
    ROLE_B,
    RULE_MODE_CUSTOM,
    SetScore,
    now_iso,
    other_role,
)


class MatchValidationError(ValueError):
    """Raised when an event is not valid in the current match state."""


def create_initial_state(
    match_id: int,
    tournament_id: int,
    match_format: int,
    rule_mode: str,
    time_limit_enabled: bool,
    time_limit_minutes: int,
) -> MatchState:
    state = MatchState(
        match_id=match_id,
        tournament_id=tournament_id,
        match_format=match_format,
        rule_mode=rule_mode,
        time_limit_enabled=time_limit_enabled,
        time_limit_minutes=time_limit_minutes,
    )
    state.current_server = state.first_set_starter_role
    state.sets[0].starter_role = state.first_set_starter_role
    return state


def serialize_state(state: MatchState) -> dict:
    return state.to_dict()


def state_summary(state: MatchState) -> str:
    return (
        f"Сет {state.current_set_no}, счет {state.current_set.score_a}:{state.current_set.score_b}, "
        f"по сетам {state.sets_won_a}:{state.sets_won_b}, подача {state.current_server}, "
        f"{state.serve_no}-я"
    )


def apply_command(
    state: MatchState,
    command: MatchCommand,
    seq_no: int,
) -> Tuple[MatchState, MatchEventRecord]:
    updated = MatchState.from_dict(state.to_dict())
    before = serialize_state(state)
    timestamp = now_iso()

    if updated.status in {MATCH_STATUS_COMPLETED, MATCH_STATUS_DEFAULTED} and command.event_type not in {
        EVENT_NOTE,
        EVENT_RESUME,
    }:
        if not command.confirm_override:
            raise MatchValidationError(
                "Матч уже завершен. Для корректировки требуется подтверждение."
            )

    if command.event_type == EVENT_MATCH_READY:
        if updated.status == MATCH_STATUS_NOT_STARTED:
            updated.status = MATCH_STATUS_IN_PROGRESS
            updated.started_at = timestamp
        description = "Подтверждена готовность игроков и начат матч"
        return updated, build_record(
            updated,
            before,
            seq_no,
            command,
            description,
            0,
            "",
        )

    if command.event_type == EVENT_RESUME:
        updated.status = MATCH_STATUS_IN_PROGRESS
        updated.timer_state = ""
        updated.current_timeout_owner = ""
        description = "Матч возобновлен"
        return updated, build_record(updated, before, seq_no, command, description, 0, "")

    if updated.status == MATCH_STATUS_NOT_STARTED:
        updated.status = MATCH_STATUS_IN_PROGRESS
        updated.started_at = timestamp

    points_awarded = 0
    beneficiary = ""
    description = ""

    if command.event_type == EVENT_GOAL:
        _ensure_live_play(updated)
        beneficiary = command.actor_role
        points_awarded = 2
        award_points(updated, beneficiary, points_awarded)
        description = f"Гол игрока {beneficiary}"
        advance_serve(updated)
    elif command.event_type == EVENT_ERROR:
        _ensure_live_play(updated)
        beneficiary = other_role(command.actor_role)
        points_awarded = 2 if command.subtype == "illegal_defense_goal" else 1
        award_points(updated, beneficiary, points_awarded)
        subtype_name = ERROR_SUBTYPES.get(command.subtype, "Ошибка")
        description = f"{subtype_name}: ошибка игрока {command.actor_role}"
        advance_serve(updated)
    elif command.event_type == EVENT_PENALTY:
        beneficiary = other_role(command.actor_role)
        points_awarded = 2
        award_points(updated, beneficiary, points_awarded)
        updated.penalties_total[command.actor_role] += 1
        reason = IMMEDIATE_PENALTY_REASONS.get(command.reason, command.reason or "штраф")
        description = f"Штраф игроку {command.actor_role}: {reason}"
        if command.reason == "coach_advice":
            description += ". Тренер подлежит удалению из игровой комнаты"
        advance_serve(updated)
    elif command.event_type == EVENT_WARNING:
        updated.warnings_total[command.actor_role] += 1
        reason_label = GROUP_19_3_REASONS.get(command.reason, command.reason or "предупреждение")
        description = f"Предупреждение игроку {command.actor_role}: {reason_label}"
        if command.reason in GROUP_19_3_REASONS:
            updated.group_19_3_counts[command.actor_role] += 1
            if updated.group_19_3_counts[command.actor_role] >= 2:
                beneficiary = other_role(command.actor_role)
                points_awarded = 2
                award_points(updated, beneficiary, points_awarded)
                updated.penalties_total[command.actor_role] += 1
                description = (
                    f"Повторное нарушение группы 19.3 игрока {command.actor_role}: "
                    f"штраф 2 очка игроку {beneficiary}"
                )
                advance_serve(updated)
    elif command.event_type == EVENT_PLAYER_TIMEOUT:
        _ensure_stoppage_possible(updated, command)
        set_key = str(updated.current_set_no)
        per_set = updated.player_timeouts_used.setdefault(
            set_key, {ROLE_A: False, ROLE_B: False}
        )
        if per_set.get(command.actor_role) and not command.confirm_override:
            raise MatchValidationError(
                "Обычный тайм-аут этого игрока в текущем сете уже использован."
            )
        per_set[command.actor_role] = True
        updated.status = MATCH_STATUS_PAUSED
        updated.timer_state = "player_timeout"
        updated.current_timeout_owner = command.actor_role
        description = f"Тайм-аут игрока {command.actor_role} на 60 секунд"
    elif command.event_type == EVENT_MEDICAL_TIMEOUT:
        _ensure_stoppage_possible(updated, command)
        updated.medical_timeouts_used[command.actor_role] = True
        updated.status = MATCH_STATUS_PAUSED
        updated.timer_state = "medical_timeout"
        updated.current_timeout_owner = command.actor_role
        description = f"Медицинский тайм-аут игрока {command.actor_role} до 5 минут"
    elif command.event_type == EVENT_REFEREE_TIMEOUT:
        updated.referee_timeout_count += 1
        updated.status = MATCH_STATUS_PAUSED
        updated.timer_state = "referee_timeout"
        description = "Судейский тайм-аут"
    elif command.event_type == EVENT_SWITCH_SIDES:
        if updated.current_set.side_switched and not command.confirm_override:
            raise MatchValidationError(
                "Смена сторон в текущем сете уже подтверждена."
            )
        updated.current_set.side_switched = True
        updated.current_set.switch_pending = False
        updated.side_switch_pending = False
        updated.status = MATCH_STATUS_PAUSED
        updated.timer_state = "side_switch"
        description = "Смена сторон подтверждена, 60 секунд"
    elif command.event_type in {EVENT_REPLAY_SERVE, EVENT_LOST_BALL, EVENT_BALL_BREAK, EVENT_BAT_BREAK}:
        descriptions = {
            EVENT_REPLAY_SERVE: "Повторная подача",
            EVENT_LOST_BALL: "Потеря мяча, повторная подача",
            EVENT_BALL_BREAK: "Поломка мяча, повторная подача",
            EVENT_BAT_BREAK: "Поломка ракетки, повторная подача",
        }
        description = descriptions[command.event_type]
    elif command.event_type == EVENT_DEFAULT_LOSS:
        beneficiary = other_role(command.actor_role)
        apply_default_loss_result(updated, beneficiary, timestamp)
        updated.status = MATCH_STATUS_DEFAULTED
        updated.winner_role = beneficiary
        updated.finish_reason = command.reason or "Поражение по умолчанию"
        updated.ended_at = timestamp
        description = (
            f"Поражение по умолчанию игрока {command.actor_role}. Победитель: игрок {beneficiary}"
        )
    elif command.event_type == EVENT_FINISH_SET:
        winner = detect_set_winner(updated)
        if not winner and not command.confirm_override:
            raise MatchValidationError(
                "Сет нельзя завершить вручную без победителя по счету без подтверждения."
            )
        finish_current_set(updated, winner or command.actor_role, timestamp)
        description = f"Сет {updated.current_set_no - 1} завершен"
    elif command.event_type == EVENT_FINISH_MATCH:
        winner = updated.winner_role or command.actor_role
        if not winner:
            raise MatchValidationError("Нужно указать победителя матча.")
        updated.status = MATCH_STATUS_COMPLETED
        updated.winner_role = winner
        updated.finish_reason = command.reason or "Матч завершен вручную"
        updated.ended_at = timestamp
        description = f"Матч завершен вручную. Победитель: игрок {winner}"
    elif command.event_type == EVENT_TIME_EXPIRED:
        if not updated.time_limit_enabled and updated.rule_mode != RULE_MODE_CUSTOM:
            raise MatchValidationError("Лимит времени недоступен в стандартном режиме.")
        if updated.current_set.score_a == updated.current_set.score_b:
            updated.decided_next_point_mode = True
            description = "Время истекло, счет равный. Следующее очко становится решающим"
        else:
            winner = ROLE_A if updated.current_set.score_a > updated.current_set.score_b else ROLE_B
            finish_current_set(updated, winner, timestamp)
            description = f"Время истекло. Сет выиграл игрок {winner}"
    elif command.event_type == EVENT_NOTE:
        description = command.note or "Судейская заметка"
    else:
        raise MatchValidationError(f"Неизвестное событие: {command.event_type}")

    if command.event_type in {EVENT_GOAL, EVENT_ERROR, EVENT_PENALTY} and updated.decided_next_point_mode:
        winner = beneficiary
        finish_current_set(updated, winner, timestamp)
        description += ". Решающее очко определило победителя сета"

    if updated.status not in {MATCH_STATUS_COMPLETED, MATCH_STATUS_DEFAULTED}:
        maybe_mark_side_switch(updated)
        if not updated.winner_role:
            maybe_finish_match(updated, timestamp)

    return updated, build_record(
        updated,
        before,
        seq_no,
        command,
        description,
        points_awarded,
        beneficiary,
    )


def build_record(
    state: MatchState,
    before: dict,
    seq_no: int,
    command: MatchCommand,
    description: str,
    points_awarded: int,
    beneficiary: str,
) -> MatchEventRecord:
    state.log_lines.append(
        f"{now_iso()[11:19]} | Сет {state.current_set_no} | {description} | "
        f"счет {state.current_set.score_a}:{state.current_set.score_b} | "
        f"подача {state.current_server}, {state.serve_no}-я"
    )
    return MatchEventRecord(
        id=None,
        match_id=state.match_id,
        seq_no=seq_no,
        set_no=state.current_set_no,
        timestamp=now_iso(),
        event_type=command.event_type,
        event_subtype=command.subtype or command.reason,
        actor_role=command.actor_role,
        beneficiary_role=beneficiary,
        points_awarded=points_awarded,
        score_a_after=state.current_set.score_a,
        score_b_after=state.current_set.score_b,
        server_after=state.current_server,
        serve_no_after=state.serve_no,
        description=description,
        state_before_json="",
        state_after_json="",
    )


def _ensure_live_play(state: MatchState) -> None:
    if state.status not in {MATCH_STATUS_IN_PROGRESS, MATCH_STATUS_NOT_STARTED}:
        raise MatchValidationError("Сейчас нельзя фиксировать игровое очко.")


def _ensure_stoppage_possible(state: MatchState, command: MatchCommand) -> None:
    if state.status in {MATCH_STATUS_COMPLETED, MATCH_STATUS_DEFAULTED}:
        raise MatchValidationError("Нельзя взять тайм-аут после завершения матча.")
    if state.status == MATCH_STATUS_PAUSED and not command.confirm_override:
        raise MatchValidationError("Матч уже находится в остановке.")


def award_points(state: MatchState, role: str, points: int) -> None:
    state.set_points(role, state.points_for(role) + points)


def advance_serve(state: MatchState) -> None:
    if state.serve_no == 1:
        state.serve_no = 2
        return
    state.serve_no = 1
    state.current_server = other_role(state.current_server)


def needed_sets_to_win(match_format: int) -> int:
    return 1 if match_format == 1 else 2 if match_format == 3 else 3


def detect_set_winner(state: MatchState) -> str:
    score_a = state.current_set.score_a
    score_b = state.current_set.score_b
    if state.decided_next_point_mode and score_a != score_b:
        return ROLE_A if score_a > score_b else ROLE_B
    if score_a >= 11 or score_b >= 11:
        if abs(score_a - score_b) >= 2:
            return ROLE_A if score_a > score_b else ROLE_B
    return ""


def maybe_mark_side_switch(state: MatchState) -> None:
    set_no = state.current_set_no
    if state.current_set.side_switched:
        return
    trigger_by_score = False
    if state.match_format == 1 and max(state.current_set.score_a, state.current_set.score_b) >= 6:
        trigger_by_score = True
    if state.match_format >= 3 and set_no == 3 and max(
        state.current_set.score_a, state.current_set.score_b
    ) >= 6:
        trigger_by_score = True
    if trigger_by_score:
        state.current_set.switch_pending = True
        state.side_switch_pending = True

    winner = detect_set_winner(state)
    if winner:
        finish_current_set(state, winner, now_iso())


def finish_current_set(state: MatchState, winner_role: str, timestamp: str) -> None:
    current = state.current_set
    current.winner_role = winner_role
    current.ended_at = timestamp
    if winner_role == ROLE_A:
        state.sets_won_a += 1
    else:
        state.sets_won_b += 1
    maybe_finish_match(state, timestamp)
    if state.winner_role:
        return
    next_set_no = state.current_set_no + 1
    state.current_set_no = next_set_no
    next_starter = (
        state.first_set_starter_role if next_set_no % 2 == 1 else other_role(state.first_set_starter_role)
    )
    state.current_server = next_starter
    state.serve_no = 1
    state.side_switch_pending = False
    state.current_timeout_owner = ""
    state.timer_state = ""
    state.decided_next_point_mode = False
    state.sets.append(SetScore(set_no=next_set_no, starter_role=next_starter))
    state.status = MATCH_STATUS_IN_PROGRESS


def maybe_finish_match(state: MatchState, timestamp: str) -> None:
    target = needed_sets_to_win(state.match_format)
    if state.sets_won_a >= target:
        state.winner_role = ROLE_A
    elif state.sets_won_b >= target:
        state.winner_role = ROLE_B
    if state.winner_role:
        state.status = MATCH_STATUS_COMPLETED
        state.finish_reason = state.finish_reason or "Победа по сетам"
        state.ended_at = timestamp


def apply_default_loss_result(state: MatchState, winner_role: str, timestamp: str) -> None:
    target_sets = needed_sets_to_win(state.match_format)
    state.sets = []
    state.current_set_no = target_sets
    state.sets_won_a = target_sets if winner_role == ROLE_A else 0
    state.sets_won_b = target_sets if winner_role == ROLE_B else 0
    state.side_switch_pending = False
    state.current_timeout_owner = ""
    state.timer_state = ""
    state.decided_next_point_mode = False
    state.player_timeouts_used = {}
    state.medical_timeouts_used = {}
    state.referee_timeout_count = 0
    state.warnings_total = {ROLE_A: 0, ROLE_B: 0}
    state.penalties_total = {ROLE_A: 0, ROLE_B: 0}
    state.group_19_3_counts = {ROLE_A: 0, ROLE_B: 0}
    for set_no in range(1, target_sets + 1):
        starter_role = state.first_set_starter_role if set_no % 2 == 1 else other_role(state.first_set_starter_role)
        state.sets.append(
            SetScore(
                set_no=set_no,
                starter_role=starter_role,
                score_a=11 if winner_role == ROLE_A else 0,
                score_b=11 if winner_role == ROLE_B else 0,
                winner_role=winner_role,
                started_at=state.started_at or timestamp,
                ended_at=timestamp,
            )
        )
    state.current_server = state.sets[-1].starter_role
    state.serve_no = 1

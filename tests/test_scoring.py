from showdown_app.domain.models import (
    EVENT_DEFAULT_LOSS,
    EVENT_ERROR,
    EVENT_GOAL,
    EVENT_PENALTY,
    EVENT_PLAYER_TIMEOUT,
    EVENT_SWITCH_SIDES,
    EVENT_WARNING,
    MatchCommand,
    ROLE_A,
    ROLE_B,
    RULE_MODE_CUSTOM,
)
from showdown_app.domain.scoring import MatchValidationError, apply_command, create_initial_state


def test_goal_adds_two_points_and_rotates_serve_every_two_rallies():
    state = create_initial_state(1, 1, 3, "standard_ibsa", False, 0)
    state, _ = apply_command(state, MatchCommand(EVENT_GOAL, actor_role=ROLE_A), 1)
    assert state.current_set.score_a == 2
    assert state.current_server == ROLE_A
    assert state.serve_no == 2

    state, _ = apply_command(state, MatchCommand(EVENT_GOAL, actor_role=ROLE_B), 2)
    assert state.current_server == ROLE_B
    assert state.serve_no == 1


def test_set_requires_two_point_margin():
    state = create_initial_state(1, 1, 1, "standard_ibsa", False, 0)
    for seq in range(1, 6):
        state, _ = apply_command(state, MatchCommand(EVENT_GOAL, actor_role=ROLE_A), seq * 2 - 1)
        state, _ = apply_command(state, MatchCommand(EVENT_GOAL, actor_role=ROLE_B), seq * 2)
    assert state.current_set.score_a == 10
    assert state.current_set.score_b == 10
    assert state.winner_role == ""

    state, _ = apply_command(state, MatchCommand(EVENT_ERROR, actor_role=ROLE_B, subtype="out"), 11)
    assert state.current_set.score_a == 11
    assert state.winner_role == ""

    state, _ = apply_command(state, MatchCommand(EVENT_ERROR, actor_role=ROLE_B, subtype="out"), 12)
    assert state.winner_role == ROLE_A


def test_group_19_3_warning_turns_into_penalty_on_repeat():
    state = create_initial_state(1, 1, 3, "standard_ibsa", False, 0)
    state, _ = apply_command(state, MatchCommand(EVENT_WARNING, actor_role=ROLE_A, reason="talking"), 1)
    assert state.warnings_total[ROLE_A] == 1
    assert state.penalties_total[ROLE_A] == 0

    state, _ = apply_command(state, MatchCommand(EVENT_WARNING, actor_role=ROLE_A, reason="bat_noise"), 2)
    assert state.penalties_total[ROLE_A] == 1
    assert state.current_set.score_b == 2


def test_immediate_penalty_awards_two_points():
    state = create_initial_state(1, 1, 3, "standard_ibsa", False, 0)
    state, _ = apply_command(state, MatchCommand(EVENT_PENALTY, actor_role=ROLE_B, reason="phone_signal"), 1)
    assert state.current_set.score_a == 2
    assert state.penalties_total[ROLE_B] == 1


def test_timeout_is_once_per_set_without_override():
    state = create_initial_state(1, 1, 3, "standard_ibsa", False, 0)
    state, _ = apply_command(state, MatchCommand(EVENT_PLAYER_TIMEOUT, actor_role=ROLE_A), 1)
    assert state.timer_state == "player_timeout"
    try:
        apply_command(state, MatchCommand(EVENT_PLAYER_TIMEOUT, actor_role=ROLE_A), 2)
    except MatchValidationError:
        pass
    else:
        raise AssertionError("Expected MatchValidationError for second timeout in the set")


def test_switch_sides_becomes_pending_at_six_points_in_single_set_match():
    state = create_initial_state(1, 1, 1, "standard_ibsa", False, 0)
    for seq in range(1, 4):
        state, _ = apply_command(state, MatchCommand(EVENT_GOAL, actor_role=ROLE_A), seq)
    assert state.current_set.score_a == 6
    assert state.side_switch_pending is True
    state, _ = apply_command(state, MatchCommand(EVENT_SWITCH_SIDES), 4)
    assert state.current_set.side_switched is True
    assert state.side_switch_pending is False


def test_default_loss_finishes_match():
    state = create_initial_state(1, 1, 3, "standard_ibsa", False, 0)
    state, _ = apply_command(state, MatchCommand(EVENT_DEFAULT_LOSS, actor_role=ROLE_A), 1)
    assert state.winner_role == ROLE_B
    assert state.finish_reason
    assert state.status == "defaulted"
    assert state.sets_won_b == 2
    assert [(set_score.score_a, set_score.score_b) for set_score in state.sets] == [(0, 11), (0, 11)]


def test_time_limit_expiry_enters_deciding_next_point_mode_on_tie():
    state = create_initial_state(1, 1, 1, RULE_MODE_CUSTOM, True, 10)
    state.current_set.score_a = 8
    state.current_set.score_b = 8
    state, _ = apply_command(state, MatchCommand("time_expired"), 1)
    assert state.decided_next_point_mode is True

from resistance import rules


def test_five_player_constants():
    assert rules.N_PLAYERS == 5
    assert rules.N_SPIES == 2
    assert rules.TEAM_SIZES == (2, 3, 2, 3, 3)
    assert rules.VOTES_TO_APPROVE == 3
    assert rules.MAX_PROPOSALS_PER_ROUND == 5
    assert rules.MAX_SUGGESTIONS == 3


def test_team_size_by_round():
    assert [rules.team_size(r) for r in range(1, 6)] == [2, 3, 2, 3, 3]

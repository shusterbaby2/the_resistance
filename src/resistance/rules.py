"""Rules constants for 5-player base Resistance.

Other player counts are intentionally out of scope (see CLAUDE.md). At exactly 5
players the two-fails-required rule never applies, so mission resolution is:
any fail card fails the mission.
"""

N_PLAYERS = 5
N_SPIES = 2
N_ROUNDS = 5
TEAM_SIZES = (2, 3, 2, 3, 3)  # indexed by round_num - 1
MAX_PROPOSALS_PER_ROUND = 5  # 5th consecutive rejection in a round = spies win
MAX_SUGGESTIONS = 3  # per attempt: leader may float up to 3 teams before the vote
MISSIONS_TO_WIN = 3
VOTES_TO_APPROVE = N_PLAYERS // 2 + 1  # 3 of 5


def team_size(round_num: int) -> int:
    return TEAM_SIZES[round_num - 1]

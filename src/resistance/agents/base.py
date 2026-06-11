"""The agent-turn interface.

One shape for every actor at the table — LLM agents, scripted agents, and the
human (whose Controller is the I/O boundary; the engine never special-cases
the human beyond which Controller sits in the seat).

in:  SeatView (structured state + transcript + own beliefs) + the action asked
out: AgentOutput {reasoning, speech, updated beliefs, action payload}
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..beliefs import Beliefs
from ..views import SeatView


class Action(str, Enum):
    PROPOSE = "propose_team"  # leader floats an initial team suggestion
    RECONSIDER = "reconsider"  # leader, after discussion: submit or float a new team
    DISCUSS = "discuss"
    VOTE = "vote"
    MISSION = "mission"
    DEBRIEF = "debrief"  # post-game reflection after roles are revealed


class AgentOutput(BaseModel):
    reasoning: str = ""  # private; never shown to other agents
    speech: str = ""  # public table talk; empty = stay quiet
    beliefs: Beliefs | None = None  # replaces the seat's persisted beliefs if set
    team: list[int] | None = None  # for PROPOSE / RECONSIDER (revised team)
    submit: bool | None = None  # for RECONSIDER: True = put current team to the vote
    vote: bool | None = None  # for VOTE
    mission_success: bool | None = None  # for MISSION (spies only)
    strategy: str = ""  # for DEBRIEF
    best_move: str = ""  # for DEBRIEF
    mistake: str = ""  # for DEBRIEF
    confusion: str = ""  # for DEBRIEF
    meta: dict[str, Any] = Field(default_factory=dict)  # e.g. raw llm_call records


class Controller(ABC):
    @abstractmethod
    def act(self, view: SeatView, action: Action) -> AgentOutput: ...

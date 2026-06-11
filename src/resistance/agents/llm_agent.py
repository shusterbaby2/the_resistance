"""LLM-backed agent: one structured model call per turn.

Output schemas are per-action so the model is only ever asked for fields that
matter for the current decision. Beliefs use a list (not a dict) because
structured outputs require closed object schemas.
"""

from pydantic import BaseModel, Field, ValidationError

from ..beliefs import Beliefs, SeatBelief
from ..llm.base import LLMClient
from ..personality import Personality
from ..views import SeatView
from .base import Action, AgentOutput, Controller
from .prompts import build_system, build_user
from .scripted import RandomController


class BeliefEntry(BaseModel):
    seat: int
    suspicion: float
    reason: str


class DiscussOut(BaseModel):
    reasoning: str
    speech: str
    beliefs: list[BeliefEntry]


class ProposeOut(BaseModel):
    reasoning: str
    speech: str
    team: list[int]
    beliefs: list[BeliefEntry]


class ReconsiderOut(BaseModel):
    reasoning: str
    speech: str
    submit: bool
    team: list[int] = Field(default_factory=list)
    beliefs: list[BeliefEntry]


class VoteOut(BaseModel):
    reasoning: str
    approve: bool
    beliefs: list[BeliefEntry]


class MissionOut(BaseModel):
    reasoning: str
    play_success: bool


SCHEMAS: dict[Action, type[BaseModel]] = {
    Action.PROPOSE: ProposeOut,
    Action.RECONSIDER: ReconsiderOut,
    Action.DISCUSS: DiscussOut,
    Action.VOTE: VoteOut,
    Action.MISSION: MissionOut,
}


class LLMController(Controller):
    def __init__(self, seat: int, persona: Personality, client: LLMClient):
        self.seat = seat
        self.persona = persona
        self.client = client
        self._system: str | None = None

    def _system_prompt(self, view: SeatView) -> str:
        if self._system is None:
            self._system = build_system(
                seat=view.seat,
                persona=self.persona,
                view_role=view.role,
                fellow_spies=view.fellow_spies,
                seat_names={p.seat: p.name for p in view.players},
            )
        return self._system

    def act(self, view: SeatView, action: Action) -> AgentOutput:
        schema = SCHEMAS[action]
        system = self._system_prompt(view)
        records: list[dict] = []
        error_note = None
        parsed = None
        out = None
        for attempt in range(2):  # one retry with a correction note
            try:
                out, record = self.client.complete(
                    system=system,
                    user=build_user(view, action, error_note),
                    schema=schema,
                )
            except (ValidationError, ValueError) as exc:
                records.append({
                    "model": getattr(self.client, "model", "unknown"),
                    "error": str(exc),
                })
                if attempt == 1:
                    return self._fallback(view, action, records)
                error_note = (
                    "Your last response was incomplete or could not be parsed. "
                    "Keep reasoning brief (1–2 sentences) and return complete valid JSON."
                )
                continue
            records.append(record)
            error_note = self._validate(view, action, out)
            if error_note is None:
                parsed = out
                break
        if parsed is None:
            if out is not None:
                parsed = out  # let the engine's last-resort correction handle it
            else:
                return self._fallback(view, action, records)
        result = self._to_output(action, parsed)
        result.meta["llm_calls"] = records
        return result

    def _fallback(self, view: SeatView, action: Action,
                  records: list[dict]) -> AgentOutput:
        """Guarantee a legal turn when the model returns unparseable output."""
        fb = RandomController(self.seat, self.seat, self.persona)
        result = fb.act(view, action)
        result.meta["llm_calls"] = records
        result.meta["fallback"] = "unparseable_output"
        return result

    def _validate(self, view: SeatView, action: Action, out: BaseModel) -> str | None:
        if action in (Action.PROPOSE, Action.RECONSIDER):
            if action == Action.RECONSIDER and out.submit:
                return None
            team = sorted(set(out.team))
            valid = {p.seat for p in view.players}
            if len(team) != view.team_size or not set(team) <= valid:
                return (
                    f"Your team {out.team} is invalid: pick exactly "
                    f"{view.team_size} distinct seats from "
                    f"{sorted(valid)}. Respond again in full."
                )
        return None

    def _to_output(self, action: Action, parsed: BaseModel) -> AgentOutput:
        beliefs = None
        if hasattr(parsed, "beliefs"):
            beliefs = Beliefs(entries=[
                SeatBelief(seat=b.seat,
                           suspicion=max(0.0, min(1.0, b.suspicion)),
                           reason=b.reason)
                for b in parsed.beliefs
                if b.seat != self.seat
            ])
        if action == Action.PROPOSE:
            return AgentOutput(reasoning=parsed.reasoning, speech=parsed.speech,
                               team=sorted(set(parsed.team)), beliefs=beliefs)
        if action == Action.RECONSIDER:
            team = sorted(set(parsed.team)) if parsed.team else None
            return AgentOutput(reasoning=parsed.reasoning, speech=parsed.speech,
                               submit=parsed.submit, team=team, beliefs=beliefs)
        if action == Action.DISCUSS:
            return AgentOutput(reasoning=parsed.reasoning, speech=parsed.speech,
                               beliefs=beliefs)
        if action == Action.VOTE:
            return AgentOutput(reasoning=parsed.reasoning, vote=parsed.approve,
                               beliefs=beliefs)
        if action == Action.MISSION:
            return AgentOutput(reasoning=parsed.reasoning,
                               mission_success=parsed.play_success)
        raise ValueError(f"unknown action {action}")

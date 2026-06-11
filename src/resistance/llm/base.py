"""Provider-agnostic LLM interface.

Every agent turn is one call of this shape. Swapping providers (or running
different agents on different models in the same game) means implementing
`complete` for a new client — nothing else changes.
"""

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    model: str

    def complete(self, *, system: str, user: str, schema: type[T],
                 thinking: bool = False) -> tuple[T, dict[str, Any]]:
        """Run one structured completion.

        `thinking` requests extended thinking for this call. Most turns leave
        it off: the schema's `reasoning` field already carries chain-of-thought,
        so extended thinking would pay for the same deliberation twice.

        Returns (parsed schema instance, raw record). The raw record is logged
        as an llm_call event so recorded games can be replayed and analyzed
        without re-running the model.
        """
        ...

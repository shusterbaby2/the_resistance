"""Agent personas. Traits are 1-10 dials.

`talkativeness` is the static desirability term in the mechanical speaking bid;
the other traits shape the LLM system prompt only.
"""

from pydantic import BaseModel


class Personality(BaseModel):
    name: str
    style: str  # one-line character sketch, used verbatim in the system prompt
    talkativeness: int  # 1 quiet .. 10 dominates the table; feeds speak bids
    aggression: int  # 1 conflict-averse .. 10 accuses freely
    trustfulness: int  # 1 paranoid .. 10 takes people at their word
    deceptiveness: int  # 1 terrible liar .. 10 ice-cold bluffer


NEUTRAL = Personality(
    name="Player",
    style="a measured player at the table",
    talkativeness=5,
    aggression=5,
    trustfulness=5,
    deceptiveness=5,
)


PRESETS: list[Personality] = [
    Personality(
        name="Marlow",
        style="a blunt ex-dockworker who accuses first and apologizes never",
        talkativeness=8, aggression=9, trustfulness=3, deceptiveness=5,
    ),
    Personality(
        name="Vex",
        style="a quiet analyst who speaks rarely, precisely, and only when it counts",
        talkativeness=3, aggression=4, trustfulness=4, deceptiveness=8,
    ),
    Personality(
        name="Juno",
        style="a chatty optimist who thinks out loud and overshares her hunches",
        talkativeness=9, aggression=5, trustfulness=8, deceptiveness=4,
    ),
    Personality(
        name="Castor",
        style="a careful diplomat who hedges everything and quietly builds consensus",
        talkativeness=5, aggression=2, trustfulness=6, deceptiveness=7,
    ),
    Personality(
        name="Sable",
        style="a sardonic gambler who needles people to see how they react",
        talkativeness=6, aggression=7, trustfulness=3, deceptiveness=9,
    ),
]

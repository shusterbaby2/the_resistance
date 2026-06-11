# AI Resistance: Product Requirements Document (PRD)

**Version:** 0.1 MVP  
**Date:** 2025-06-09

---

## Table of Contents

1. [Overview & Vision](#overview--vision)
2. [Goals & Success Criteria](#goals--success-criteria)
3. [Gameplay & Game Flow](#gameplay--game-flow)
    - [Players](#players)
    - [Turns & Interactions](#turns--interactions)
    - [Voting](#voting)
    - [Game BoardVisuals](#game-boardvisuals)
4. [AILLM Design](#aillm-design)
    - [LLM Prompting and Deception](#llm-prompting-and-deception)
5. [Voice Tech](#voice-tech)
6. [UIUX](#uiux)
7. [Technical Considerations](#technical-considerations)
8. [MVP Scope](#mvp-scope)
9. [StretchFuture Features](#stretchfuture-features)
10. [Risks & Open Questions](#risks--open-questions)
11. [Out of Scope for MVP](#out-of-scope-for-mvp)
12. [AppendixNotes](#appendixnotes)

---

## Overview & Vision

Build a desktop-based, AI-driven digital version of **The Resistance**, designed as a technical playground for experimenting with modern LLMs, agent personalities, trust dynamics, and real-time voice interaction. The core goal is to create a game loop where the player interacts naturally (via voice and simple UI) with multiple AI agents who act, talk, and *lie* like human players.

---

## Goals & Success Criteria

- **Technical playground:** Learn and experiment with Python, LLM-based agent logic, and voice integration.
- **Human-like AI:** AIs that can bluff, deceive, form and express trust/distrust, and vary their talkativeness/personalities.
- **Voice-first experience:** Core gameplay occurs via speech; voting and simple UI actions via clickable UI.
- **Replayable:** Each game should feel different and non-deterministic, even when replayed.
- **Metrics:** Ability to log/track key behaviors (e.g., how often AI lies, effectiveness of bluffing).

---

## Gameplay & Game Flow

### Players

- **Core loop:** Classic Resistance (5–10 players). MVP supports as few as 3 players for testing.
- **Mix:** Human player vs. all-AI agents (for v1).

### Turns & Interactions

- **Team suggestion loop:** When it is a leader's turn, they **suggest** a mission team (not a final proposal). Everyone discusses the suggestion. The leader then either **submits** that team to a vote or **floats an alternate** team for more discussion. Up to **3 suggestions per vote attempt**; after the third suggestion, the team auto-submits to a vote. Suggestion counter resets after each vote (approved or rejected). Five rejected votes in a round still hands the game to the spies.
- **Table Talk:** All players can interrupt each other to speak, but system should balance so that AI personalities (e.g., talkative vs. quiet) influence how much they interject. Need to prevent constant overlap/interruptions—possibly by enforcing short pauses or a queue system. Players are never required to speak on any round.
- **AI Speech:** Free-form; not template-based. AI can ask questions of human or other AI agents and must respond to questions.
- **Memory:** AI "remembers" conversation, but the player does not see a transcript/log. (Audio recording for review is supported.)
- **Trust System:** Each AI maintains internal "trust" levels for every player. Trust/distrust can be stated aloud, with more or less frequency based on personality.

### Voting

- **Team Selection Voting:** Public, shown in UI. (Who approves/rejects a leader-submitted mission team.)
- **Mission Voting:** Secret, shown in UI. (Success/Fail outcome per classic rules.)
- **UI:** Simple, clickable interface for voting and confirming mission results.

### Game BoardVisuals

- Minimal but clear UI to show:
    - Player/AI avatars and names
    - Which missions succeeded/failed
    - Voting history for team approval
    - Who is currently speaking (avatar highlight)
- Visual style: "Whatever is fast" (simple avatars, basic color indicators). Improve later.

---

## AILLM Design

- **Agents:** Each AI agent is a unique persona, defined by personality traits (e.g., aggressiveness, talkativeness, trustfulness, propensity to lie). Traits configurable on a scale (e.g., 1–10).
- **LLM Instance:** Each agent can use its own LLM system prompt/memory (ideal), but team can experiment with cost/performance tradeoffs.
- **LLM Prompts:** Custom system prompt per agent, plus dynamic context (recent dialogue, trust values, game state).
- **Personality Expression:** Personality affects how much/when AI interrupts, how expressive they are, and how likely they are to state reasons for trust/distrust.
- **Lie Detection/Tracking:** Log and analyze how often each AI lies, bluffs, or is "caught" by the human.
- **Metrics:** Track key AI actions (lies, trust shifts, interjections).

### LLM Prompting and Deception

- **Deception/Bluffing:**  
    - LLM agents must convincingly act according to secret roles, including lying/bluffing as required by the game.
    - Prompt engineering should emphasize "roleplay" and "acting in-game" rather than direct instructions to "lie."
    - System should log cases where LLM refuses to lie or breaks character for analysis and further prompt refinement.
    - If necessary, explore programmatic interventions or alternate LLMs with looser guardrails as a fallback.

---

## Voice Tech

- **Input:** Real-time speech-to-text (e.g., OpenAI Whisper, Google, or equivalent cloud STT).
- **Output:** Text-to-speech (TTS) with unique voices per AI (e.g., ElevenLabs, OpenAI, or similar). Prefer cloud solutions for voice variety and expressiveness.
- **Personality in Voice:** Ideally, TTS should reflect AI personality traits, but not required for v1.
- **Audio-to-Audio Option:**  
    - Consider supporting direct audio-to-audio APIs (e.g., OpenAI Voice Mode, Google Audio-to-Audio) if lower latency or more natural conversation is needed.
    - System should be modular to allow switching between classic STT > LLM > TTS and direct audio-to-audio architectures.
    - Early prototyping will determine which approach is best for real-time play and debugging.
- **Latency Handling:** On voice/speech lag, system can display "Thinking..." or pause gracefully.
- **Audio Recording:** Option to record all game audio for later analysis.

---

## UIUX

- **UI Elements:**  
    - Main game board with avatars, mission tracker, vote tracker.
    - Simple voting panel for public/secret votes.
    - Speaker indicator.
    - "Thinking..." status as needed.
- **Accessibility:** None required for MVP (subtitles/other features for later).
- **Art:** Simple, placeholder as needed. Improve later.

---

## Technical Considerations

- **Language:** Python preferred for all core logic and glue code.
- **Framework:** Open to PyGame, Tkinter, or another Python desktop GUI; web-based (with Flask + JS) possible if easier for integration.
- **Voice APIs:** Must support both classic STT/TTS pipeline and/or direct audio-to-audio APIs.
- **Cloud/Local Hosting:** Local for development; cloud hosting as a possible stretch goal.
- **Data Logging:** Log all AI prompts/outputs, key game events, and trust system for debugging/learning.

---

## MVP Scope

- Playable game with one human and at least two AI agents
- Real-time voice input/output (classic STT/TTS or audio-to-audio)
- Simple UI with game board, voting, avatars
- AI agents have distinct personalities, can talk, lie, and respond to human input
- Full round-trip gameplay: team selection, voting, missions, win/loss detection
- Metrics/tracking for AI behavior and game outcomes

---

## StretchFuture Features

- Multiplayer support (multiple human players over network)
- Customizable game rules/roles
- Advanced AI memory (e.g., recall prior games, "learn" from experience)
- More expressive, emotion-matched voices
- Enhanced analytics (AI success/failure, player suspicion levels)
- Accessibility features (subtitles, colorblind mode, etc.)

---

## Risks & Open Questions

- **LLM/Voice API Cost:** Running multiple LLM agents and real-time TTS/STT may incur API costs.
- **Real-Time Coordination:** Balancing turn-taking, interruptions, and "natural" conversation flow is technically challenging.
- **Lying/Bluffing:** LLMs may be reluctant to "lie" unless carefully prompted; prompt engineering required.
- **Latency:** Real-time voice responsiveness is a key user experience challenge.
- **Game Flow Balance:** Ensuring neither silence nor constant crosstalk dominates; requires tuning of agent "talkativeness."

---

## Out of Scope for MVP

- Fancy art/animation
- Accessibility for all user types
- Persistent user accounts, stats, etc.
- Multiplayer

---

## AppendixNotes

- Reference materials: Rules for The Resistance, OpenAI/ElevenLabs API docs
- Stretch idea: "AI personality editor" UI for configuring agent traits easily

---

# Learning Loop — LLM Model Manager

**The closed learning loop for AI-assisted development.**

A three-document framework bundled into Llama Model Manager that turns every
AI-assisted coding session into a compounding investment: each session learns
from the last, scoped to your hardware tier, and ships with you across projects.

## The Problem

AI coding agents start every session from scratch. They re-discover your project
structure, re-learn your conventions, and repeat mistakes they made last week.
Without a persistence mechanism, every session is Session Zero.

## The Solution

Three documents + two Python modules that form a closed loop, integrated into LMM:

```
┌─────────────────────────────────────────────────────────┐
│                     AGENTS.md                           │
│              (the operating instructions)                │
│  "Use subagents liberally. Write lessons. Verify work." │
│  + LMM tier-aware rules + Rust stack guide              │
└────────────────────┬────────────────────────────────────┘
                     │ prescribes
                     ▼
┌─────────────────────────────────────────────────────────┐
│                  tasks/lessons.md                        │
│              (the empirical memory)                      │
│  "Tier 3: 9B-8Q + 256k context + --long-run = 9h+"     │
└────────────────────┬────────────────────────────────────┘
                     │ validates / grounds
                     ▼
┌─────────────────────────────────────────────────────────┐
│               docs/self_learning.md                      │
│           (the theoretical framework)                    │
│  "Novelty tracker, intrinsic reward, persistence."       │
└─────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│            templates/persistence.py                      │
│        (tier-aware JSON state store)                     │
│  store.record_outcome("subagent", "spawn", ...)          │
└─────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│             templates/novelty.py                         │
│        (exploration / familiarity tracker)               │
│  tracker.get_novelty(state) → 0.0-1.0                    │
└─────────────────────────────────────────────────────────┘
```

| Layer | Role | What it contains |
|---|---|---|
| `AGENTS.md` | **Prescription** — how the agent should behave | Intent classification, delegation, verification, **LMM tier-aware rules**, Rust stack guide |
| `tasks/lessons.md` | **Memory** — what the agent has learned | Tier-scoped empirical findings, failure patterns, fix strategies |
| `docs/self_learning.md` | **Theory** — why the patterns work | Novelty tracking, intrinsic motivation, persistence, provider quality |
| `templates/persistence.py` | **State store** — cross-session JSON persistence | Tier-aware approach tracking, recommendations, atomic writes |
| `templates/novelty.py` | **Exploration** — novelty/familiarity scoring | StateEncoder, NoveltyTracker, temporal decay, eviction |

## How It Works with LMM

### Automatic Tier Detection

When you run `llama-model doctor`, LMM detects your hardware and writes `agent-tier.yaml`:

```yaml
tier: 3
vram_gb: 24
ram_gb: 112
recommended_model: Qwen3.5-9B-8Q
recommended_context: 256k
```

The Learning Loop reads this file and scopes all learning to your tier.

### Session Startup

When a harness (opencode, Claude Code, etc.) starts:

1. Agent reads `agent-tier.yaml` → knows it's Tier 3
2. Agent reads `lessons.md` → finds Tier 3 lessons:
   - "Qwen3.5-9B-8Q with 256k context runs 9+ hour sessions"
   - "GlyphOS full mode (port 4010) handles tool calls correctly"
3. Agent loads `persistence.py` → gets recommendations for Tier 3:
   - debugging → binary_search (92% success, avg 2.1s)
   - subagent → spawn (88% success, avg 5.0s)
4. Agent starts working with proven approaches — no exploration overhead

### During the Session

- Gateway records outcomes: success/failure/latency per domain per tier
- Agent appends lessons after every user correction
- Persistence store updates approach statistics in real-time

### Next Session

Agent starts smarter — knows what works on this tier, what to avoid, and which
approaches have the best track record.

## Installation

Learning Loop is bundled with LMM. After installing LMM:

```bash
# Files are automatically placed in:
~/.config/llama-model-manager/
├── agent-tier.yaml          ← created by `llama-model doctor`
├── agent_state.json         ← persistence store (auto-created)
├── lessons.md               ← your lesson log
└── self_learning.md         ← reference docs
```

### First Run

```bash
# 1. Detect your hardware tier
llama-model doctor

# 2. Start the GlyphOS gateway (auto-configured for your tier)
llama-model gateway start

# 3. Launch your harness
ANTHROPIC_API_KEY=local-test-key claude --bare
# or
opencode --long-run
```

## Tier-Specific Behavior

| Tier | VRAM | RAM | Strategy |
|---|---|---|---|
| **Tier 1** | ≤8GB | ≤16GB | 4B models, no subagents, inline search only |
| **Tier 2** | 12-16GB | 32GB | 7B models, limited subagents, context ≤16k |
| **Tier 3** | 24GB | 64GB+ | 9B-8Q, full subagents, context ≤256k, --long-run |
| **Tier 4** | 48GB+ | 128GB+ | Dual-server, any model, parallel backends |

## Cloud Models + Learning Loop + Quantum Glyphs

Cloud models (GPT-4, Claude Sonnet, Gemini, Grok) are stateless — they forget
everything between sessions. The Learning Loop fixes this by injecting
accumulated knowledge into every cloud model session via the system prompt.

### How It Works

1. **Tier context injection**: Cloud model knows your hardware tier and available local models
2. **Lesson injection**: Cloud model reads proven approaches and failure patterns from prior sessions
3. **GIS1 compression**: Intent descriptions compressed to 10% of original token count
4. **Privacy encoding**: Sensitive context glyph-encoded before cloud transmission
5. **Outcome recording**: Cloud session results stored in persistence store for future sessions

### Benefits

| Benefit | Without Learning Loop | With Learning Loop |
|---|---|---|
| Session memory | Stateless | Remembers 47+ prior sessions |
| Hardware awareness | None | Knows tier, optimizes routing |
| Token efficiency | Verbose | 90% reduction on intent (GIS1) |
| Privacy | Raw context sent | Glyph-encoded before cloud |
| Failure avoidance | Repeats mistakes | Lessons prevent known failures |

## File Reference

| File | Purpose | Action |
|---|---|---|
| `AGENTS.md` | Orchestration rules + LMM tier rules + Rust guide | Read by agent at session start |
| `tasks/lessons.md` | Tier-scoped empirical learning log | Read at start, appended after corrections |
| `docs/self_learning.md` | Research concepts with runnable Python code | Reference for exploration strategies |
| `templates/novelty.py` | `NoveltyTracker` + `StateEncoder` module | Import for novelty scoring |
| `templates/persistence.py` | Tier-aware JSON persistence store | Import for cross-session state |

## License

This framework is published under Apache 2.0. Use it, fork it, adapt it to
your stack. The value is in the loop, not the license.

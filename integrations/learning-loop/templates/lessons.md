# Lessons — LMM Learning Loop

**The empirical memory for AI-assisted development.**

This file is read at the start of every session and appended to after every
correction. Over time it becomes a structured log of what works, what doesn't,
and why — scoped to your hardware tier.

---

## How to Use This File

1. **At session start**: Read this file. Note lessons matching your tier from `agent-tier.yaml`.
2. **After a correction**: Append a new entry. Include tier tag, file paths, failure patterns, fix approach.
3. **Cross-reference**: Add `> **Related concept**:` lines linking lessons to `docs/self_learning.md` concepts.
4. **Review periodically**: Update or consolidate lessons that are superseded.

### Entry format

```markdown
### [Tier N] Short descriptive title
- **Tier**: N
- **What happened**: [concrete description with context]
- **Root cause**: [why it happened, not just what]
- **Fix approach**: [what worked]
- **Prevention**: [how to avoid repeating this]
> **Related concept**: docs/self_learning.md#[section-id]
> — [why this lesson validates or challenges the theory]
```

---

## Reusable Lessons

(These survive across projects — they're about how agents behave, not about specific code.)

- Treat broad AI/static-review findings as hypotheses until verified against actual source. ~60% of AI-generated bug reports are false positives.
- When delegating to subagents, always include explicit scope boundaries (what they MUST NOT touch).
- After any delegation, verify the output against actual source — agents can fabricate file paths, line numbers, and code patterns.
- When debugging: fix root causes, not symptoms. If 3 attempts fail, stop, revert, and escalate to a specialist.
- Recovery paths should be tolerant but not silent. Log warnings for recoverable failures so they're discoverable without crashing.
- Prefer small, focused changes over large refactors. Impact minimal code.
- Cross-reference runtime behavior against repo code — installed copies can drift from source.

---

## Tier-Specific Lessons

(Pre-populated from LMM development. Append new entries below.)

### [Tier 1] Subagent spawning causes OOM on ≤8GB VRAM
- **Tier**: 1
- **What happened**: Explore agent spawned → KV cache overflow → llama-server OOM crash
- **Root cause**: Subagent requires separate context window; 8GB VRAM can't hold both primary + subagent
- **Fix approach**: Skip subagent entirely, use inline grep/AST search instead
- **Prevention**: Check tier before spawning — Tier 1 always uses inline search
> **Related concept**: docs/self_learning.md#1-exploration-vs-exploitation
> — validates that exploration strategy must adapt to hardware constraints

### [Tier 1] Use 4B models only, Q4_K or Q6_K quantization
- **Tier**: 1
- **What happened**: 7B model loaded → immediate OOM or extreme slowdown
- **Root cause**: 7B model weights exceed available VRAM even at Q4_K
- **Fix approach**: Use 4B models with Q4_K (fastest) or Q6_K (better quality)
- **Prevention**: `llama-model doctor` auto-selects 4B for Tier 1
> **Related concept**: docs/self_learning.md#2-state-representation
> — tier state determines viable model selection

### [Tier 3] Qwen3.5-9B-8Q with 256k context runs 9+ hour sessions
- **Tier**: 3
- **What happened**: Loaded 9B-8Q with 256k context on 24GB VRAM + 112GB RAM → ran perfectly for 9 hours
- **Root cause**: 8Q quantization keeps weights in VRAM, context spills to RAM efficiently
- **Fix approach**: Use `--long-run` flag in opencode to prevent timeout
- **Prevention**: This is the proven configuration for Tier 3 marathon sessions
> **Related concept**: docs/self_learning.md#7-persistence
> — validates that persistence of proven configs eliminates repeated experimentation

### [Tier 3] GlyphOS full mode (port 4010) handles tool calls correctly
- **Tier**: 3
- **What happened**: Tool calls failed through port 4000 (legacy claude-gateway)
- **Root cause**: Legacy gateway doesn't extract tool_calls from llama.cpp response
- **Fix approach**: Use port 4010 (GlyphOS full) — extracts tool_calls, converts to Anthropic tool_use blocks
- **Prevention**: Always use port 4010 for tool call support
> **Related concept**: docs/self_learning.md#5-subagent-quality-tracking
> — validates that gateway selection affects tool call reliability

### [Tier 3] GIS1 semantic encoding activates at psi_coherence ≥ 0.7
- **Tier**: 3
- **What happened**: Intent encoded as glyphs → 90% token reduction on routing descriptions
- **Root cause**: Semantic encoder detects high coherence → switches from byte-level to GIS1 wire format
- **Fix approach**: No action needed — automatic based on psi_coherence
- **Prevention**: Monitor encoding_status in gateway logs to verify activation
> **Related concept**: docs/self_learning.md#3-intrinsic-motivation-novelty--learning-progress--surprise
> — validates that encoding format adapts to signal quality

### [Tier 4] Dual-server mode (opt-in) improves subagent throughput
- **Tier**: 4
- **What happened**: Single server bottleneck during parallel subagent spawning
- **Root cause**: One llama-server instance serializes all requests
- **Fix approach**: Primary on 8081, subagent backend on 8082 — parallel request handling
- **Prevention**: Opt-in only — configure via `llama-model enable dual-server`
> **Related concept**: docs/self_learning.md#1-exploration-vs-exploitation
> — validates that high-tier hardware benefits from parallel exploration

---

## Session Log

(Add entries below, most recent first.)

```markdown
# Session YYYY-MM-DD: [Short Description]

## What we learned

### [Tier N] [Specific lesson title]
- **Tier**: N
- **What happened**: [description]
- **Root cause**: [analysis]
- **Fix approach**: [solution]
> **Related concept**: docs/self_learning.md#[section-id]
```

---

## Concept Reference Quick-Links

| Section | Link | When to use |
|---|---|---|
| Exploration vs exploitation | `docs/self_learning.md#1-exploration-vs-exploitation` | Deciding whether to try a novel approach or stick with proven |
| State representation | `docs/self_learning.md#2-state-representation` | Encoding task context for learning |
| Intrinsic motivation | `docs/self_learning.md#3-intrinsic-motivation-novelty--learning-progress--surprise` | Breaking out of local optima, tracking surprise |
| Goal discovery | `docs/self_learning.md#4-goal-discovery` | Long-running sessions with shifting objectives |
| Subagent quality tracking | `docs/self_learning.md#5-subagent-quality-tracking` | Learning which agents/approaches work per task type |
| Autonomy levels | `docs/self_learning.md#6-autonomy-levels` | Adaptive confidence-based autonomy |
| Persistence | `docs/self_learning.md#7-persistence` | Cross-session learning, JSON state store |

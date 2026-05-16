# Workflow Orchestration

## 1. Plan Node Default
- Enter plan mode for **ANY** non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, **STOP** and re-plan immediately — don’t keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

## 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution
- > **Related**: [`docs/self_learning.md#1-exploration-vs-exploitation`](docs/self_learning.md#1-exploration-vs-exploitation) — this explore/exploit tradeoff is formalized there, with epsilon decay and failure-triggered exploration resets.

## 3. Self-Improvement Loop
- After **ANY** correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project
- > **Related**: [`docs/self_learning.md#7-persistence`](docs/self_learning.md#7-persistence) — lessons.md IS the persistence store; the persistence section describes how to formalize it into structured learnings across sessions.

## 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

## 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

## 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management
1. **Plan First**: Write plan to `tasks/todo.md` with checklist
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/...`
6. **Capture Lessons**: Update `tasks/lessons.md` after

## Core Principles
- **Simplicity First**: Make every change as simple as possible. Impact minimal code
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards

## Tool-Call Contract (Strict)
1. Invoke tools directly with required structured arguments. Never print tool calls as text, markdown, or prose.
2. Never prefix shell commands with "$". Never emit duplicate keys.
3. Always include every required field (description + command for bash; subagent_type, run_in_background, load_skills, description, prompt for task).
4. One tool call at a time unless the runtime explicitly supports parallel calls.
5. **REPAIR (one shot)**: If your previous output contained a malformed tool call, re-emit ONLY the corrected structured invocation. Do not explain, add markdown, or add prose. If the repair also fails, the system will hard-fail.
6. **TOOL FAILURE**: If a tool returns an error, fix the root cause. Never retry with identical args. Never switch to printing pseudo-calls.
7. **LANE-SPECIFIC (local GlyphOS/llama.cpp)**: Zero tolerance for pseudo-calls. If a tool is needed, invoke it directly in structured form.

## Context Budget / File Reading Rules

### Why this matters

The local llama.cpp backend has a context window (`n_ctx`, typically 65536 tokens).
Requesting inference with more tokens than `n_ctx` causes the backend to return
HTTP 400, wasting the round-trip.  The LMM gateway now pre-checks the estimated
token count before forwarding and rejects oversized requests with a clear
message.

### File reading rules (all agents)

Do not read whole files by default.

1. Use `rg`, `grep`, or symbol search to locate relevant functions/classes.
2. Read only the relevant function, class, or ~120 lines around the match.
3. If more context is needed, request another narrow range.
4. Avoid generated files, lockfiles, build artifacts, large logs, `.old` files,
   cache files, and vendored files unless explicitly required.
5. When a file has already been read, do not reread it fully.  Use targeted
   search or refer to the previous summary.
6. Keep total working context below 60k tokens unless explicitly told otherwise.
7. If context is getting large, compact findings into a short summary before
   continuing.
8. Only read an entire file if you have enough context available and are
   explicitly requested to do so.

### Gateway context budget

The gateway respects these environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `LMM_MAX_CONTEXT_TOKENS` | 65536 | Backend context window (`n_ctx`) |
| `LMM_CONTEXT_SAFETY_MARGIN` | 2048 | Headroom subtracted from max |
| `LMM_CONTEXT_OVERFLOW_MODE` | reject | `reject` \| `compact` \| `truncate` |
| `LMM_AGENT_SOFT_CONTEXT_LIMIT` | 60000 | Soft target for agent self-regulation |

When a request exceeds `max_tokens - safety_margin`, the gateway returns a
structured 400 error with the estimated count, budget, and actionable guidance.

### Increasing n_ctx on llama.cpp

The `n_ctx` value is set when launching `llama-server`.  The model entry in
`~/.config/llama-server/models.tsv` has a dedicated context column (the 4th
TSV column, also settable via `llama-model add --context N`).  The launcher
always emits `-c "$context"` before any `extra_args`, so context flags in
`extra_args` produce duplicate flags and stale state file entries.

Use the context column or `--context` flag instead of `extra_args`:

```bash
llama-model add my-model /path/to/model.gguf --context 81920
```

or edit the TSV context column directly:

```
my-model	/path/to/model.gguf		81920	999	128	16	1
```

The launcher validates and rejects `--ctx-size`, `--context-size`, and
`-c` inside `extra_args` at startup.

If no explicit context is set, the llama.cpp binary uses its compiled default
(usually the model's `context_length` metadata field from the GGUF header).
The `llama-model` launcher defaults `LLAMA_SERVER_CONTEXT` to 128000; set
this env var in `~/.config/llama-server/defaults.env` to override.

**Warning**: higher `n_ctx` increases KV-cache memory and attention
computation.  On a system with 12 GB VRAM and 48 GB RAM, increasing from 65536
to 81920 is usually safe.  Going beyond 98304 may cause out-of-memory errors
or significant slowdown.

## No-Clobber / Source-of-Truth Rules

Do not assume a missing string in one file is a regression until you verify
the intended layer.

Context-budget and security-guard ownership:

- `scripts/lmm_config.py` owns `ContextBudgetConfig` and env validation.
- `scripts/gateway/handlers_openai.py` owns context-budget request rejection.
- `bin/llama-model` owns launcher propagation and active context detection.
- `bin/llama-model-gui` owns Zenity GUI status/model registry behavior.
- `web/app.js` owns dashboard frontend controls and client-side extra_args
  validation.
- `web/app.py` owns dashboard backend API, static serving, download
  orchestration, and model/defaults persistence.

Before claiming a regression:

1. Run `git log -S <needle> -- <file>` to check whether the string ever
   existed in that file.
2. Check whether the guard belongs in another layer (see ownership above).
3. Compare repo and runtime copies if runtime behavior differs.
4. Prefer targeted patches; never rewrite full production files from stale
   context.

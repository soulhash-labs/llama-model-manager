# Workflow Orchestration — LLM Model Manager + Learning Loop

**The operating instructions for AI-assisted development.**

These rules govern how the agent approaches tasks, delegates work, captures
learnings, and verifies results. Adapt the tool names, file paths, and
verification commands to your tech stack.

---

## 1. Task Classification (Intent Gate)

Before acting on any request, classify it:

| Request type | What it means | Default approach |
|---|---|---|
| **Trivial** | Single file, known location, direct answer | Execute directly |
| **Explicit** | Specific file/line, clear command | Execute directly |
| **Exploratory** | "How does X work?", "Find Y" | Search first, synthesize, answer |
| **Open-ended** | "Improve", "Refactor", "Add feature" | Assess codebase first, propose plan |
| **Ambiguous** | Unclear scope, multiple interpretations | Ask ONE clarifying question |

If the request could be interpreted 2+ ways with 2x+ effort difference,
**must ask** before proceeding.

> **Related**: [`docs/self_learning.md#2-state-representation`](docs/self_learning.md#2-state-representation)
> — this classification encodes the task state, which is the foundation for
> learning action-outcome associations per task type.

## 2. Explore Before Commit

For anything non-trivial, gather context before diving in:

1. Search the codebase for relevant patterns (grep, AST search, symbol lookup)
2. Read only what you need — ~120 lines around the match, not whole files
3. For unfamiliar libraries: check documentation or open-source examples
4. Parallelize independent searches (fire 2-5 searches simultaneously)
5. Stop searching when you have enough context to proceed confidently

**Avoid these** unless explicitly needed: lockfiles, build artifacts, generated
code, vendored dependencies, large log files.

> **Related**: [`docs/self_learning.md#1-exploration-vs-exploitation`](docs/self_learning.md#1-exploration-vs-exploitation)
> — formalizes this explore/exploit tradeoff with epsilon decay and
> failure-triggered exploration resets.

## 3. Subagent Strategy

- Delegate research, exploration, and parallel analysis to subagents
- One task per subagent for focused execution
- Always include explicit scope boundaries (what the subagent MUST and MUST NOT do)
- Verify subagent output against the actual source — agents can hallucinate
- For complex or high-risk tasks, consult a specialist agent before implementing

```python
# Good delegation pattern:
task(
    subagent_type="explore",
    prompt="Search for auth middleware patterns in src/. Return file paths and pattern descriptions. MUST NOT modify any files.",
    run_in_background=True,
)
```

## 4. Self-Improvement Loop

This is the core of the Learning Loop:

1. **After any correction** from the user: write the pattern to `tasks/lessons.md`
2. **At session start**: read `tasks/lessons.md` for relevant prior learnings
3. **Cross-reference**: annotate lessons with links to `docs/self_learning.md` concepts
4. **Ruthlessly iterate**: the goal is zero repeat mistakes

```markdown
### What we learned
- [specific, actionable lesson from the correction]
> **Related concept**: docs/self_learning.md#5-provider-quality-tracking
> — this validates the theory that [specific concept applies here]
```

> **Related**: [`docs/self_learning.md#7-persistence`](docs/self_learning.md#7-persistence)
> — lessons.md IS the persistence store; formalizing it into structured data
> across sessions compounds the learning.

## 5. Verification Before Done

Never mark a task complete without proving it works:

1. **Lint/type check**: run diagnostics on changed files
2. **Build**: compile or transpile to catch integration errors
3. **Test**: run relevant tests (not the full suite unless requested)
4. **Diff**: review your changes — "Would a staff engineer approve this?"

**If verification fails:**
- Fix only what you broke (not pre-existing issues unless asked)
- If 3 consecutive fix attempts fail: **STOP. Revert. Consult a specialist.**
- Never leave code in a broken state

## 6. Demand Elegance

- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: re-implement the clean solution
- Skip this for trivial fixes — don't over-engineer
- Challenge your own work before presenting it

## 7. Tool-Call Contract

1. Always include required fields for every tool invocation
2. Never print tool calls as text — invoke them directly
3. On tool failure: fix the root cause, don't retry with identical args
4. On malformed output: emit the corrected invocation in one shot
5. Prefer existing libraries over adding new dependencies
6. Prefer small, focused changes over large refactors

## 8. LMM Tier-Aware Rules

These rules apply when running inside Llama Model Manager with hardware tier detection.

### Tier Detection

At session start, read `agent-tier.yaml` to determine hardware capability:

| Tier | VRAM | RAM | Strategy |
|---|---|---|---|
| **Tier 1** | ≤8GB | ≤16GB | Use 4B models, skip subagents, inline search only |
| **Tier 2** | 12-16GB | 32GB | Use 7B models, limited subagents, context ≤16k |
| **Tier 3** | 24GB | 64GB+ | Use 9B models, full subagent support, context ≤256k |
| **Tier 4** | 48GB+ | 128GB+ | Dual-server mode, any model, opt-in parallel backends |

### Tier-Specific Behaviors

**Tier 1 (≤8GB VRAM):**
- Never spawn subagents — causes OOM
- Use 4B quantized models (Q4_K or Q6_K)
- Context limit: 8k tokens
- Skip GlyphOS full mode — use fast mode (port 4011)
- Delegate complex tasks to cloud models

**Tier 2 (12-16GB VRAM):**
- Subagents OK for simple exploration, not for heavy analysis
- Use 7B models (Q4_K or Q5_K)
- Context limit: 16k tokens
- GlyphOS fast mode recommended
- Cloud fallback for tasks requiring >16k context

**Tier 3 (24GB VRAM + 64GB+ RAM):**
- Full subagent support — spawn explore/librarian agents freely
- Use 9B models (8Q quantization fits in VRAM)
- Context up to 256k (VRAM + RAM combined)
- GlyphOS full mode (port 4010) — tool calls, semantic encoding, context pipeline
- Use `--long-run` flag in opencode for 9+ hour sessions
- Single llama-server handles all workloads

**Tier 4 (48GB+ VRAM):**
- Dual-server mode (opt-in): primary on 8081, subagent backend on 8082
- Any model size, any context length
- GlyphOS full mode with parallel backend support
- Best for marathon sessions, large codebase analysis

### Cloud vs Local Routing

- **Quick fixes** (<30s): always use local model
- **Complex architecture**: delegate to cloud model with tier context injected
- **Debugging**: try local binary_search first, escalate to cloud after 3 failures
- **Code review**: local for small files, cloud for large modules
- **Long sessions** (>2h): use `--long-run` flag + local model to avoid cloud costs

### GlyphOS Gateway

- Port 4010 = full mode (context pipeline + routing + semantic encoding + tool calls)
- Port 4011 = fast mode (basic routing, lower latency)
- Port 4000 = removed (deprecated; Anthropic handled natively on 4010)
- Tool calls work through GlyphOS — use `tool_choice` for forced tool use
- GIS1 semantic encoding activates automatically when psi_coherence ≥ 0.7

### Persistence-Aware Behavior

- Read `~/.config/llama-model-manager/agent_state.json` at session start
- Apply recommended approaches for current tier
- Record outcomes after each task (success/failure/latency)
- Append lessons after every user correction

## 9. Stacks

<!--
  Add stack-specific sections below. Each section is the AGENTS.md fragment that
  a project using that language/stack would include. The Customization Guide at
  the bottom remains the cross-stack placeholder reference.
-->

### Rust

#### Code Style

- Inline format args — use `format!("{x}")` not `format!("{}", x)` ([`uninlined_format_args`](https://rust-lang.github.io/rust-clippy/master/index.html#uninlined_format_args)).
- Collapse nested `if` statements where possible ([`collapsible_if`](https://rust-lang.github.io/rust-clippy/master/index.html#collapsible_if)).
- Prefer method references over closures ([`redundant_closure_for_method_calls`](https://rust-lang.github.io/rust-clippy/master/index.html#redundant_closure_for_method_calls)).
- Make `match` statements exhaustive — avoid wildcard arms.
- Do not create small helper methods that are only referenced once.
- Prefer private modules with explicitly exported public API.

#### API Design

Avoid `bool` or ambiguous `Option` parameters that produce unreadable callsites
like `foo(false)` or `bar(None)`. Prefer enums, named methods, or newtypes that
keep callsites self-documenting.

When you cannot change the API and must pass an opaque literal positionally,
use an argument comment:

```rust
foo(/*enable_cache*/ true, /*timeout_ms*/ 500)
```

- The comment must exactly match the parameter name in the callee's signature.
- String and char literals are exempt — only use comments where they add real clarity.

#### Async Traits

Do **not** use `#[async_trait]` or `#[allow(async_fn_in_trait)]`.

Prefer native RPITIT with explicit `Send` bounds:

```rust
// Trait definition
fn foo(&self) -> impl std::future::Future<Output = T> + Send;

// Implementation (async fn is fine here)
async fn foo(&self) -> T { ... }
```

#### Documentation

- Newly added traits must include doc comments explaining their role and how
  implementations are expected to use them.
- When adding or changing a public API, update any relevant documentation
  alongside the code change.

#### Module & File Size

- Target modules under **500 LoC**, excluding tests.
- If a file exceeds ~**800 LoC**, add new functionality in a new module rather
  than extending the existing file.
- When extracting code into a new module, move the related tests and doc
  comments with it — keep invariants close to the code that owns them.

#### Testing

**Assertions**
- Use `pretty_assertions::assert_eq` for clearer diffs. Import it at the top of
  each test module that needs it.
- Compare whole objects with `assert_eq!` rather than asserting individual
  fields one by one.
- Avoid mutating the process environment in tests. Pass environment-derived
  values as arguments instead.

**Running Tests**
- Run the tests for the specific crate you changed:
  ```sh
  cargo test -p <crate-name>
  ```
- Avoid `--all-features` for routine local runs — it significantly expands the
  build matrix and disk usage. Use it only when you specifically need full
  feature coverage.
- Ask before running the full workspace test suite (`cargo test` with no `-p`
  flag) — it can be slow and is usually unnecessary for scoped changes.

**Snapshot Tests**
Any change that affects user-visible output must include updated
[`insta`](https://insta.rs) snapshot coverage. Add a new snapshot test if one
doesn't exist, or update existing snapshots and include the reviewed `.snap`
files in the same commit.

```sh
cargo test -p <crate-name>                        # generates *.snap.new files
cargo insta pending-snapshots -p <crate-name>     # list what's pending
cargo insta accept -p <crate-name>                # accept all for this crate

# Install if needed:
cargo install cargo-insta
```

#### Formatting & Linting

Run `cargo fmt` and `cargo clippy` after finishing code changes — no need to
ask for approval:

```sh
cargo fmt
cargo clippy -p <crate-name>    # scoped to avoid slow workspace-wide builds
```

Do not re-run tests after formatting or linting.

#### Patience with Rust Commands

Rust compilation and lock acquisition can be slow. Never attempt to kill a
running `cargo` command by PID. Wait for it to complete.

## Customization Guide

For your project, replace these placeholders:

| Placeholder | Your value |
|---|---|
| Source directory | `src/` or `lib/` or `app/` |
| Test command | `pytest`, `jest`, `go test`, `cargo test` |
| Lint/type check | `ruff`, `eslint`, `tsc --noEmit`, `golangci-lint` |
| Build command | `make`, `npm run build`, `cargo build`, `go build` |
| Task tracking | `tasks/todo.md` |
| Lesson store | `tasks/lessons.md` |
| Concept reference | `docs/self_learning.md` |
| Tier config | `~/.config/llama-model-manager/agent-tier.yaml` |
| Persistence store | `~/.config/llama-model-manager/agent_state.json` |

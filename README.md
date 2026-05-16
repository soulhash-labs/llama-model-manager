# 🦙 Llama Model Manager

**by soulhash.ai**

## ⚡ The engine room for local AI

**llama-model-manager** turns raw `llama.cpp` inference into a stable, production-grade local AI platform. It gives you a clean browser dashboard, intelligent routing, project-aware context, GlyphOS™ AI Compute, and a cross-session Learning Loop — all while staying sovereign and local-first.

If you're running Claude Code, OpenClaw, or opencode, this is where your reliability lives.

![Dashboard overview](docs/screenshots/dashboard-overview.png)

---

## 🚀 One-line install

```bash
curl -fsSL https://soulhash.ai/install_lmm.sh | sh
```

Then run:

```bash
llama-model-web          # Browser dashboard
llama-model doctor       # System health check
llama-model list         # See your models
```

Or install from source:

```bash
git clone https://github.com/soulhash-labs/llama-model-manager.git
cd llama-model-manager
./install.sh
```

**Zero root required.** Installs to `~/.local/`. Asks before building anything.

---

## 🧩 Core Capabilities

### 🔱 GlyphOS AI Compute

Intelligent routing + context compression layer.

![GlyphOS encoding demo](docs/branding/glyphos-encoding-demo.gif)

- **SI Transport Builder** — full-featured glyph packet encoding with roundtrip verification and SHA-256 integrity
- **Semantic Encoder/Decoder** — intent-to-glyph conversion with GE1-JSON / GE1-LINES compression
- **Adaptive Routing** — psi coherence, action type, and context quality aware
- **Local-First Guarantee** — all local traffic goes through the unified GlyphOS pipeline
- **Cloud Fallback** — privacy-preserving cloud routing with instruction headers and anonymized learning context

### 🧠 Context Mode MCP

Project-aware memory for your AI.

- **Automatic project indexing** (FTS5)
- **Smart context retrieval** + injection
- **Context quality scoring** (0.0–1.0)
- **Graceful fallback** on empty/degraded results

### 🔄 Learning Loop

Cross-session memory that compounds. AI agents normally start every session from scratch — the Learning Loop fixes this.

- **Persistence store** — records success/failure/latency per task type, scoped to your hardware tier
- **Lessons log** — empirical findings appended after every correction, preventing repeat mistakes
- **Novelty tracker** — scores familiarity with code patterns to decide when to explore vs. exploit
- **Cloud injection** — accumulated knowledge is glyph-encoded and injected into cloud model sessions via system prompts
- **Tier-aware** — strategies and recommendations adapt to your VRAM/RAM capability

### 📊 Dashboard + Observability

Clean browser UI with real-time health, model switching, cloud configuration, and run records.

- **Cloud config card** — toggle cloud fallback, select preferred provider (OpenAI / Anthropic / xAI), paste API keys
- **Context + GlyphOS readiness** — combined pipeline view with one-click activation
- **Download queue** — pause/resume/retry lifecycle with duplicate detection and cleanup
- **Activity feed** — control-plane actions, session handoffs, and audit trail

---

## 🖥️ Hardware Tier Detection

Run `llama-model doctor` and LMM detects your VRAM/RAM, classifying you into a tier:

| Tier | VRAM | RAM | Strategy |
|:----:|:----:|:---:|:---------|
| **Tier 1** | ≤8GB | ≤16GB | 4B models, no local subagents, context ≤8k |
| **Tier 2** | 12-16GB | 32GB | 7B models, limited subagents, context ≤16k |
| **Tier 3** | 24GB | 64GB+ | 9B models, full subagent support, context ≤256k |
| **Tier 4** | 48GB+ | 128GB+ | Dual-server mode, any model, parallel backends |

### Subagent Delegation by Tier

oh-my-openagent spawns subagents by making API calls to the LMM gateway. The gateway's router then decides where inference actually runs — **local** llama.cpp or **cloud** API. This means subagents work on every tier; the question is where the compute happens:

- ☁️ **Cloud-enabled subagents**: inference runs on OpenAI/Anthropic/xAI. Zero local VRAM used. Works on all tiers.
- 💻 **Local-only subagents**: inference runs on your GPU. Requires VRAM headroom. OOM risk on Tier 1.

The Learning Loop's tier rules tell the AI agent which path to choose, and the gateway enforces it by routing accordingly.

| Tier | Local subagents | Cloud subagents |
|:----:|:---------------:|:---------------:|
| **Tier 1** | ❌ OOM risk — avoid | ✅ Recommended escape hatch |
| **Tier 2** | ⚠️ Limited (simple exploration only) | ✅ For heavy analysis |
| **Tier 3** | ✅ Full support | ✅ For marathon sessions |
| **Tier 4** | ✅ Dual-server parallel backends | ✅ Optional |

> 💡 **Tier 1 users:** If you enable cloud fallback in the dashboard, your harness can still spawn subagents — they just run on cloud infrastructure instead of your local GPU. The Learning Loop records this lesson so future sessions automatically route complex tasks to cloud rather than attempting local parallelization.

---

## 💎 Why it matters

| Benefit | How it works |
|:--------|:-------------|
| 🏠 **Stay local** | Local-first routing with GlyphOS pipeline. Cloud only when you want it. |
| 🔒 **Stay sovereign** | Your data never leaves your machine unless you explicitly choose cloud. |
| ⚡ **Stay fast** | SI transport compression reduces intent tokens by ~90%. Auto-fit optimizes GPU usage. |
| 🛡️ **Stay stable** | Context quality scoring, graceful degradation, guarded runtime startup. |
| 📈 **Stay observable** | Real-time dashboard, doctor diagnostics, detailed telemetry. |
| 🧠 **Stay smarter** | Learning Loop remembers what works. Each session inherits proven approaches from the last. |

---

## 📦 What ships

| Component | Purpose |
|:----------|:--------|
| `llama-model` | Main CLI (list, switch, doctor, sync, learn, gateway, etc.) |
| `llama-model-web` | Browser dashboard |
| `llama-model-gui` | Desktop launcher |
| `GlyphOS AI Compute` | Bundled public routing + encoding engine |
| `Context Mode MCP` | Optional indexed context system |
| `Learning Loop` | Cross-session persistence, lessons, novelty tracking |
| `oh-my-openagent` | OpenCode plugin for subagent delegation and task() dispatch |
| `install.sh` + `safe_install` | Portable installer (works on Alpine/minimal systems) |

---

## 🏁 Quick Start

```bash
llama-model doctor
llama-model build-runtime --backend auto
llama-model-web
```

**Recommended first commands:**

| Command | What it does |
|:--------|:-------------|
| `llama-model doctor` | Detect your hardware tier |
| `llama-model list` | See your models |
| `llama-model sync-opencode --preset balanced` | Point OpenCode at the LMM gateway |

---

## 🏗️ Architecture

```
Browser Dashboard / CLI / Desktop GUI
         ↓
   LMM Gateway (GlyphOS)
   ┌──────────────────────────────────────┐
   │ Context MCP     → Indexed project search
   │ Semantic Encoder → Intent-to-glyph (GIS1)
   │ SI Transport    → Roundtrip-verified packets
   │ Adaptive Router → Local-first + cloud fallback
   │ Learning Loop   → Cross-session persistence
   └───────────────┬──────────────────────┘
                   │
     ┌─────────────┴──────────────┐
     │                            │
llama.cpp (local)          Cloud (OpenAI / Anthropic / xAI)
  local inference            glyph-encoded + lesson-injected
                             privacy-preserving routing
```

---

## 🔍 Key Features Deep Dive

### 🏠 Local-First Guarantee

All local `llama.cpp` traffic is routed through the unified GlyphOS pipeline. No more direct bypasses.

### ☁️ Cloud Control

Configure cloud fallback directly from the dashboard:

- **Enable Cloud Fallback** — master toggle
- **Preferred Provider** — auto / OpenAI / Anthropic / xAI
- **API Key fields** — masked password inputs for each provider
- **Model selection** — pick which cloud model each provider uses
- **Gateway restart notification** — UI warns you when cloud config changes require a restart

API keys can also come from env vars (`GLYPHOS_CLOUD_OPENAI_API_KEY`, `OPENAI_API_KEY`, etc.) or `~/.glyphos/config.yaml`.

### 🔐 Cloud Glyph Injection

When routing to cloud models, LMM doesn't send raw prompts. It builds a structured payload:

1. **Instruction header** — tells the cloud model it's a co-processor in a GlyphOS pipeline
2. **GIS1 glyph** — compressed intent (action, destination, confidence, time slot)
3. **Anonymized learning context** — proven lessons and strategies (no hardware specs, no raw user data)
4. **Original prompt** — appended at the end so the cloud model has full context

### 🧠 Context Intelligence

Auto-indexing + quality-aware retrieval with graceful degradation.

### 🔄 Learning Loop in Action

```
Session 1: Agent tries subagent delegation → fails (OOM on Tier 1)
           → Lesson recorded: "Tier 1: delegate to cloud, not local subagents"

Session 2: Agent reads lessons.md → knows to use cloud for complex tasks
           → Success. Outcome recorded in persistence store.

Session 3: Agent starts with proven approach → no exploration overhead
           → Cloud model receives glyph-encoded lessons from Sessions 1-2
```

### 🌍 Hybrid Global/Local Design

The Learning Loop uses a **hybrid** model — hardware strategies are global (your machine doesn't change between projects), while project-specific lessons stay per-repo (no cross-contamination):

```
~/.config/llama-model-manager/          ← Global (shared across all projects)
├── agent-tier.yaml                     ← Hardware tier (VRAM/RAM)
├── agent_state.json                    ← Tier-scoped strategies (compounds across repos)
└── lessons.md                          ← Universal lessons (hardware, routing, OOM)

~/projects/my-app/                      ← Per-repo (project-specific)
├── AGENTS.md                           ← Agent instructions (can extend global)
└── tasks/
    └── lessons.md                      ← Project-specific lessons
```

**Workflow:**

```bash
# After install — initialize global store (done once)
llama-model learn init

# For each new project — create per-repo files
cd ~/projects/my-new-app
llama-model learn init-project

# Export/import with --global flag
llama-model learn export --global       # Export to global config dir
llama-model learn import --global data.json  # Import into global store
llama-model learn export ./backup.json  # Export to current directory
```

| What | Scope | Example |
|:-----|:-----:|:--------|
| Hardware tier | 🌍 Global | "Tier 1: 8GB VRAM" |
| Strategy stats | 🌍 Global | "debugging → binary_search: 92% success" |
| Universal lessons | 🌍 Global | "Never spawn subagents on Tier 1" |
| Project lessons | 📁 Per-repo | "This project uses FastAPI, not Django" |
| AGENTS.md | 📁 Per-repo | Custom orchestration rules for this project |

---

## 🤖 oh-my-openagent Integration

oh-my-openagent is an OpenCode plugin that adds agent orchest capabilities:

- **Background subagents** — OpenCode spawns parallel explore/librarian agents
- **`task()` delegation** — structured task dispatch with skills and categories
- **Model fallback** — routes to cloud when local models can't handle a task
- **Hot patches** — wake patch and task defaults patch applied and managed by LMM

LMM manages the full lifecycle:

| Command | What it does |
|:--------|:-------------|
| `llama-model sync-oh-my-openagent` | Syncs config to point at the LMM gateway |
| `llama-model opencode-plugin enable-oh-my-openagent` | Enables the plugin in OpenCode config |
| `llama-model opencode-plugin disable-oh-my-openagent` | Disables and backs up plugin entries |
| `llama-model doctor` | Reports version, patch status, auto_update, stale models, recent errors |

The dashboard defaults form includes a **Sync oh-my-openagent** toggle (default: enabled) and a config file path field. When enabled, every model switch automatically updates the oh-my-openagent config to match the active LMM gateway endpoint.

---

## 📥 Installation & Portability

- ✅ Works on Ubuntu, Debian, Fedora, Alpine, Docker, and stripped containers
- ✅ `safe_install` fallback (no dependency on GNU `install`)
- ✅ No silent compilation — always asks
- ✅ Everything installs under `~/.local/`

---

## ⌨️ Common Commands

```bash
llama-model doctor                          # Detect hardware tier
llama-model list                            # See your models
llama-model switch qwen3.5-8b-q8            # Switch active model
llama-model sync-opencode --preset balanced # Sync OpenCode
llama-model sync-glyphos                    # Sync GlyphOS config
llama-model sync-oh-my-openagent            # Sync oh-my-openagent
llama-model gateway start                   # Start LMM gateway
llama-model learn status                    # Check Learning Loop state
llama-model learn init                      # Initialize global store (once)
llama-model learn init-project              # Initialize per-repo files (per project)
```

---

## 📋 What `install.sh` does

- ✅ Installs the CLI, web UI, desktop launcher, help text, and example config files
- ✅ Copies bundled runtime assets if this repo already contains them
- ✅ In an interactive terminal, offers to check and install missing build dependencies and compile a local runtime
- 🚫 Does **not** silently compile `llama.cpp` — it only launches the runtime build flow if you agree
- 🚫 Does **not** silently install OS packages or GPU SDKs

### After install

```bash
llama-model-web
llama-model list
llama-model doctor
llama-model build-runtime --backend auto
```

### Recommended first-run flow

```bash
./install.sh
llama-model doctor
llama-model build-runtime --backend auto
llama-model doctor
llama-model-web
```

If `doctor` reports `binary_status: unavailable`, install the missing build dependencies for that machine and run `build-runtime` again.

---

## 🔧 Optional dashboard background service

The dashboard runs on demand by default. You can opt into a managed `systemd --user` service if you want a stable local dashboard URL without launching it manually.

```bash
llama-model dashboard-service install
llama-model dashboard-service enable
llama-model dashboard-service status
```

| Detail | Value |
|:-------|:------|
| Unit | `llama-model-web.service` |
| URL | `http://127.0.0.1:8765/` |

> ⚠️ The background service is optional and is **never** enabled by default.

---

## 🔒 Dashboard safety defaults

The dashboard binds to `127.0.0.1` by default. API responses use structured JSON errors with stable `code` fields. State-changing API payloads are schema-checked and reject unknown fields. Request bodies are capped by `LLAMA_MODEL_WEB_MAX_REQUEST_BYTES`.

If you intentionally bind the dashboard beyond localhost, set the hardening knobs explicitly:

```bash
export LLAMA_MODEL_WEB_HOST=0.0.0.0
export LLAMA_MODEL_WEB_API_TOKEN='replace-with-a-long-random-token'
export LLAMA_MODEL_WEB_ALLOWED_HOSTS='127.0.0.1,192.168.1.25'
llama-model-web --no-browser
```

Remote clients must send either:

- `X-LLAMA-MODEL-MANAGER-TOKEN: <token>`
- `Authorization: Bearer <token>`

> 🛡️ Localhost clients remain convenient for normal single-user workflows. External binds should be treated as operator-controlled surfaces, not public internet endpoints.

---

## 🔄 Runtime portability

llama.cpp source is portable, but built `llama-server` binaries are backend-, platform-, and architecture-specific. This repo does not assume one bundled GPU binary works everywhere. `llama-model doctor` reports host backends, selected binary source, and compatibility status.

### What `llama-model build-runtime` does

- 📥 Clones or updates `https://github.com/ggml-org/llama.cpp.git`
- 🔖 Checks out the configured `llama.cpp` ref
- 🔨 Builds a host-specific `llama-server` runtime for the selected backend
- 🔄 Also builds a CPU fallback runtime
- 📝 Writes compatibility metadata so the manager can reject mismatched bundled binaries later

### What it does **not** do

- 🚫 Does **not** silently run `apt`, `dnf`, `pacman`, `brew`, or any other package manager without asking first
- 🚫 Does **not** install unsupported toolchains or SDK paths by guesswork
- 🚫 Does **not** try to guess a safe third-party GPU binary from another machine

### Interactive dependency assistance

When `build-runtime` sees missing build tools in an interactive terminal, it tells you what's missing, shows the install commands it plans to run, and asks for confirmation first. If the host package manager is unsupported, the script stops and tells you what to install manually.

### 📥 Remote model downloads

The dashboard can search Hugging Face for cached GGUF artifacts, annotate basic fit signals, and queue downloads through a serialized lifecycle. Download jobs are stored under `~/.local/state/llama-server/download-jobs.json`, so the UI can recover stale workers and the CLI can inspect or cancel jobs even when the browser is closed.

```bash
llama-model download-jobs
llama-model download-cancel <job_id>
llama-model download-retry <job_id>
```

---

## 🔌 Supported integrations

| Integration | What it does | CLI |
|:------------|:-------------|:----|
| **opencode** | Syncs to the live local OpenAI-compatible `llama.cpp` endpoint | `llama-model sync-opencode --preset balanced\|long-run` |
| **oh-my-openagent** | Subagent delegation, task() dispatch, model fallback for OpenCode | `llama-model sync-oh-my-openagent` |
| **OpenClaw** | Syncs to the live local OpenAI-compatible `llama.cpp` endpoint | `llama-model sync-openclaw` |
| **Harness gateway** | OpenAI-compatible routed gateway in front of Context/GlyphOS/local llama.cpp | `llama-model gateway start\|stop\|restart\|status\|logs` |
| **Claude Code** | Syncs local Claude settings to a local Anthropic-compatible gateway | `llama-model sync-claude` |
| **Claude gateway** | Local bridge in front of the active `llama.cpp` endpoint for Claude Code compatibility | `llama-model claude-gateway start\|stop\|restart\|status\|logs` |
| **GlyphOS AI Compute** | Syncs `~/.glyphos/config.yaml` to the active local `llama.cpp` runtime | `llama-model sync-glyphos` |

These integrations are optional. The default product behavior remains the local `llama.cpp` runtime plus the on-demand dashboard.

Manage the routed harness gateway with `llama-model gateway start|stop|restart|status|logs`.
Use `llama-model sync-opencode --mode direct` when an OpenAI-compatible client must bypass the gateway and call the raw backend endpoint.
Override the long-run reservation with `OPENCODE_COMPACTION_RESERVED` when a harness needs a fixed compaction headroom.

### 🐂 Claude Code Quick Start

After syncing, Claude Code works with **no flags** — just run `claude`.

```bash
# 1. Start the Claude gateway (translates Anthropic protocol to local llama.cpp)
llama-model claude-gateway start

# 2. Sync your settings (writes ~/.claude/settings.json with local endpoint + dummy key)
llama-model sync-claude

# 3. Just run Claude — no env vars, no --bare flag needed
claude
```

**What `sync-claude` writes to `~/.claude/settings.json`:**

```json
{
  "model": "qwen35-9b-q8",
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:4000",
    "ANTHROPIC_MODEL": "qwen35-9b-q8",
    "ANTHROPIC_API_KEY": "local-dev-token"
  }
}
```

Claude Code reads this file automatically on startup. The `ANTHROPIC_API_KEY` is a placeholder — the gateway doesn't validate it. All traffic stays local.

> 🔄 **After each model switch**, if `LLAMA_MODEL_SYNC_CLAUDE=1` (opt-in), LMM automatically updates the settings file so Claude Code always points at the active model.

**Ad-hoc override** (bypasses settings.json):

```bash
ANTHROPIC_API_KEY=local-test-key claude --bare
```

Use this for one-off testing or debugging. Not needed for normal use.

### Client sync details

- `opencode` keeps its own local client config in `~/.config/opencode/opencode.json`, so it can keep pointing at a stale GGUF even after `llama-model switch`.
- Successful model switches auto-run the OpenCode sync by default with `LLAMA_MODEL_SYNC_OPENCODE=1`; set it to `0` for manual-only sync.
- `llama-model sync-opencode` updates the `llamacpp` provider endpoint, default model, and local model-state wiring to match `llama-model current`. The default route mode is `routed`, which points OpenAI-compatible harnesses at the LMM gateway on `http://127.0.0.1:4010/v1`.
- In routed mode, `sync-opencode` and `sync-openclaw` start or verify the LMM gateway so clients do not land on a refused `127.0.0.1:4010` connection. Set `LLAMA_MODEL_AUTOSTART_GATEWAY_ON_SYNC=0` only if you manage the gateway lifecycle yourself.
- Routed mode means `harness → LMM gateway → Context MCP when available → Glyph Encoding when useful → GlyphOS AI Compute → local llama.cpp backend`. Sync output reports `routed-full-capable` when the combined feature is configured. Use `--mode direct` when you want to bypass the gateway and call the backend `8081/v1` endpoint directly.
- `llama-model sync-opencode --preset long-run` writes model-aware `compaction.reserved` headroom. For 128k-token local contexts it reserves 64000 tokens, which avoids the observed long-session stall pattern where opencode aborts a pending tool after a parent message timeout.
- `llama-model sync-openclaw` updates `~/.openclaw/openclaw.json` so OpenClaw points at the routed LMM gateway by default.
- `llama-model sync-claude` writes `~/.claude/settings.json` for Claude Code.
- Post-switch sync for Claude Code, OpenClaw, GlyphOS, and oh-my-openagent is opt-in with `LLAMA_MODEL_SYNC_CLAUDE=1`, `LLAMA_MODEL_SYNC_OPENCLAW=1`, `LLAMA_MODEL_SYNC_GLYPHOS=1`, and `LLAMA_MODEL_SYNC_OH_MY_OPENAGENT=1` (default).
- Post-switch sync is non-fatal; a client-config error warns but does not roll back a successfully started local model.

---

## 🧩 Context Mode MCP

The optional Context Mode MCP package lives under `integrations/context-mode-mcp/`. It is intended for local development workflows that need indexed context, compact retrieval, lifecycle diagnostics, and MCP tool execution helpers.

Gateway requests use the bundled `scripts/context_mcp_bridge.py` by default when the Context Mode MCP package and built `dist/index.js` are present. If Context MCP is unavailable, times out, or returns no context, the gateway continues in `routed-basic` mode and records the degraded stage in telemetry.

Glyph Encoding runs after context retrieval and before GlyphOS routing. It only compresses structured or repeated retrieved context, never the latest user instruction. If encoding is not smaller or fails, the gateway falls back to raw retrieved context and records the reason.

### Common commands

```bash
cd integrations/context-mode-mcp
npm ci --omit=optional --ignore-scripts --no-audit --fund=false
npm run typecheck
npm run build
npm run lifecycle-matrix
```

**Supply-chain policy:**

- All `npm ci` invocations use `--ignore-scripts` (blocks arbitrary postinstall hooks) and `--no-audit --fund=false` (skips network telemetry).
- `--omit=optional` is correct for the Context MCP bundle (no optional platform-deps needed).
- 🚫 **Do not use `--omit=optional` for Next.js, Vite, or other frontend builds** — those require optional platform-native packages like `@next/swc-*` binaries. Use `npm ci --ignore-scripts --no-audit --fund=false` instead.

**Safety notes:**

- `ctx_execute` and `ctx_execute_file` run in temporary working directories with allowlist and denylist policy checks.
- These helpers are not described as OS-level sandboxes; use container or VM isolation if you need a security boundary.
- Large outputs are indexed automatically when configured, so MCP responses stay compact.

### Context + GlyphOS readiness

The dashboard has a `Context + GlyphOS` preference in global defaults. The toggle activates a combined readiness and workflow view for:

- ✅ Active local model selected by Llama Model Manager
- ✅ GlyphOS config present at `~/.glyphos/config.yaml`
- ✅ Context Mode MCP package present in `integrations/context-mode-mcp/`
- ✅ Lifecycle and typecheck commands available for local validation

This toggle is operator-facing. It does not create a new network service or claim extra sandboxing; it makes the bundled combined workflow clear when Context Mode MCP retrieval and GlyphOS routing are used together.

The Integrations panel also includes an **Activate feature** button for this card. That one click persists `LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE=1`, enables GlyphOS auto-sync, runs `llama-model sync-glyphos`, and refreshes the readiness card.

---

## 📋 Dependencies

| Dependency | Required? | Notes |
|:-----------|:---------:|:------|
| `python3` | ✅ Yes | Required for the web dashboard |
| `zenity` | ⚠️ Optional | Only needed for the legacy fallback UI |
| `git`, `cmake`, C++ compiler | ⚠️ Optional | Required if you want to build `llama.cpp` locally |
| CUDA toolkit | ⚠️ Optional | Only for CUDA builds |
| Vulkan SDK | ⚠️ Optional | Only for Vulkan builds |
| Xcode CLT | ⚠️ Optional | Only for Metal builds (macOS) |

**Runtime knobs:**

- `LLAMA_SERVER_PARALLEL=1` — recommended for a single coding harness (avoids parallel slot pressure)
- `LLAMA_MODEL_AUTO_FIT=1` — default guarded GPU/RAM-aware startup mitigation; use `--no-auto-fit` for strict launch
- `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` — experimental CUDA-only escape hatch for oversized context/KV-cache
- `LLAMA_MODEL_UI=zenity` — force the old Zenity UI instead of the browser dashboard
- `LLAMA_MODEL_SYNC_OH_MY_OPENAGENT=1` (default) — keeps oh-my-openagent config aligned after each model switch

---

## 📦 Bundled local packages

The public GlyphOS AI Compute package is vendored locally under `integrations/public-glyphos-ai-compute/`. This bundled copy contains only the public glyph and AI routing layers. The private Q45 and quantum stack is intentionally not included here.

The Learning Loop is bundled under `integrations/learning-loop/` with AGENTS.md, lessons.md, persistence.py, novelty.py, and a cloud glyph injection protocol spec.

## Gateway foundation modules

The gateway Python surfaces share small stdlib-only foundation modules under `scripts/`:

- `lmm_config.py` — loads and validates gateway and context environment settings with dataclasses instead of ad-hoc parsing
- `lmm_errors.py` — provides machine-readable error payloads for configuration, gateway, provider, routing, and storage failures
- `lmm_storage.py` — owns gateway telemetry persistence behind a storage adapter so handlers do not mutate state files directly

These modules are intentionally dependency-free and can coexist with the existing `defaults.env` shell configuration.

---

## ✅ Maintainer verification

Before pushing a release branch, run the focused checks that cover the web dashboard, GlyphOS routing, and Context Mode MCP surfaces:

```bash
python -m unittest tests.test_phase0_contracts
python -m unittest integrations.public-glyphos-ai-compute.tests.test_q2_flow
cd integrations/context-mode-mcp && npm run typecheck && npm run build
```

**Expected notes:**

- The web contract suite includes cancellation-path coverage and may exercise connection-reset behavior while still passing.
- `npm run build` may warn about dashboard chunk size; that is a bundle-size hygiene item, not a functional failure.
- `npm run lifecycle-matrix` is the manual MCP lifecycle smoke test for `ctx_doctor`, `ctx_execute`, `ctx_upgrade`, `ctx_purge`, `ctx_index`, and `ctx_search`.

---

## 🗺️ Roadmap

Planned follow-up is tracked in [docs/ROADMAP.md](docs/ROADMAP.md), including long-run session handoff: persistent run state, completion summaries, artifacts, and optional local notifications for extended agent sessions.

---

## 📄 License

- Copyright 2026 soulhash.ai
- Licensed under Apache-2.0
- The code is free to use under the license terms while soulhash.ai remains the copyright owner

## ™️ Trademark notice

- **Soul Hash®** is a registered trademark of soulhash.ai
- **GlyphOS™** is a trademark of soulhash.ai
- The Apache-2.0 license does not grant trademark rights

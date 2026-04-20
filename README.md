LLM Model Manager

by soulhash.ai

Portable v2.0 handoff bundle for inclusion in another repo or machine.

Screenshots:

![Dashboard overview](docs/screenshots/dashboard-overview.png)
![Serve feedback](docs/screenshots/dashboard-serve-feedback.png)
![Empty-state preview](docs/screenshots/dashboard-empty-state.png)

Contents:
- `bin/llama-model`: CLI wrapper for registry management, switching, restart/stop, discovery, and diagnostics
- `bin/llama-model-web`: browser dashboard launcher
- `bin/llama-model-gui`: launcher that prefers the web dashboard and falls back to Zenity
- `config/defaults.env.example`: runtime defaults template
- `config/models.tsv.example`: model registry template
- `config/HELP.txt`: end-user help text
- `desktop/llama-model-manager.desktop`: desktop launcher
- `scripts/build-llama-server.sh`: wrapper for fetching and compiling a host-specific llama.cpp runtime
- `web/`: browser dashboard assets and Python server
- `LICENSE`: Apache License 2.0
- `NOTICE`: copyright and attribution notice
- `docs/ORION-INTEGRATION.md`: inclusion notes for Agent Orion
- `install.sh`: optional local installer for user-space deployment

Quick install:
```bash
./install.sh
```

What `install.sh` does:
- installs the CLI, web UI, desktop launcher, help text, and example config files
- copies bundled runtime assets if this repo already contains them
- in an interactive terminal, offers to check/install missing build dependencies and compile a local runtime
- does **not** silently compile `llama.cpp`; it only launches the runtime build flow if the user agrees
- does **not** silently install OS packages or GPU SDKs/toolkits for you

After install:
```bash
llama-model-web
llama-model list
llama-model doctor
llama-model build-runtime --backend auto
```

Runtime portability:
- llama.cpp source is portable, but built `llama-server` binaries are backend-, platform-, and architecture-specific
- this repo does not assume one bundled GPU binary works everywhere
- `llama-model doctor` reports host backends, selected binary source, and compatibility status
- if no safe runtime is available, run `llama-model build-runtime --backend auto` or `./scripts/build-llama-server.sh --backend auto`

What `llama-model build-runtime` does:
- clones or updates `https://github.com/ggml-org/llama.cpp.git`
- checks out the configured `llama.cpp` ref
- builds a host-specific `llama-server` runtime for the selected backend
- also builds a CPU fallback runtime
- writes compatibility metadata so the manager can reject mismatched bundled binaries later

What `llama-model build-runtime` does **not** do:
- it does **not** silently run `apt`, `dnf`, `pacman`, `brew`, or any other package manager without asking first
- it does **not** install unsupported toolchains or SDK paths by guesswork
- it does **not** try to guess a safe third-party GPU binary from another machine

Interactive dependency assistance:
- when `llama-model build-runtime` sees missing build tools in an interactive terminal, it now:
  - tells the user exactly what is missing
  - shows the install commands it plans to run
  - asks for confirmation first
  - runs the detected system package manager when it knows a sane command for that host
- this currently covers common package-manager flows such as `apt-get`, `dnf`, `pacman`, `zypper`, and `brew`, plus `xcode-select --install` for macOS command line tools
- if the host package manager or SDK path is unsupported, the script stops and tells the user what still needs to be installed manually

So the hand-holding behavior is:
- if the required build tools are already installed, the script will fetch `llama.cpp` and compile a local runtime for the user
- if required tools are missing and the host package manager is supported, the script can prompt the user, install them with the user’s confirmation, and then continue
- if required tools are missing and the script does not know a safe install path, it stops with a clear error telling the user what is missing
- it is intentionally explicit rather than silently mutating the system

Recommended first-run flow from a fresh GitHub checkout:
```bash
./install.sh
llama-model doctor
llama-model build-runtime --backend auto
llama-model doctor
llama-model-web
```

If `doctor` reports `binary_status: unavailable`, the next step is to install the missing build dependencies for that machine and run `llama-model build-runtime --backend auto` again.

Key v2.0 features:
- browser dashboard for switching models, importing discovered GGUFs, editing presets, and checking runtime health
- structured registry entries with per-model overrides for context, `ngl`, batch, threads, parallel, device, and notes
- automatic discovery of `.gguf` models plus same-directory `mmproj` sidecars
- CLI diagnostics via `llama-model doctor`
- manifest-driven runtime selection that only accepts validated bundled binaries
- local `llama.cpp` bootstrap via `llama-model build-runtime`
- OpenAI-compatible endpoint summary for local harnesses such as `opencode`
- Modern Operator dashboard treatment with toasts, busy states, and first-run empty states
- built-in sanitized `--demo` mode for public screenshots and demo captures

Public demo assets:
- screenshots live under `docs/screenshots/`
- a short product demo GIF lives at `docs/demo/llama-model-manager-demo.gif`
- branding assets live under `docs/branding/`
- the browser favicon source lives at `web/branding/favicon.svg`
- generate assets from sanitized data with:

```bash
python3 scripts/render_public_assets.py
```

This uses the built-in demo mode and writes:
- overview, serve-feedback, scan-feedback, and empty-state screenshots
- a small public demo GIF
- a social preview card at `docs/branding/llama-model-manager-social-card.png`

Dependencies:
- `python3` is required for the web dashboard
- `zenity` is optional and only needed for the legacy fallback UI
- `git`, `cmake`, and a C++ compiler are required if you want the repo to fetch and build `llama.cpp` locally
- CUDA builds need the CUDA toolkit, Vulkan builds need Vulkan SDK/shader tools, and Metal builds need Xcode command line tools
- the runtime build script fetches `llama.cpp` source automatically, but system dependencies must already be present
- the scripts use XDG-style config/state locations under `~/.config/llama-server` and `~/.local/state/llama-server`
- `LLAMA_SERVER_PARALLEL=1` is recommended for a single coding harness because it avoids parallel slot pressure without reducing context length
- set `LLAMA_MODEL_UI=zenity` if you want to force the old Zenity UI instead of the browser dashboard

Common commands:
```bash
llama-model list
llama-model show gemma4-e4b-q8
llama-model add gemma4-e4b-q8 /absolute/path/to/Gemma-4-E4B-Q8_K_P.gguf --mmproj /absolute/path/to/mmproj-Gemma-4-E4B-f16.gguf
llama-model discover ~/models
llama-model build-runtime --backend auto
llama-model switch qwen35-9b-q8
llama-model doctor
```

License:
- Copyright `2026 soulhash.ai`
- Licensed under `Apache-2.0`
- The code is free to use under the license terms while `soulhash.ai` remains the copyright owner

Release notes:
- see `docs/RELEASE-NOTES-v2.md`

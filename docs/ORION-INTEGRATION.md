Orion Integration Notes

Recommended repo layout:
- `tools/llama-model-manager/bin/llama-model`
- `tools/llama-model-manager/bin/llama-model-web`
- `tools/llama-model-manager/bin/llama-model-gui`
- `tools/llama-model-manager/config/defaults.env.example`
- `tools/llama-model-manager/config/models.tsv.example`
- `tools/llama-model-manager/config/HELP.txt`
- `tools/llama-model-manager/desktop/llama-model-manager.desktop`
- `tools/llama-model-manager/web/`
- `tools/llama-model-manager/install.sh`

Recommended inclusion approach:
1. Keep the scripts user-space and XDG-based rather than hardwiring repo-local state.
2. Ship the `*.example` config files and copy them into `~/.config/llama-server/` on first run or via installer.
3. Keep the desktop entry `Exec=llama-model-gui`; v2 dispatches to the browser dashboard by default.
4. Preserve `LLAMA_SERVER_PARALLEL=1` as the safe default for single-harness use on older GPUs.
5. If LocalBrain already has a launcher framework, call `llama-model-gui` or `llama-model-web` from that instead of duplicating UI code.

Assumptions:
- `llama-server` can come from a validated bundled runtime, a locally built runtime, or an external install.
- `python3` is available for the dashboard.
- `zenity` is optional and only needed for the fallback UI.
- the host uses Linux desktop conventions for `.desktop` launchers.

Suggested portability posture:
- keep `LLAMA_SERVER_BIN` blank by default so the selector can choose a validated runtime
- expose `llama-model build-runtime --backend auto` during first-run or setup flows
- avoid shipping one prebuilt CUDA binary as if it were universal

Optional extensions for LocalBrain:
- add an icon
- add a first-run wizard for model discovery/import
- surface server health and current alias inside a larger LocalBrain status panel

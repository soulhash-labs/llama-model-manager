LLM Model Manager v2 Release Notes

One-line summary:
- a browser-first control surface for local `llama.cpp` that is easier to operate, easier to package, and easier to present publicly

Highlights:
- moved the manager to a browser-first dashboard while keeping the CLI and Zenity fallback
- hardened runtime portability so bundled binaries are explicitly validated against the host before use
- added `llama-model build-runtime` so repo users can fetch and compile llama.cpp locally for their own backend
- added a stronger Modern Operator visual treatment for the dashboard
- added inline help for novice users, including hover guidance and a touch-friendly operator notes panel
- added inline busy states for important actions such as `Serve`, `Save`, `Scan`, `Restart`, and mode switching
- replaced blocking alerts with lightweight toast feedback for success, info, and error states
- added authored empty states for empty registry and empty discovery scans
- added sanitized `--demo` mode for screenshots, GIFs, and public documentation assets

Operational improvements:
- per-model overrides remain supported for context, GPU offload, batch, threads, parallel, device, and notes
- model discovery still auto-detects matching `mmproj` sidecars
- the dashboard still exposes an OpenAI-compatible local endpoint summary for tools such as `opencode`

Packaging:
- public screenshots now live under `docs/screenshots/`
- a short demo GIF now lives under `docs/demo/`
- a GitHub/social preview card now lives under `docs/branding/`
- publishing notes now include the screenshot/demo workflow
- `docs/GITHUB-LAUNCH.md` now includes copy-ready blurbs, release text, and announcement text

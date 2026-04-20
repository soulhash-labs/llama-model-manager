GitHub Publishing Notes

This subtree is designed to live at:
- `tools/llama-model-manager/`

Suggested commit contents:
- `tools/llama-model-manager/LICENSE`
- `tools/llama-model-manager/NOTICE`
- `tools/llama-model-manager/bin/`
- `tools/llama-model-manager/config/`
- `tools/llama-model-manager/desktop/`
- `tools/llama-model-manager/docs/`
- `tools/llama-model-manager/scripts/`
- `tools/llama-model-manager/web/`
- `tools/llama-model-manager/install.sh`
- `tools/llama-model-manager/README.md`

Suggested README positioning:
- keep the existing subtree `README.md` as the main user-facing document
- if publishing as part of a larger repo, link to it from the repo root
- use `docs/GITHUB-LAUNCH.md` for short blurbs, release copy, and announcement text

Suggested polish before public release:
1. Add an icon if the target project has one.
2. Mention `zenity` as a GUI dependency in the parent repo docs.
3. Decide whether the installer should remain user-space or be adapted to the parent project's packaging/install flow.
4. Be explicit that bundled llama.cpp binaries are backend-/platform-specific. Keep `llama-model build-runtime --backend auto` in setup docs so users can compile locally for CUDA, Vulkan, Metal, or CPU.
5. Use the built-in demo mode for public assets:
   - `python3 scripts/render_public_assets.py`
   - the script serves sanitized demo data and generates overview, serve-feedback, scan-feedback, empty-state, and social-card assets automatically
   - store assets under `docs/screenshots/`, `docs/demo/`, and `docs/branding/`
   - use `docs/branding/llama-model-manager-social-card.png` as the GitHub social preview upload
   - use `docs/branding/` for the app icon and app-mark in repo docs or release graphics
6. Keep the Apache-2.0 `LICENSE` and `NOTICE` files with the subtree if it is copied elsewhere.

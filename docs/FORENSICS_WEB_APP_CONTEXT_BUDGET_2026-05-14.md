# Forensics: web/app.py Context-Budget Regression Check

**Date**: 2026-05-14
**Trigger**: Suspicion that previously applied context-budget guards were missing from `web/app.py`.

---

## Finding

**No regression was found in `web/app.py`.**

The following strings were searched in the current file, in git history (`git log -S`), and in the runtime copy at `~/.local/share/llama-model-manager/web/app.py`:

| String | In current file? | In git history? | Verdict |
|--------|-----------------|-----------------|---------|
| `relative_to` | ✅ Yes (line 2425) | Yes (commit 7e6f84a) | Present, never removed |
| `ALLOWED_HOST` / `parse_allowed_hosts` | ✅ Yes (lines 122, 3478+) | Yes (commit b1e2f96) | Present, never removed |
| `_is_allowed_client` | ✅ Yes | Yes | Present, never removed |
| `LMM_MAX_CONTEXT_TOKENS` | ❌ No | 0 commits ever | Never belonged here (see ownership below) |
| `LMM_CONTEXT_SAFETY_MARGIN` | ❌ No | 0 commits ever | Never belonged here |
| `LMM_CONTEXT_OVERFLOW_MODE` | ❌ No | 0 commits ever | Never belonged here |
| `LMM_AGENT_SOFT_CONTEXT_LIMIT` | ❌ No | 0 commits ever | Never belonged here |
| `bool_fields` | ❌ No | 0 commits ever | Never existed in this repo |
| `context_budget` (any form) | ❌ No | 0 commits ever | Never belonged here |

---

## Source of Truth

Repo copy and runtime copy are **identical** (verified via `diff`). No source-of-truth split.

---

## Actual Ownership by Layer

| Layer | File | Responsibility |
|-------|------|----------------|
| Config | `scripts/lmm_config.py` | `ContextBudgetConfig` dataclass + env var validation |
| Gateway enforcement | `scripts/gateway/handlers_openai.py` | `_check_context_budget()` rejects oversized prompts |
| Launcher propagation | `bin/llama-model` | `active_context_window()`, env var pass-through, `extra_args` validation |
| Zenity GUI | `bin/llama-model-gui` | Status display, 4-column TSV context field |
| Dashboard frontend | `web/app.js` | Read/write budget fields, client-side `containsContextFlag()` |
| Dashboard backend | `web/app.py` | API routes, static serving, model/defaults persistence, download orchestration |

---

## Root Cause of False Alarm

Review-scope confusion: the context-budget variables were assumed to live in `web/app.py` because they were recently added to the dashboard UI (`web/app.js`). In the current architecture, `web/app.py` is the backend that serves the static dashboard and proxies API calls — it does not own context-budget configuration, which is managed at the config dataclass (Python) and frontend (JS) layers.

---

## Preventative Measures Added

1. `tests/test_integrity_guards.py` — static guard tests that trip if critical strings are removed from their intended files
2. `AGENTS.md` — No-Clobber / Source-of-Truth Rules section documenting layer ownership
3. `CLAUDE.md` — Same rules, since it references AGENTS.md
4. This forensic note — so future reviewers find the investigation result immediately

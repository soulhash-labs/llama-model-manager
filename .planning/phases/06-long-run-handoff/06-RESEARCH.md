# Phase 06: Long-Run Session Handoff - Research

**Researched:** 2026-04-30
**Domain:** Long-running session handoff, run record management, dashboard history
**Confidence:** HIGH

## Summary

Phase 06 ("Long-Run Session Handoff") focuses on improving visibility and continuity for local long-running AI sessions managed through LMM. The core problem is that users running extended local sessions (via Claude Code, OpenClaw, GlyphOS, etc.) need to know what finished, what changed, and what needs review when they return to the dashboard.

The existing infrastructure provides a solid foundation:
- **RunRecord dataclass** (`lmm_types.py`) tracks run status with fields like `status`, `exit_result`, `duration_ms`, `model`, `provider`
- **JsonRunRecordStore** (`lmm_storage.py`) provides bounded JSON storage with fcntl locking
- **Gateway recording** (`glyphos_openai_gateway.py`) already creates RunRecords on every request and fires notifications for runs > 30s
- **Notification system** (`lmm_notifications.py`) supports desktop (notify-send/osascript) and log backends with cooldown
- **Dashboard state API** (`web/app.py`) exposes `run_history` with `records`, `total`, `by_status`, and `latest_completed`

**Primary recommendation:** Extend the existing RunRecord model with handoff-specific fields, build a `lmm_handoff.py` module for generating session summaries, add CLI commands for quick status checks, and enhance the dashboard with a dedicated "Session History" panel showing long-running session handoffs.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (json, dataclasses, fcntl, threading) | 3.12+ | All backend logic | Project constraint: no external deps |
| ThreadingHTTPServer | stdlib | Gateway + Dashboard HTTP | Already in use (glyphos_openai_gateway.py, web/app.py) |
| notify-send / osascript | system | Desktop notifications | Already used in lmm_notifications.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| argparse | stdlib | CLI command parsing | Adding `llama-model handoff` subcommands |
| urllib (request, error) | stdlib | HTTP client for API calls | Dashboard-to-gateway communication |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ThreadingHTTPServer | asyncio/aiohttp | Would require architectural shift; project uses sync |
| notify-send | Webhook/Slack notifications | Nice-to-have but Phase 06 should keep local-first |

**Installation:**
```bash
# No new dependencies - all stdlib
# Ensure system notification support:
# Debian/Ubuntu: sudo apt-get install libnotify-bin
# macOS: built-in osascript
```

## Architecture Patterns

### Recommended Project Structure
```
scripts/
├── lmm_types.py          # Existing: RunRecord, RunStatus, ExitResult
├── lmm_storage.py       # Existing: JsonRunRecordStore
├── lmm_notifications.py # Existing: NotificationManager
├── lmm_health.py       # Existing: HealthChecker
├── glyphos_openai_gateway.py  # Existing: gateway with run recording
├── lmm_handoff.py      # NEW: Handoff summary generation
└── lmm_session.py      # NEW (optional): Session tracking

web/
├── app.py               # Existing: Dashboard (extend /api/state, add /api/handoff)
├── app.js               # Existing: Frontend (add session history UI)
└── index.html          # Existing: HTML (add handoff panel)

bin/
└── llama-model         # Existing: CLI (add handoff subcommands)
```

### Pattern 1: Handoff Summary Generation
**What:** Generate a human-readable summary of a completed long-running session
**When to use:** After a run with duration > threshold completes (default 30s, matching notification logic)
**Example:**
```python
# Source: New lmm_handoff.py module (to be created)
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class HandoffSummary:
    session_id: str
    run_id: str
    status: str  # "completed", "failed", "cancelled"
    model: str
    provider: str
    duration_human: str
    completed_at: str
    exit_result: str
    prompt_preview: str  # First 200 chars
    artifacts: list[str]  # Paths to output files
    upstream_session_ref: str  # e.g., "claude-code-session-123"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_run_record(cls, record: dict[str, Any]) -> "HandoffSummary":
        """Build handoff summary from a completed RunRecord."""
        import humanize  # Would need this or implement manually
        duration_ms = record.get("duration_ms") or 0
        duration_human = _format_duration(duration_ms)

        prompt = record.get("prompt", "")
        prompt_preview = (prompt[:200] + "...") if len(prompt) > 200 else prompt

        return cls(
            session_id=record.get("session_id", ""),
            run_id=record.get("id", ""),
            status=record.get("status", "unknown"),
            model=record.get("model", ""),
            provider=record.get("provider", ""),
            duration_human=duration_human,
            completed_at=record.get("completed_at", ""),
            exit_result=record.get("exit_result") or "unknown",
            prompt_preview=prompt_preview,
            artifacts=_extract_artifacts(record),
            upstream_session_ref=record.get("upstream_session_ref", ""),
        )

def _format_duration(ms: int) -> str:
    """Convert milliseconds to human-readable duration."""
    if ms <= 0:
        return "0s"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"

def _extract_artifacts(record: dict[str, Any]) -> list[str]:
    """Extract artifact paths from run record metadata."""
    artifacts = []
    # Check common artifact locations
    metadata = record.get("metadata", {})
    if isinstance(metadata, dict):
        artifacts.extend(metadata.get("output_files", []))
        artifacts.extend(metadata.get("artifact_paths", []))
    return artifacts
```

### Pattern 2: CLI Status Surface
**What:** Quick CLI command to check latest completed run without opening dashboard
**When to use:** User returns to terminal after a long session and wants immediate status
**Example:**
```python
# Source: New subcommand in bin/llama-model (extend existing argparse)

def cmd_handoff_status(args: argparse.Namespace) -> None:
    """Check the latest completed run handoff status."""
    store = JsonRunRecordStore()
    latest = store.latest_completed()

    if not latest:
        print("No completed runs found.")
        return

    summary = HandoffSummary.from_run_record(latest)
    print(f"Latest Run: {summary.run_id}")
    print(f"Status: {summary.status}")
    print(f"Model: {summary.model} (via {summary.provider})")
    print(f"Duration: {summary.duration_human}")
    print(f"Completed: {summary.completed_at}")
    print(f"Exit Result: {summary.exit_result}")
    print(f"Prompt: {summary.prompt_preview}")

    if summary.artifacts:
        print(f"\nArtifacts ({len(summary.artifacts)}):")
        for artifact in summary.artifacts:
            print(f"  - {artifact}")

    if summary.upstream_session_ref:
        print(f"\nUpstream Session: {summary.upstream_session_ref}")

# Add to argparse:
# handoff_parser = sub.add_parser("handoff", help="Session handoff commands")
# handoff_sub = handoff_parser.add_subparsers(dest="handoff_cmd")
# status_parser = handoff_sub.add_parser("status", help="Check latest run status")
# status_parser.set_defaults(func=cmd_handoff_status)
```

### Pattern 3: Dashboard Session History Panel
**What:** New collapsible panel in dashboard showing recent long-running session handoffs
**When to use:** User opens dashboard after extended time away
**Example:**
```javascript
// Source: Add to web/app.js

function renderSessionHandoffs(runHistory) {
  const container = $("#session-handoffs-panel");
  if (!container) return;

  const records = (runHistory?.records || [])
    .filter(r => r.duration_ms > 30000)  // Only long runs
    .slice(0, 10);  // Show last 10

  if (!records.length) {
    container.innerHTML = `<div class="empty-state">
      <strong>No long-running sessions yet</strong>
      <span>Sessions with >30s duration will appear here</span>
    </div>`;
    return;
  }

  const html = records.map(record => `
    <article class="handoff-card ${record.status}">
      <div class="handoff-header">
        <span class="handoff-model">${escapeHtml(record.model || "-")}</span>
        <span class="handoff-status ${record.status}">${record.status}</span>
      </div>
      <div class="handoff-meta">
        <span>${formatRelativeTime(record.completed_at)}</span>
        <span>${record.duration_ms ? Math.round(record.duration_ms / 1000) + "s" : "-"}</span>
        <span>${record.provider || "-"}</span>
      </div>
      <div class="handoff-prompt">${escapeHtml((record.prompt || "").slice(0, 100))}</div>
      ${record.error_message ? `<div class="handoff-error">${escapeHtml(record.error_message)}</div>` : ""}
    </article>
  `).join("");

  container.innerHTML = html;
}

// Call from renderStatus() or similar:
// renderSessionHandoffs(state.data?.run_history);
```

### Anti-Patterns to Avoid
- **Don't create a new storage mechanism** — Extend JsonRunRecordStore with new query methods
- **Don't build custom notification system** — Extend NotificationManager with new NotificationType (HANDOFF_READY)
- **Don't replace existing RunRecord** — Add optional fields with backward compatibility
- **Don't make handoff mandatory** — Keep it opt-in / advisory for long runs only

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|----------|-------------|---------------|-----|
| Duration formatting | Custom time formatting logic | Simple helper in lmm_handoff.py | Edge cases in human-readable time are tricky |
| CLI table output | Custom ASCII table renderer | Plain text with aligned columns | Keep it simple; rich formatting not needed |
| Semantic version comparison | Custom parser | N/A - not needed for this phase | |

**Key insight:** The existing infrastructure (RunRecord, JsonRunRecordStore, NotificationManager) covers 80% of what's needed. Handoff is primarily about **presentation layer** — better summaries, easier access, and clearer history.

## Common Pitfalls

### Pitfall 1: Session Identity Crisis
**What goes wrong:** Runs from different upstream tools (Claude Code, OpenClaw, GlyphOS) can't be distinguished in run records
**Why it happens:** RunRecord doesn't track which upstream session initiated the run
**How to avoid:** Add optional `upstream_session_ref` field to RunRecord; populate from gateway metadata
**Warning signs:** All runs show "provider: llamacpp" with no way to trace back to the originating tool

### Pitfall 2: Notification Fatigue
**What goes wrong:** Users get spammed with handoff notifications for short runs
**Why it happens:** Reusing the existing 30s threshold without additional filtering
**How to avoid:** Only generate handoff summaries for runs > 60s (or configurable threshold); batch notifications
**Warning signs:** User disables notifications entirely due to too many alerts

### Pitfall 3: Storage Bloat from Long Prompts
**What goes wrong:** RunRecord store grows unbounded due to long prompts being stored
**Why it happens:** lmm_types.py already truncates to 4000 chars, but handoff summaries add more text
**How to avoid:** Reuse existing truncation logic; store prompt preview separately from full prompt
**Warning signs:** lmm-run-records.json grows beyond expected size

### Pitfall 4: Dashboard State Bloat
**What goes wrong:** Returning all 50 run records to dashboard on every /api/state call
**Why it happens:** _load_run_history() returns full records list
**How to avoid:** Add summary mode to run_history that returns condensed view for handoff panel
**Warning signs:** Slow dashboard load times; large JSON responses in DevTools

## Code Examples

Verified patterns from existing codebase:

### Extending RunRecord with Handoff Fields
```python
# Source: lmm_types.py (extend existing RunRecord)
# Proposed new fields (all optional for backward compatibility):

@dataclass
class RunRecord:
    # ... existing fields ...

    # NEW: Handoff-specific fields
    session_id: str = ""              # Links related runs (e.g., multi-turn session)
    upstream_session_ref: str = ""    # Reference to upstream tool session
    handoff_summary: str = ""        # Pre-generated human summary
    artifacts: list[str] = field(default_factory=list)  # Output file paths
    tags: list[str] = field(default_factory=list)        # User/lane tags

    def __post_init__(self) -> None:
        # ... existing logic ...
        if not self.session_id:
            self.session_id = self.id  # Default: single-run session

    def to_dict(self) -> dict[str, Any]:
        base = {
            # ... existing fields ...
        }
        # Add new fields if present
        if self.session_id != self.id:
            base["session_id"] = self.session_id
        if self.upstream_session_ref:
            base["upstream_session_ref"] = self.upstream_session_ref
        if self.handoff_summary:
            base["handoff_summary"] = self.handoff_summary
        if self.artifacts:
            base["artifacts"] = self.artifacts
        if self.tags:
            base["tags"] = self.tags
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunRecord:
        # ... existing logic ...
        return cls(
            # ... existing fields ...
            session_id=str(data.get("session_id", "")),
            upstream_session_ref=str(data.get("upstream_session_ref", "")),
            handoff_summary=str(data.get("handoff_summary", "")),
            artifacts=list(data.get("artifacts", [])),
            tags=list(data.get("tags", [])),
        )
```

### Adding Handoff API Endpoint
```python
# Source: web/app.py (extend existing API_POST_PAYLOAD_SCHEMAS and do_POST)

# Add to API_POST_PAYLOAD_SCHEMAS:
"/api/handoff/summary": {
    "allowed": {"run_id", "limit"},
    "int_fields": {"limit"},
},

# Add handler method or lambda:
def get_handoff_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Generate handoff summary for a specific run or latest completed."""
    from lmm_handoff import HandoffSummary, JsonHandoffStore

    run_id = str(payload.get("run_id", "")).strip()
    store = JsonHandoffStore()  # Reuses JsonRunRecordStore path

    if run_id:
        record = store.get_record(run_id)
    else:
        record = store.latest_completed()

    if not record:
        return {"ok": False, "error": "No matching run found", "code": "not_found"}

    summary = HandoffSummary.from_run_record(record)
    return {"ok": True, "summary": summary.to_dict()}
```

### Gateway Integration for Session Tracking
```python
# Source: glyphos_openai_gateway.py (extend existing record_gateway_request logic)

def _extract_session_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract session references from incoming gateway payload."""
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        return {}

    return {
        "upstream_session_ref": str(metadata.get("session_id") or metadata.get("conversation_id") or ""),
        "tags": list(metadata.get("tags", [])),
    }

# In do_POST, after run_record creation:
        record = _run_record_from_dict(record)

        # NEW: Add session tracking
        session_meta = _extract_session_metadata(payload)
        if session_meta.get("upstream_session_ref"):
            record.upstream_session_ref = session_meta["upstream_session_ref"]
        if session_meta.get("tags"):
            record.tags = session_meta["tags"]

        # Generate handoff summary for long runs
        if record.duration_ms and record.duration_ms > 60000:  # > 1 minute
            from lmm_handoff import HandoffSummary
            summary = HandoffSummary.from_run_record(record.to_dict())
            record.handoff_summary = summary.to_dict()  # Or summary.format_text()

        safe_record_run_record(record)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No run tracking | RunRecord + JsonRunRecordStore | Phase 02 (run-records) | Basic run history available |
| No notifications | NotificationManager + gateway integration | Phase 03 (receipts-notifications) | Desktop alerts for long runs |
| Single run view | Handoff summary (Phase 06) | Phase 06 | Session-level continuity |

**Deprecated/outdated:**
- **Direct manipulation of lmm-run-records.json:** Always use JsonRunRecordStore API
- **Storing full prompts in summaries:** Use prompt_preview (200 chars) instead

## Open Questions

1. **Should handoff summaries be pre-generated or on-demand?**
   - What we know: Gateway already has run recording; notifications fire at 30s
   - What's unclear: Should we generate summary when run completes, or when user requests it?
   - Recommendation: Pre-generate for runs > 60s (store in handoff_summary field); on-demand as fallback

2. **How should artifacts be detected?**
   - What we know: Upstream tools may write output files; paths might be in metadata
   - What's unclear: Standard location for artifact references? Should we scan common directories?
   - Recommendation: Start with metadata extraction; add filesystem scanning in Phase 06 follow-up

3. **CLI output format for handoff status?**
   - What we know: `llama-model` uses plain text output (see bin/llama-model)
   - What's unclear: Should we support --json flag for machine parsing?
   - Recommendation: Plain text for MVP; add --json in Phase 06 follow-up if needed

4. **Webhook notifications for handoff?**
   - What we know: Phase 06 scope mentions "webhook or local notification hooks"
   - What's unclear: Is this in-scope for Phase 06 or follow-up?
   - Recommendation: Phase 06 MVP = desktop + log notifications only; webhooks are Phase 06 follow-up

## Validation Architecture

> Workflow.nyquist_validation is not explicitly set to false in .planning/config.json, so validation architecture is included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | unittest (stdlib) |
| Config file | None — tests in tests/test_phase0_contracts.py pattern |
| Quick run command | `python3 -m pytest tests/test_phase6_handoff.py -x` |
| Full suite command | `python3 -m pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| (TBD) HANDOFF-01 | RunRecord extensible with handoff fields | unit | `python3 -m pytest tests/test_phase6_handoff.py::TestRunRecordHandoffFields -x` | ❌ Phase 06 |
| (TBD) HANDOFF-02 | HandoffSummary generation from RunRecord | unit | `python3 -m pytest tests/test_phase6_handoff.py::TestHandoffSummary -x` | ❌ Phase 06 |
| (TBD) HANDOFF-03 | CLI status command works | integration | `llama-model handoff status` | ❌ Phase 06 |
| (TBD) HANDOFF-04 | Dashboard handoff panel renders | manual (browser) | N/A | ❌ Phase 06 |
| (TBD) HANDOFF-05 | Gateway records session metadata | unit | `python3 -m pytest tests/test_phase6_handoff.py::TestGatewaySessionTracking -x` | ❌ Phase 06 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest tests/test_phase6_handoff.py::<TestClass> -x`
- **Per wave merge:** `python3 -m pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_phase6_handoff.py` — covers HANDOFF-01, HANDOFF-02, HANDOFF-05
- [ ] `scripts/lmm_handoff.py` — HandoffSummary class + generation logic
- [ ] `scripts/lmm_types.py` — Extend RunRecord with handoff fields
- [ ] `web/app.py` — Add /api/handoff/* endpoints
- [ ] `web/app.js` — Add renderSessionHandoffs() function
- [ ] `web/index.html` — Add session-handoffs-panel

*(If no gaps: "None — existing test infrastructure covers all phase requirements")*

## Sources

### Primary (HIGH confidence)
- `/opt/llama-model-manager-v2.1.0/scripts/lmm_types.py` - RunRecord dataclass definition
- `/opt/llama-model-manager-v2.1.0/scripts/lmm_storage.py` - JsonRunRecordStore implementation
- `/opt/llama-model-manager-v2.1.0/scripts/lmm_notifications.py` - NotificationManager + backends
- `/opt/llama-model-manager-v2.1.0/scripts/glyphos_openai_gateway.py` - Gateway request recording
- `/opt/llama-model-manager-v2.1.0/web/app.py` - Dashboard state API + run_history

### Secondary (MEDIUM confidence)
- `/opt/llama-model-manager-v2.1.0/.planning/ROADMAP.md` - Phase definitions
- `/opt/llama-model-manager-v2.1.0/.planning/STATE.md` - Current project state
- `/opt/llama-model-manager-v2.1.0/bin/llama-model` - CLI entry point patterns

### Tertiary (LOW confidence)
- Web search for "Python handoff summary patterns" — not yet performed; may reveal additional patterns
- Web search for "llama.cpp session management" — not yet performed; gap in ecosystem knowledge

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib, matches existing architecture
- Architecture: HIGH - Extends existing modules with clear patterns
- Pitfalls: MEDIUM - Some pitfalls identified from similar projects; need validation during implementation

**Research date:** 2026-04-30
**Valid until:** 2026-05-30 (30 days for stable stdlib patterns)

---

## Appendix: Module Breakdown for Phase 06

### New Modules

#### `scripts/lmm_handoff.py`
**Purpose:** Generate handoff summaries from completed RunRecords
**Key exports:**
- `HandoffSummary` dataclass
- `JsonHandoffStore` (extends JsonRunRecordStore)
- `generate_handoff_summary(record: dict) -> HandoffSummary`
- `format_handoff_text(summary: HandoffSummary) -> str`

**Estimated size:** 150-200 lines

#### `scripts/lmm_session.py` (optional)
**Purpose:** Track multi-run sessions (if needed beyond single-run session_id)
**Key exports:**
- `SessionTracker` class
- `link_runs_to_session(run_ids: list[str], session_id: str) -> None`

**Estimated size:** 80-100 lines (may defer to Phase 06 follow-up)

### Modified Modules

#### `scripts/lmm_types.py`
**Changes:** Add 5 optional fields to RunRecord (session_id, upstream_session_ref, handoff_summary, artifacts, tags)
**Impact:** Backward compatible — all new fields have defaults
**Testing:** Extend existing test_phase0_contracts.py RunRecord tests

#### `scripts/glyphos_openai_gateway.py`
**Changes:** Extract session metadata in do_POST; populate new RunRecord fields; trigger handoff summary generation for long runs
**Impact:** Extends existing recording logic (lines ~982-1134)
**Testing:** Add test for session metadata extraction

#### `web/app.py`
**Changes:**
- Add `/api/handoff/summary` endpoint
- Extend `_load_run_history()` with summary mode (condensed view)
- Add `API_POST_PAYLOAD_SCHEMAS` entry for handoff

**Impact:** Moderate — 2-3 new route handlers
**Testing:** Add test in test_phase0_contracts.py pattern

#### `web/app.js`
**Changes:** Add `renderSessionHandoffs()` function; call from `renderStatus()`
**Impact:** New UI section in dashboard
**Testing:** Manual browser testing

#### `web/index.html`
**Changes:** Add `<section id="session-handoffs-panel">` in dashboard main area
**Impact:** HTML structure addition
**Testing:** Visual inspection

#### `bin/llama-model`
**Changes:** Add `handoff` subparser with `status` subcommand
**Impact:** Extends existing argparse structure (see `scripts/integration_sync.py` for pattern)
**Testing:** CLI integration test

### Integration Points Summary

| Component | Integration Method | Data Flow |
|-----------|-------------------|------------|
| Gateway → Handoff | Extend `safe_record_run_record()` call | RunRecord with session fields → lmm_handoff.py |
| Handoff → Storage | Reuse JsonRunRecordStore | HandoffSummary serialized to run_records.json |
| Handoff → Notifications | Extend NotificationManager | New NotificationType.HANDOFF_READY |
| Handoff → CLI | New `llama-model handoff` subcommand | Read from JsonRunRecordStore |
| Handoff → Dashboard | New `/api/handoff/summary` endpoint | HTTP JSON response |

### Success Criteria (Observable, Testable)

1. **RunRecord extensible:** Adding handoff fields to RunRecord doesn't break existing to_dict()/from_dict() round-trip
   - Test: `test_run_record_handoff_fields_round_trip()`

2. **Handoff summary generated:** Calling `generate_handoff_summary()` on a completed RunRecord produces valid HandoffSummary
   - Test: `test_handoff_summary_from_completed_run()`

3. **CLI status works:** `llama-model handoff status` prints latest completed run in < 1s
   - Test: `test_cli_handoff_status_runs()`

4. **Dashboard shows history:** Session handoff panel renders last 10 long-running sessions
   - Test: Manual browser verification

5. **Gateway records session:** Gateway do_POST extracts session metadata and populates RunRecord
   - Test: `test_gateway_session_metadata_recorded()`

### Dependencies & Ordering

**Must be built first:** None — Phase 06 builds on Phase 02 (run-records) and Phase 03 (notifications), which are complete.

**Recommended build order:**
1. Extend `lmm_types.py` with handoff fields (5 min)
2. Create `lmm_handoff.py` module (20 min)
3. Extend gateway recording in `glyphos_openai_gateway.py` (15 min)
4. Add CLI command to `bin/llama-model` (10 min)
5. Add API endpoint to `web/app.py` (10 min)
6. Add UI to `web/app.js` + `web/index.html` (20 min)

**Parallelizable:** Steps 3-6 can be done in parallel after steps 1-2 complete.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Upstream tools don't send session metadata | HIGH | MEDIUM | Default to run_id as session_id; document metadata format for tool authors |
| Handoff summaries are too verbose | MEDIUM | LOW | Implement prompt_preview (200 chars); make summary format configurable |
| Storage bloat from artifacts list | LOW | MEDIUM | Artifacts stored as paths only (not file contents); bounded by recent_limit |
| Notification fatigue | MEDIUM | LOW | Only notify for runs > 60s; respect existing cooldown logic |
| Breaking change to RunRecord | LOW | HIGH | All new fields optional with defaults; full backward compatibility |

# Completion Evidence Model

This document defines how completion is judged and reported in this workspace.

## Core Principle

Never mark a task complete just because files, components, or config entries exist.
Only behavior that works in the user-facing path is `complete`.

## Completion Status Rules

- `complete`: User-facing workflow works end-to-end and evidence is verified in the target runtime.
- `verified_limited`: Target runtime was checked and constraints or unsupported paths were explicitly observed and documented.
- `partial`: Some behavior works, but the acceptance criteria are not yet fully met.
- `scaffolded`: Structure or wiring exists, but functional behavior has not been proven.
- `blocked`: Work cannot continue due to missing dependency, permission issue, hardware/device limitation, service outage, or unresolved decision.

## Evidence Requirements

1. Keep implementation proof and user-facing proof separate.
2. Distinguish between static checks and runtime checks.
3. If a user reports a previously claimed behavior still fails, immediately downgrade that claim to `partial` until it is revalidated.
4. Never use `complete` for browser, audio, mic, camera, OS, notification, desktop, mobile, or hardware-sensitive behavior unless real target runtime behavior is verified.
5. For scoped tests limited to mock/headless/unit/build signals, use:
   - `scaffolded` if behavior is unproven
   - `verified_limited` if limitations are explicitly captured and tested.

## Required Final Report Shape (User-Facing Work)

- `Status:`
- `Implementation evidence:`
- `User-facing evidence:`
- `Remaining gaps:`
- `Next verification needed:`

## Runtime-Dependent Evidence Templates

### UI Work

For a UI task to be `complete`, verify all of:

1. Open the surface
2. Perform the user action
3. Observe expected result
4. Observe and record supported/unsupported state when applicable

### Audio / Voice Work

For audio/voice tasks to be `complete`, verify all of:

1. Browser/runtime tested
2. Mic or relevant permission observed
3. Capture, transcription, and playback (or equivalent) results recorded
4. Limitation/error is surfaced in UI when unsupported

## Audit / Rollback Rule

- If evidence is incomplete or behavior regresses, do not keep `complete`; update status to `partial`, `verified_limited`, or `scaffolded` with exact rationale.

## Revision Note

This model is authoritative for milestone closure and final summaries in this repository.

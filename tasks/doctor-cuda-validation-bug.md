# Bug: `llama-model doctor` exits before diagnostics when CUDA bundle validation cannot detect host compute capability

## Observed Failure

Running the deployed CLI directly can fail before printing doctor diagnostics:

```text
error: configured bundled binary /home/angelo/.local/share/llama-model-manager/runtime/llama-server/linux-x86_64-cuda/llama-server failed validation: host CUDA compute capability could not be detected. Fix the bundle or select a different binary.
```

The new oh-my-openagent wake-patch guard is present and works when doctor is run with a neutral runtime override, but the normal path exits too early to show it.

## Impact

`doctor` is supposed to be the recovery surface. A runtime validation problem should be reported as diagnostic fields and guidance, not block unrelated health checks such as OpenCode, oh-my-openagent, gateway state, install state, and route drift.

## Likely Cause

Runtime selection/validation runs before `show_doctor` can collect diagnostics. The validation failure is treated as fatal for every command, including `doctor`.

## Fix Plan

- Make `doctor` tolerant of runtime validation failures by allowing the command to enter `show_doctor` with `SELECTED_LLAMA_SERVER_STATUS`/`VALIDATE_RUNTIME_*` populated as failed/unavailable instead of exiting.
- Preserve fatal validation behavior for commands that actually launch or switch runtimes.
- Add a portability regression that configures an invalid CUDA bundle/undetectable compute capability and asserts `doctor` still prints route, binary, and oh-my-openagent diagnostics.
- Keep the existing actionable CUDA guidance in the output so the operator still knows how to repair the runtime bundle.

## Verification

- `llama-model doctor` prints diagnostics even when CUDA validation cannot detect host compute capability.
- `llama-model switch` and runtime launch paths still fail fast when the selected runtime is incompatible.
- Existing portability tests plus the new doctor-failure regression pass.

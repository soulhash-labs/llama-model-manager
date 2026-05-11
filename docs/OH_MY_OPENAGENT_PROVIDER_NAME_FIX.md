# oh-my-openagent Provider Name Fix

## Date

2026-05-09

## Root Cause

`llama-model sync-opencode` configured oh-my-openagent agents and categories with
model identifiers using the provider prefix `glyphos/` and `glyphos-fast/`:

```
glyphos/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q6_K.gguf
glyphos-fast/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q6_K.gguf
```

But the actual OpenCode provider names — written into `opencode.json` by the
same sync command — are `llamacpp` and `llamacpp_fast`:

```
llamacpp/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q6_K.gguf      ← port 4010 (GlyphOS full)
llamacpp_fast/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q6_K.gguf ← port 4011 (GlyphOS fast)
```

When oh-my-openagent (or OpenCode itself) tries to resolve
`glyphos/Qwen3.5-4B-...gguf`, it looks for a provider named `glyphos` which
doesn't exist — hence: **"configured model ... is not valid"**.

## Files Changed

### `bin/llama-model` — 2 edits

| Lines | Was | Now |
|-------|-----|-----|
| 4929, 4931 | `glyphos/$SYNC_TARGET_MODEL_NAME`<br>`glyphos-fast/$SYNC_TARGET_MODEL_NAME` | `llamacpp/$SYNC_TARGET_MODEL_NAME`<br>`llamacpp_fast/$SYNC_TARGET_MODEL_NAME` |
| 4960, 4961 | `--full-provider-name glyphos`<br>`--fast-provider-name glyphos-fast` | `--full-provider-name llamacpp`<br>`--fast-provider-name llamacpp_fast` |

The first edits fix the model validation set used by
`_validate_opencode_model_catalog`. The second edits fix the actual provider
prefixes written into `oh-my-openagent.json`.

### `scripts/integration_sync.py` — 2 edits

| Lines | Was | Now |
|-------|-----|-----|
| 489 | `default="sisyphus,prometheus,metis,atlas,sisyphus-junior"` | `default="sisyphus,prometheus,hephaestus,atlas,metis,momus,oracle,librarian,explore,multimodal-looker,sisyphus-junior"` |
| 491 | `default=""` | `default="ultrabrain,deep,unspecified-high,quick,visual-engineering,writing,artistry,unspecified-low"` |

The `--agents` default was missing 6 agents (`hephaestus`, `oracle`, `momus`,
`librarian`, `explore`, `multimodal-looker`), so those agents were never
updated by `sync-opencode` and would retain stale model identifiers.

The `--categories` default was empty (`""`), so categories were never updated by
`sync-opencode`. All 8 categories would carry stale model identifiers forever
unless a user manually passed `--categories`.

## Lane Mappings

The lane assignment in `integration_sync.py` (`L124-L127`) is correct and was
not changed. The fix only corrects the provider name string used to construct
the model identifier.

| Lane | Provider Name | Agents | Categories |
|------|---------------|--------|------------|
| Full (GlyphOS) | `llamacpp` → port 4010 | sisyphus, prometheus, hephaestus, atlas, metis, momus, oracle | ultrabrain, deep, unspecified-high |
| Fast (GlyphOS) | `llamacpp_fast` → port 4011 | librarian, explore, multimodal-looker, sisyphus-junior | quick, visual-engineering, writing, artistry, unspecified-low |

## Verification

Check that all agent and category model identifiers in
`oh-my-openagent.json` use `llamacpp/` or `llamacpp_fast/` prefixes:

```bash
python3 -c "
import json
with open('$HOME/.config/opencode/oh-my-openagent.json') as f:
    d = json.load(f)
bad = [n for n,c in d.get('agents',{}).items()
       if not c.get('model','').startswith(('llamacpp/','llamacpp_fast/'))]
bad += [n for n,c in d.get('categories',{}).items()
        if not c.get('model','').startswith(('llamacpp/','llamacpp_fast/'))]
print('✓ All valid' if not bad else f'Issues: {bad}')
```

Also check that the OpenCode model catalog includes matching entries:

```bash
opencode models
# Expected:
#   llamacpp/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q6_K.gguf
#   llamacpp_fast/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q6_K.gguf
```

## Fresh Install (from this repo)

**No action needed.** `install.sh` copies the fixed files automatically.
After install, `llama-model switch <model>` runs `sync-opencode` which produces
correct oh-my-openagent configs.

## Existing Deployment Upgrade

For a user with an older installation, two approaches:

### Option A — Re-run install.sh (recommended)

```bash
cd <this-repo>
./install.sh
llama-model sync-opencode
```

### Option B — Targeted fix

1. Edit `~/.local/bin/llama-model`:
   - Lines 4929, 4931: `glyphos/` → `llamacpp/`, `glyphos-fast/` → `llamacpp_fast/`
   - Lines 4960, 4961: `--full-provider-name glyphos` → `--full-provider-name llamacpp`,
     `--fast-provider-name glyphos-fast` → `--fast-provider-name llamacpp_fast`

2. Edit `~/.local/share/llama-model-manager/scripts/integration_sync.py`:
   - `--agents` default: expand to all 11 agents
   - `--categories` default: set to all 8 categories

3. Regenerate the config:
   ```bash
   llama-model sync-opencode
   ```

## Recovery: Plugin Failure Mode

If oh-my-openagent encounters a `ProviderModelNotFoundError` or similar plugin
failure, OpenCode can become unusable even though LMM, llama-server, the LMM
gateways, and the dashboard are separate processes that continue running.

### Detection

```bash
llama-model doctor
```

Look for these fields:

```
oh_my_openagent_recent_error: ProviderModelNotFoundError
oh_my_openagent_recent_error_detail: Model not found: glyphos-fast/...
oh_my_openagent_recent_error_log: /tmp/oh-my-opencode.log
oh_my_openagent_recent_error_guidance: Run llama-model sync-opencode to replace...
oh_my_openagent_plugin_enabled: yes
```

### Safe Mode (Disable Plugin)

If the plugin is causing OpenCode to stall or crash, disable it without deleting
the oh-my-openagent configuration:

```bash
llama-model opencode-plugin status
llama-model opencode-plugin disable
```

This removes only the `oh-my-openagent` entry from `opencode.json`'s `plugin`
list and saves a backup to `opencode.json.lmm-plugin-backup`. Restart OpenCode
after changing plugin status.

To restore:

```bash
llama-model opencode-plugin enable
```

The enable command restores the plugin from the backup or reports what to
install. It does not duplicate an already-present plugin entry.

## Scope

This fix only affects oh-my-openagent provider naming. The following are
**unrelated** and were not changed:

- **`opencode.json`** — Provider names (`llamacpp`, `llamacpp_fast`) were
  already correct.
- **GlyphOS AI Compute** — The gateway endpoints, routing, telemetry, and
  `~/.glyphos/config.yaml` are separate concerns.
- **`share_orion/`** — Contains only GlyphOS API/gateway references, not the
  agent naming issue.

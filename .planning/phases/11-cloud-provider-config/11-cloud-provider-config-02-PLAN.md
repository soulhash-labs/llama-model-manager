---
phase: 11-cloud-provider-config
plan: 02
type: execute
wave: 2
depends_on: ["11-cloud-provider-config-01"]
files_modified:
  - scripts/glyphos_openai_gateway.py
  - web/app.py
autonomous: true
requirements:
  - CLOUD-04

must_haves:
  truths:
    - "Doctor/status endpoint reports which cloud providers are available"
    - "Doctor reports GLYPHOS_CLOUD_ENABLED master toggle status"
    - "Doctor reports xAI-first default order"
    - "Dashboard state includes cloud provider availability"
  artifacts:
    - path: "scripts/glyphos_openai_gateway.py"
      provides: "Doctor endpoint includes cloud provider availability section"
      pattern: "cloud_providers|cloud_enabled|available_providers"
    - path: "web/app.py"
      provides: "Dashboard state includes cloud provider info"
      pattern: "cloud_providers|cloud_status"
  key_links:
    - from: "scripts/glyphos_openai_gateway.py"
      to: "web/app.py"
      via: "doctor/health endpoint feeds dashboard state"
      pattern: "doctor|health|state"
---

<objective>
Expose cloud provider configuration status through doctor endpoint and dashboard so operators can see which providers are available, which are disabled, the master toggle state, and the preferred provider order.

Purpose: Make cloud provider status visible and debuggable.
Output: Doctor endpoint cloud section, dashboard state cloud provider info.
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@scripts/glyphos_openai_gateway.py
@web/app.py
@.planning/phases/11-cloud-provider-config/11-cloud-provider-config-01-PLAN.md
</context>

<interfaces>
From scripts/glyphos_openai_gateway.py:
The gateway has health/doctor endpoints that return system status dicts.
After Plan 01, create_configured_clients() returns clients in preferred order.

From web/app.py:
The dashboard state() method returns a dict with various status sections.
Need to add cloud_providers section alongside existing glyphos/context sections.

Expected cloud_providers dict shape:
```python
{
    "enabled": True,                              # GLYPHOS_CLOUD_ENABLED
    "preferred_provider": "xai",                  # GLYPHOS_PREFERRED_CLOUD_PROVIDER
    "fallback_order": ["xai", "anthropic", "openai"],  # actual order
    "providers": {
        "xai":        {"available": True,  "enabled": True},
        "anthropic":  {"available": True,  "enabled": True},
        "openai":     {"available": False, "enabled": True},
    },
    "available_count": 2,
}
```
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Add cloud provider status to doctor/health endpoint</name>
  <files>scripts/glyphos_openai_gateway.py</files>
  <action>
    In `scripts/glyphos_openai_gateway.py`, find the health/doctor endpoint (search for `def lmm_health` or `def doctor` or `"health"` in the response dict) and add a cloud provider availability section.

    Add a helper function `_get_cloud_provider_status()` near the other health helpers:
    ```python
    def _get_cloud_provider_status() -> dict[str, Any]:
        from glyphos_ai.ai_compute.api_client import create_configured_clients  # type: ignore

        clients = create_configured_clients()
        cloud_enabled = os.environ.get("GLYPHOS_CLOUD_ENABLED", "true").strip().lower() != "false"
        preferred = os.environ.get("GLYPHOS_PREFERRED_CLOUD_PROVIDER", "xai").strip().lower()

        # Order reflects actual create_configured_clients() output (preference applied)
        fallback_order = [k for k in clients.keys() if k in ("xai", "anthropic", "openai")]

        providers = {}
        for name in ("xai", "anthropic", "openai"):
            providers[name] = {
                "available": name in clients,
                "enabled": cloud_enabled,
            }

        return {
            "cloud_enabled": cloud_enabled,
            "preferred_provider": preferred,
            "fallback_order": fallback_order,
            "providers": providers,
            "available_count": len(fallback_order),
        }
    ```

    Integrate into the doctor/health response dict by adding:
    ```python
    response["cloud_providers"] = _get_cloud_provider_status()
    ```

    The exact location depends on how the health response is structured. Find the dict that's returned and add this key to it.
  </action>
  <verify>
    <automated>python3 -c "
from pathlib import Path
src = Path('scripts/glyphos_openai_gateway.py').read_text()
checks = [
    ('cloud_providers', 'cloud provider section in response'),
    ('_get_cloud_provider_status', 'helper function'),
    ('cloud_enabled', 'master toggle in status'),
]
for pattern in checks:
    if pattern in src:
        print(f'  OK: {pattern}')
    else:
        print(f'  MISSING: {pattern}', file=__import__('sys').stderr)
        __import__('sys').exit(1)
print('doctor endpoint has cloud provider status')
"</automated>
  </verify>
  <done>
    Doctor/health endpoint includes cloud_providers section with cloud_enabled, preferred_provider, fallback_order, and per-provider availability status.
  </done>
</task>

<task type="auto">
  <name>Task 2: Add cloud provider status to dashboard state</name>
  <files>web/app.py</files>
  <action>
    In `web/app.py`, find the `state()` method (or equivalent endpoint) that returns the dashboard state dict.

    Add cloud provider status to the returned state. The dashboard needs to know:
    - Whether cloud is enabled (master toggle)
    - Which providers are available and in what order
    - The preferred provider

    Add to the state return dict:
    ```python
    "cloud_providers": {
        "enabled": True,                    # from GLYPHOS_CLOUD_ENABLED
        "preferred": "xai",                 # from GLYPHOS_PREFERRED_CLOUD_PROVIDER
        "fallback_order": ["xai", "anthropic", "openai"],  # actual order
        "available": ["xai", "anthropic"],  # list of available providers
    }
    ```

    This can be sourced by calling `_get_cloud_provider_status()` from the gateway module (if accessible) or by replicating the logic as a simple check in app.py. Since app.py is the Flask web app, it likely has access to the gateway's health functions. If not, replicate the logic inline — it's just checking env vars.

    Keep it lightweight — just the data the dashboard needs to display status. No UI changes required in this plan.
  </action>
  <verify>
    <automated>python3 -c "
from pathlib import Path
src = Path('web/app.py').read_text()
if 'cloud_provider' in src or 'cloud_providers' in src:
    print('  OK: cloud provider in dashboard state')
else:
    print('  MISSING: cloud_provider/cloud_providers', file=__import__('sys').stderr)
    __import__('sys').exit(1)
print('dashboard state includes cloud provider info')
"</automated>
  </verify>
  <done>
    Dashboard state() method includes cloud_providers dict with enabled, preferred, fallback_order, and available fields.
  </done>
</task>

</tasks>

<verification>
- Doctor endpoint returns cloud_providers section with all fields
- Dashboard state includes cloud_providers dict
- Both reflect GLYPHOS_CLOUD_ENABLED toggle
- Both reflect GLYPHOS_PREFERRED_CLOUD_PROVIDER setting (default xai)
- fallback_order matches actual clients from create_configured_clients()
- Disabled cloud (GLYPHOS_CLOUD_ENABLED=false) shows as disabled with empty available list
</verification>

<success_criteria>
- Doctor/health endpoint shows cloud provider status
- Dashboard state includes cloud provider availability
- Disabled cloud shows as disabled in both
- Available providers list matches actual configured clients
- xAI shown as default preferred provider
- fallback_order reflects the actual client creation order
</success_criteria>

<output>
After completion, create `.planning/phases/11-cloud-provider-config/11-cloud-provider-config-02-SUMMARY.md`
</output>

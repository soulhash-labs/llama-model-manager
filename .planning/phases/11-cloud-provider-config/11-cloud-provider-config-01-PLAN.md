---
phase: 11-cloud-provider-config
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py
  - integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py
  - scripts/glyphos_openai_gateway.py
autonomous: true
requirements:
  - CLOUD-01
  - CLOUD-02
  - CLOUD-03

must_haves:
  truths:
    - "GLYPHOS_CLOUD_ENABLED=false disables ALL cloud backends"
    - "GLYPHOS_CLOUD_XAI_ENABLED=false disables only xAI"
    - "API keys from ~/.glyphos/config.yaml work as fallback to env vars"
    - "ALL local llama.cpp routes (any coherence) use Unified GlyphOS pipeline"
    - "xAI is the default preferred cloud provider"
  artifacts:
    - path: "integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py"
      provides: "Cloud toggle + per-provider toggles + config.yaml API keys"
      exports: ["create_configured_clients"]
      pattern: "GLYPHOS_CLOUD_ENABLED|ai_compute.cloud"
    - path: "integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py"
      provides: "Router enforces local-first via GlyphOS, xAI-first cloud fallback"
      pattern: "local_glyphos_pipeline|cloud_fallback_order|xai"
  key_links:
    - from: "api_client.py"
      to: "router.py"
      via: "create_configured_clients returns clients in preferred order"
      pattern: "create_configured_clients"
    - from: "scripts/glyphos_openai_gateway.py"
      to: "router.py"
      via: "create_router() passes cloud_fallback_order to RoutingConfig"
      pattern: "create_router"
---

<objective>
Give operators explicit, fine-grained control over cloud backends while enforcing: ALL local traffic goes through the Unified GlyphOS pipeline (immutable), xAI is the default preferred cloud provider, and API keys can come from config.yaml.

Purpose: Replace implicit cloud activation with explicit toggles, xAI-first routing, and strong local guarantee.
Output: Cloud toggle system, config.yaml API key support, router rewrite with local-first guarantee.
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py
@integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py
@scripts/glyphos_openai_gateway.py
</context>

<interfaces>
From api_client.py (current create_configured_clients):
```python
def create_configured_clients() -> dict[str, Any]:
    config = _load_glyphos_config()  # loads ~/.glyphos/config.yaml
    clients: dict[str, Any] = {}
    # llamacpp setup ...
    # Cloud clients auto-activate from env vars only (no toggles):
    openai = OpenAIClient()   # reads OPENAI_API_KEY
    if openai.is_available():
        clients["openai"] = openai
    anthropic = AnthropicClient()  # reads ANTHROPIC_API_KEY
    if anthropic.is_available():
        clients["anthropic"] = anthropic
    xai = XAIClient()  # reads XAI_API_KEY
    if xai.is_available():
        clients["xai"] = xai
    return clients
```

Cloud client constructors accept api_key parameter:
```python
OpenAIClient(api_key=None, model="gpt-4-turbo-preview")
AnthropicClient(api_key=None, model="claude-3-sonnet-20240229")
XAIClient(api_key=None, model="grok-beta")
```

_config_value helper for dotted config path access:
```python
_config_value(config, "ai_compute.cloud.xai.api_key")  # returns string or ""
```

_env_first helper for env var priority:
```python
_env_first("XAI_API_KEY", default=_config_value(config, "ai_compute.cloud.xai.api_key", default=""))
```

From router.py (current state after high-coherence pipeline commit):
```python
# High coherence always uses GlyphOS pipeline
if psi >= self.config.high_coherence_threshold and self.llamacpp:
    target = ComputeTarget.LOCAL_LLAMACPP
    reason = "high coherence - Unified GlyphOS pipeline"
    reason_code = "high_coherence_glyphos_pipeline"
    if context_payload is None:
        context_payload = ContextPayload(raw_context="", encoding_status="none")
# Complex actions: hardcoded Anthropic-first
elif action in self.config.complex_actions:
    if self.anthropic:
        target = ComputeTarget.EXTERNAL_ANTHROPIC
    elif self.openai:
        target = ComputeTarget.EXTERNAL_OPENAI
    elif self.llamacpp:
        target = ComputeTarget.LOCAL_LLAMACPP
# Default fallback: hardcoded OpenAI-first
elif self.llamacpp:
    target = ComputeTarget.LOCAL_LLAMACPP
elif self.openai:
    target = ComputeTarget.EXTERNAL_OPENAI
elif self.anthropic:
    target = ComputeTarget.EXTERNAL_ANTHROPIC
elif self.xai:
    target = ComputeTarget.EXTERNAL_XAI
```

Current route_stream() always uses build_prompt_from_packet (already updated).

RoutingConfig:
```python
@dataclass
class RoutingConfig:
    high_coherence_threshold: float = 0.8
    low_coherence_threshold: float = 0.3
    complex_actions: list[str] | None = None
```
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Cloud toggle system + config.yaml API key support in api_client.py</name>
  <files>integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py</files>
  <action>
    Rewrite `create_configured_clients()` in `api_client.py` to support master toggle, per-provider toggles, config.yaml API keys, and xAI-first ordering.

    **1. Add helper functions** near the top of the file (after existing helpers):
    ```python
    def _bool_env(name: str, default: str = "true") -> bool:
        """Read a boolean env var, with config fallback."""
        return os.environ.get(name, default).strip().lower() != "false"

    def _provider_enabled(provider: str, config: dict[str, Any]) -> bool:
        """Check if a cloud provider is enabled via env var or config."""
        env_key = f"GLYPHOS_CLOUD_{provider.upper()}_ENABLED"
        config_key = f"ai_compute.cloud.{provider}.enabled"
        return _bool_env(env_key, _config_value(config, config_key, default="true"))
    ```

    **2. Rewrite `create_configured_clients()`**:
    ```python
    def create_configured_clients() -> dict[str, Any]:
        config = _load_glyphos_config()
        clients: dict[str, Any] = {}

        _warn_on_retired_configuration(config)

        # --- Local llama.cpp setup (unchanged) ---
        llama_url = _env_first(
            "GLYPHOS_LLAMACPP_URL",
            default=_config_value(config, "ai_compute.llamacpp.url", default="http://127.0.0.1:8081/v1"),
        )
        # ... (keep existing llamacpp client creation logic, same as current)
        # ... (keep existing lane client creation logic, same as current)

        # --- Cloud backends ---
        cloud_enabled = _bool_env(
            "GLYPHOS_CLOUD_ENABLED",
            _config_value(config, "ai_compute.cloud.enabled", default="true"),
        )
        if not cloud_enabled:
            return clients  # Return llamacpp clients only

        preferred = _env_first(
            "GLYPHOS_PREFERRED_CLOUD_PROVIDER",
            _config_value(config, "ai_compute.cloud.preferred_provider", default="xai"),
        ).lower()

        # Build ordered list: preferred first, rest in default order
        default_order = ["xai", "anthropic", "openai"]
        if preferred in default_order:
            order = [preferred] + [p for p in default_order if p != preferred]
        else:
            order = default_order

        for provider in order:
            if not _provider_enabled(provider, config):
                continue

            key = _env_first(
                f"{provider.upper()}_API_KEY",
                _config_value(config, f"ai_compute.cloud.{provider}.api_key", default=""),
            )
            model = _env_first(
                f"GLYPHOS_{provider.upper()}_MODEL",
                _config_value(config, f"ai_compute.cloud.{provider}.model", default=""),
            )

            client = None
            if provider == "xai":
                client = XAIClient(api_key=key or None, model=model or "grok-beta")
            elif provider == "anthropic":
                client = AnthropicClient(api_key=key or None, model=model or "claude-3-sonnet-20240229")
            elif provider == "openai":
                client = OpenAIClient(api_key=key or None, model=model or "gpt-4-turbo-preview")

            if client and client.is_available():
                clients[provider] = client

        return clients
    ```

    **Key behaviors:**
    - `GLYPHOS_CLOUD_ENABLED=false` → returns only llamacpp clients
    - `GLYPHOS_CLOUD_XAI_ENABLED=false` → skips xAI even if key present
    - `XAI_API_KEY` from env takes priority over `ai_compute.cloud.xai.api_key` in config.yaml
    - Default order: xai → anthropic → openai (xAI first)
    - `GLYPHOS_PREFERRED_CLOUD_PROVIDER=openai` → openai → xai → anthropic
    - Empty model string falls back to client class default

    **IMPORTANT**: Keep the existing llamacpp client creation code unchanged. Only replace the cloud client creation section (the last ~30 lines of the function that create OpenAIClient, AnthropicClient, XAIClient).
  </action>
  <verify>
    <automated>python3 -c "
from pathlib import Path
src = Path('integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py').read_text()
checks = [
    ('GLYPHOS_CLOUD_ENABLED', 'master toggle'),
    ('ai_compute.cloud.enabled', 'config toggle'),
    ('ai_compute.cloud.xai.api_key', 'config API key'),
    ('GLYPHOS_CLOUD_XAI_ENABLED', 'per-provider toggle'),
    ('GLYPHOS_PREFERRED_CLOUD_PROVIDER', 'preferred provider'),
    ('_provider_enabled', 'provider enabled helper'),
]
for pattern, desc in checks:
    if pattern in src:
        print(f'  OK: {desc} ({pattern})')
    else:
        print(f'  MISSING: {desc} ({pattern})', file=__import__('sys').stderr)
        __import__('sys').exit(1)
print('api_client.py: all cloud config features present')
"</automated>
  </verify>
  <done>
    create_configured_clients() supports GLYPHOS_CLOUD_ENABLED master toggle, per-provider toggles, config.yaml API keys, xAI-first default order, and GLYPHOS_PREFERRED_CLOUD_PROVIDER.
  </done>
</task>

<task type="auto">
  <name>Task 2: Router rewrite — local-first via GlyphOS, xAI-first cloud fallback</name>
  <files>
    integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py
  </files>
  <action>
    Rewrite the `AdaptiveRouter.route()` method to enforce:
    1. **ALL local traffic goes through GlyphOS** (any coherence level)
    2. **Cloud only when local unavailable**
    3. **xAI-first cloud fallback order**

    **Add `cloud_fallback_order` + `preferred_cloud` to `RoutingConfig`:**
    ```python
    @dataclass
    class RoutingConfig:
        high_coherence_threshold: float = 0.8
        low_coherence_threshold: float = 0.3
        complex_actions: list[str] | None = None
        cloud_fallback_order: list[str] | None = None  # e.g. ["xai", "anthropic", "openai"]
        preferred_cloud: str | None = None              # e.g. "openai" — promoted to front at route time
    ```

    In `route()`, resolve the cloud order with preference promotion:
    ```python
    default_order = ["xai", "anthropic", "openai"]
    cloud_order = self.config.cloud_fallback_order or list(default_order)

    # If user set a preferred provider, promote it to front (belt-and-suspenders)
    preferred = self.config.preferred_cloud
    if preferred and preferred in cloud_order:
        cloud_order = [preferred] + [p for p in cloud_order if p != preferred]
    ```

    This way the order is already correct from `create_configured_clients()` AND the router re-enforces it. If the gateway forgets to pass the order, the router still uses xAI-first default.

    **Rewrite `route()` method** — replace the entire routing decision logic:
    ```python
    def route(
        self, glyph_packet, prompt: Optional[str] = None, context_payload=None, **generation_kwargs: Any
    ) -> RoutingResult:
        """Route a glyph packet.

        STRONG GUARANTEE: ALL local traffic goes through Unified GlyphOS pipeline.
        Cloud is only used when local llama.cpp is unavailable.
        """
        if prompt is None:
            prompt = glyph_to_prompt(glyph_packet)

        psi = self._packet_value(glyph_packet, "psi_coherence", "psiCoherence", 0.5)
        action = glyph_packet.action

        # === ALL LOCAL TRAFFIC → Unified GlyphOS pipeline ===
        if self.llamacpp:
            if context_payload is None:
                context_payload = ContextPayload(raw_context="", raw_context_chars=0, encoding_status="none")

            # Build encoding-aware prompt
            built_prompt = build_prompt_from_packet(glyph_packet, context_payload, prompt)
            glyph_packet.encoding_status = context_payload.encoding_status
            glyph_packet.encoding_format = context_payload.encoding_format
            glyph_packet.encoding_ratio = context_payload.encoding_ratio

            reason = "local_glyphos_pipeline"
            reason_code = "local_glyphos_pipeline"
            return self._route_llamacpp(built_prompt, reason, reason_code, **generation_kwargs)

        # === LOCAL UNAVAILABLE → Cloud fallback ===
        cloud_order = self.config.cloud_fallback_order or ["xai", "anthropic", "openai"]

        # Determine reason based on action type
        is_complex = action in (self.config.complex_actions or [])

        for provider in cloud_order:
            client = getattr(self, provider, None)
            if client and client.is_available():
                target = _CLOUD_TARGET_MAP[provider]
                reason = f"complex action - prefer {provider}" if is_complex else f"fallback - use {provider}"
                reason_code = f"complex_action_{provider}" if is_complex else f"fallback_{provider}"

                # Cloud always gets raw context
                built_prompt = prompt
                return self._route_cloud(target, built_prompt, reason, reason_code, **generation_kwargs)

        # No backends available
        return RoutingResult(
            target=ComputeTarget.FALLBACK,
            response="No compute backend available",
            routing_reason="no backends configured",
            routing_reason_code="no_backends_configured",
        )
    ```

    **Add `_CLOUD_TARGET_MAP` constant** at module level (after ComputeTarget enum):
    ```python
    _CLOUD_TARGET_MAP: dict[str, ComputeTarget] = {
        "xai": ComputeTarget.EXTERNAL_XAI,
        "anthropic": ComputeTarget.EXTERNAL_ANTHROPIC,
        "openai": ComputeTarget.EXTERNAL_OPENAI,
    }
    ```

    **Add `_route_cloud()` helper method** to AdaptiveRouter class:
    ```python
    def _route_cloud(
        self, target: ComputeTarget, prompt: str, reason: str, reason_code: str, **generation_kwargs: Any
    ) -> RoutingResult:
        """Route to a cloud backend."""
        start = time.perf_counter()
        client = getattr(self, target.value, None)
        if not client:
            return RoutingResult(
                target=target,
                response=f"No {target.value} client configured",
                routing_reason=reason,
                routing_reason_code=f"{reason_code}.no_client",
            )
        try:
            response = client.generate(prompt, **generation_kwargs)
            latency_ms = round((time.perf_counter() - start) * 1000)
            self._track_route(target, reason_code, latency_ms=latency_ms)
            return RoutingResult(
                target=target,
                response=response,
                routing_reason=reason,
                routing_reason_code=reason_code,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000)
            self._track_route(target, reason_code, is_error=True, latency_ms=latency_ms, error_message=str(exc))
            return RoutingResult(
                target=target,
                response=f"{target.value} request failed: {exc}",
                routing_reason=reason,
                routing_reason_code=f"{reason_code}.error",
                latency_ms=latency_ms,
            )
    ```

    This replaces the individual `_route_openai()`, `_route_anthropic()`, `_route_xai()` methods.
    However, keep the existing individual methods as thin wrappers for backward compat if anything calls them directly:
    ```python
    def _route_openai(self, prompt, reason, reason_code, **kw):
        return self._route_cloud(ComputeTarget.EXTERNAL_OPENAI, prompt, reason, reason_code, **kw)
    def _route_anthropic(self, prompt, reason, reason_code, **kw):
        return self._route_cloud(ComputeTarget.EXTERNAL_ANTHROPIC, prompt, reason, reason_code, **kw)
    def _route_xai(self, prompt, reason, reason_code, **kw):
        return self._route_cloud(ComputeTarget.EXTERNAL_XAI, prompt, reason, reason_code, **kw)
    ```

    **Update `route_stream()`** — the high-coherence pipeline change already ensures it always uses build_prompt_from_packet. Update the reason codes to use `local_glyphos_pipeline` for all streaming routes (they're always local anyway).

    **Update gateway `create_router()`** in `scripts/glyphos_openai_gateway.py`:
    ```python
    def create_router():
        clients = create_configured_clients()
        cloud_order = [k for k in clients if k in ("xai", "anthropic", "openai")]
        preferred = os.environ.get("GLYPHOS_PREFERRED_CLOUD_PROVIDER", "xai").strip().lower()
        config = RoutingConfig(
            cloud_fallback_order=cloud_order,
            preferred_cloud=preferred,
        )
        return AdaptiveRouter(
            llamacpp_client=clients.get("llamacpp"),
            openai_client=clients.get("openai"),
            anthropic_client=clients.get("anthropic"),
            xai_client=clients.get("xai"),
            config=config,
        )
    ```
  </action>
  <verify>
    <automated>python3 -c "
from pathlib import Path
src = Path('integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py').read_text()
checks = [
    ('local_glyphos_pipeline', 'local-first reason code'),
    ('cloud_fallback_order', 'configurable cloud order'),
    ('_CLOUD_TARGET_MAP', 'cloud target mapping'),
    ('_route_cloud', 'unified cloud routing helper'),
    ('xai.*anthropic.*openai', 'xAI-first default order'),
]
import re, sys
for pattern, desc in checks:
    if re.search(pattern, src):
        print(f'  OK: {desc}')
    else:
        print(f'  MISSING: {desc} ({pattern})', file=sys.stderr)
        sys.exit(1)
print('router.py: all routing features present')
"</automated>
  </verify>
  <done>
    Router always routes to local via GlyphOS when llamacpp is available. Cloud fallback uses xAI-first order. _route_cloud helper consolidates cloud routing. Existing _route_openai/anthropic/xai kept as thin wrappers. Gateway passes cloud_fallback_order to RoutingConfig.
  </done>
</task>

</tasks>

<verification>
- GLYPHOS_CLOUD_ENABLED=false → only llamacpp clients returned, router always uses local or fallback
- GLYPHOS_CLOUD_XAI_ENABLED=false → xAI skipped even if API key present
- API keys from config.yaml (ai_compute.cloud.xai.api_key) work when env var not set
- GLYPHOS_PREFERRED_CLOUD_PROVIDER=openai → cloud order: openai → xai → anthropic
- Default cloud order: xai → anthropic → openai
- Router with local available: ALWAYS uses local_glyphos_pipeline
- Router without local: iterates cloud_fallback_order for first available provider
- Route telemetry records correct reason_code for all paths
- Backward compat: existing _route_openai/anthropic/xai methods still callable
</verification>

<success_criteria>
- Master cloud toggle (GLYPHOS_CLOUD_ENABLED) disables all cloud backends
- Per-provider toggles work independently
- API keys from config.yaml function as fallback to env vars
- xAI is the default preferred cloud provider (xAI-first fallback order)
- ALL local routes use local_glyphos_pipeline reason code
- No coherence-level bypass of GlyphOS pipeline for local routes
- Router _route_cloud helper handles all cloud backends uniformly
- Gateway create_router() passes cloud_fallback_order from client dict
- Existing individual _route_* methods kept as thin wrappers
</success_criteria>

<output>
After completion, create `.planning/phases/11-cloud-provider-config/11-cloud-provider-config-01-SUMMARY.md`
</output>

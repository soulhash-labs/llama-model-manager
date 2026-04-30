---
phase: 04-provider-protocol
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/lmm_providers.py
  - tests/test_phase0_contracts.py
autonomous: true
requirements: [PROVIDER-01]
user_setup: []

must_haves:
  truths:
    - "Provider protocol defines generate(), generate_stream(), health_check(), metadata()"
    - "LlamaCppProvider implements the protocol using stdlib urllib (no dependencies)"
    - "Provider registry selects providers by priority and criteria matching"
    - "Providers can be registered, queried, and listed"
  artifacts:
    - path: "scripts/lmm_providers.py"
      provides: "Provider Protocol, LlamaCppProvider, ProviderRegistry"
      exports: ["Provider", "LlamaCppProvider", "ProviderRegistry"]
  key_links:
    - from: "scripts/lmm_providers.py"
      to: "scripts/lmm_errors.py"
      via: "raises ProviderError, ProviderTimeoutError"
      pattern: "from lmm_errors import.*ProviderError"
---

<objective>
Create a Provider protocol with a stdlib-only LlamaCppProvider and a priority-based ProviderRegistry.

Purpose: Enable multi-backend routing through a unified interface. Foundation for future Ollama, vLLM, cloud provider support.
Output: lmm_providers.py with Provider protocol, LlamaCppProvider, ProviderRegistry
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@scripts/lmm_errors.py
@scripts/lmm_config.py
@scripts/glyphos_openai_gateway.py (route_prompt, route_prompt_stream functions)
@integrations/public-glyphos-ai-compute/glyphos_ai/providers/base.py
@docs/ACE-PATTERN-TRANSFER-ANALYSIS.md (Pattern 5: Provider Protocol + Registry)
</context>

<interfaces>
<!-- Key contracts from Phase 1. -->

From scripts/lmm_errors.py:
```python
class ProviderError(LMMError):
    error_type = "provider_error"

class ProviderTimeoutError(ProviderError):
    error_type = "provider_timeout_error"
    def __init__(self, provider: str, timeout_seconds: float, message: str | None = None) -> None: ...
```
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Create Provider protocol and LlamaCppProvider</name>
  <files>scripts/lmm_providers.py</files>
  <action>
Create scripts/lmm_providers.py with:

1. `Provider` Protocol (typing.Protocol):
   ```python
   class Provider(Protocol):
       @property
       def name(self) -> str: ...
       @property
       def supports_streaming(self) -> bool: ...
       def health_check(self, timeout: float = 5.0) -> bool: ...
       def metadata(self) -> dict[str, Any]: ...
       def generate(self, prompt: str, model: str = "", max_tokens: int = 1000, temperature: float = 0.7) -> str: ...
       def generate_stream(self, prompt: str, model: str = "", max_tokens: int = 1000, temperature: float = 0.7) -> Iterator[str]: ...
   ```

2. `LlamaCppProvider` class implementing Provider:
   - `__init__(self, base_url: str = "http://127.0.0.1:8081/v1", model: str = "", timeout: float = 300.0)`
   - Uses stdlib `urllib.request` for HTTP calls (same pattern as existing http_json in gateway)
   - `name` property: "llamacpp"
   - `supports_streaming`: True (llama.cpp supports SSE streaming)
   - `health_check(timeout)`: GET {base_url}/models, returns True if 200
   - `metadata()`: returns {"name": "llamacpp", "base_url": base_url, "model": resolved_model, "supports_streaming": True}
   - `generate()`: POST {base_url}/chat/completions with OpenAI-compatible payload. Returns response.choices[0].message.content. Raises ProviderError on HTTP failure, ProviderTimeoutError on timeout.
   - `generate_stream()`: POST with stream=True, yields text tokens from SSE data lines. Same SSE parsing as existing gateway stream_completion function.
   - `_resolve_model()`: GET {base_url}/models, returns first model ID. Falls back to "local-llama".

3. Do NOT add external providers (OpenAI, Anthropic) yet — this phase establishes the protocol and local provider only. External providers would be a separate phase.

4. Keep it stdlib-only for LlamaCppProvider. Use `urllib.request`, `urllib.error`, `json`, `time`.

5. Extract the HTTP helper (`_http_json`) from the gateway's http_json function into a private function in this module for reuse. It's the same pattern: `urllib.request.Request` + `urlopen` + JSON parse.
  </action>
  <verify>
    <automated>python3 -c "
import sys; sys.path.insert(0, 'scripts')
from lmm_providers import Provider, LlamaCppProvider
# Verify LlamaCppProvider implements the protocol
p = LlamaCppProvider(base_url='http://127.0.0.1:9999/v1')
assert p.name == 'llamacpp'
assert p.supports_streaming is True
# health_check on unreachable should return False
assert p.health_check(timeout=1.0) is False
meta = p.metadata()
assert meta['name'] == 'llamacpp'
print('lmm_providers OK')
"</automated>
  </verify>
  <done>LlamaCppProvider implements Provider protocol, health_check returns False for unreachable backend, metadata returns correct info, generate/generate_stream use stdlib urllib</done>
</task>

<task type="auto">
  <name>Task 2: Create ProviderRegistry</name>
  <files>scripts/lmm_providers.py</files>
  <action>
Extend scripts/lmm_providers.py with:

1. `ProviderRegistry` class:
   - `__init__(self)` — internal dict of registered providers
   - `register(self, provider: Provider, *, priority: int = 0) -> None` — adds provider with priority (higher = preferred)
   - `unregister(self, name: str) -> bool` — removes provider by name
   - `get(self, name: str) -> Provider | None` — looks up provider by name
   - `list_all(self) -> list[Provider]` — returns all providers sorted by priority (highest first)
   - `select(self, *, streaming: bool = False, preferred: str | None = None) -> Provider | None` — selects provider matching criteria:
     - If preferred name matches a registered provider, return it
     - If streaming=True, return first provider with supports_streaming=True
     - Otherwise return highest-priority provider
   - `freeze(self) -> None` — prevents further registration (useful for production)

2. `create_default_registry() -> ProviderRegistry`:
   - Factory that creates a registry with LlamaCppProvider registered at priority 10
   - Reads LlamaCppProvider config from env: `LLAMA_MODEL_BACKEND_BASE_URL`, `LMM_GATEWAY_TIMEOUT_SECONDS` (default 300)

3. The registry should be type-safe: `select()` returns `Provider | None`, not `Any`.

4. Add `__all__` exports at the bottom.
  </action>
  <verify>
    <automated>python3 -c "
import sys; sys.path.insert(0, 'scripts')
from lmm_providers import ProviderRegistry, LlamaCppProvider, create_default_registry
reg = ProviderRegistry()
p1 = LlamaCppProvider(base_url='http://a:8081/v1')
p2 = LlamaCppProvider(base_url='http://b:8081/v1')
reg.register(p1, priority=10)
reg.register(p2, priority=5)
assert reg.get('llamacpp') is p1  # first registration with that name
assert len(reg.list_all()) == 2
assert reg.list_all()[0].name == 'llamacpp'  # highest priority first
selected = reg.select(streaming=True)
assert selected is not None
assert selected.supports_streaming is True
# Freeze prevents further registration
reg.freeze()
try:
    reg.register(p1, priority=1)
    assert False, 'should have raised'
except RuntimeError:
    pass
# Default registry has llamacpp
default = create_default_registry()
assert default.get('llamacpp') is not None
print('ProviderRegistry OK')
"</automated>
  </verify>
  <done>Registry registers/unregisters providers, selects by criteria, freezes to prevent mutation, default registry includes LlamaCppProvider</done>
</task>

<task type="auto">
  <name>Task 3: Add contract tests for provider protocol and registry</name>
  <files>tests/test_phase0_contracts.py</files>
  <action>
Add tests to tests/test_phase0_contracts.py:

1. `test_llamacpp_provider_implements_protocol` — Verify LlamaCppProvider has all required protocol methods (name, supports_streaming, health_check, metadata, generate, generate_stream).

2. `test_llamacpp_provider_health_check_unreachable` — health_check on unreachable URL returns False within timeout.

3. `test_provider_registry_registers_and_lists_providers` — Register two providers with different priorities, list_all returns them in priority order.

4. `test_provider_registry_select_by_streaming` — Register a streaming and non-streaming provider (use mock), select(streaming=True) returns the streaming one.

5. `test_provider_registry_select_preferred` — select(preferred="llamacpp") returns the llamacpp provider even if it's not highest priority.

6. `test_provider_registry_freeze_prevents_registration` — After freeze(), register() raises RuntimeError.

7. `test_create_default_registry_has_llamacpp` — create_default_registry() returns a registry with "llamacpp" provider.

Use mock objects for streaming/non-streaming providers in tests 4-5. Use temp env vars for test 7.
  </action>
  <verify>
    <automated>python3 -m unittest tests.test_phase0_contracts.Phase0ContractTests.test_llamacpp_provider_implements_protocol tests.test_phase0_contracts.Phase0ContractTests.test_llamacpp_provider_health_check_unreachable tests.test_phase0_contracts.Phase0ContractTests.test_provider_registry_registers_and_lists_providers tests.test_phase0_contracts.Phase0ContractTests.test_provider_registry_select_by_streaming tests.test_phase0_contracts.Phase0ContractTests.test_provider_registry_select_preferred tests.test_phase0_contracts.Phase0ContractTests.test_provider_registry_freeze_prevents_registration tests.test_phase0_contracts.Phase0ContractTests.test_create_default_registry_has_llamacpp -v 2>&1</automated>
  </verify>
  <done>All 7 new tests pass, no existing tests broken</done>
</task>

</tasks>

<verification>
- Provider Protocol defines the contract for all backends
- LlamaCppProvider implements protocol with stdlib urllib only
- ProviderRegistry manages registration, selection, and freezing
- create_default_registry() returns registry with LlamaCppProvider
- No external dependencies added (OpenAI/Anthropic SDKs not imported)
</verification>

<success_criteria>
- Provider Protocol has all required methods (generate, generate_stream, health_check, metadata)
- LlamaCppProvider handles health check, generate, and streaming via stdlib urllib
- Registry selects providers by priority, streaming requirement, or preferred name
- Registry can be frozen to prevent mutation in production
- Test coverage for protocol compliance, registry selection, and default creation
</success_criteria>

<output>
After completion, create `.planning/phases/04-provider-protocol/04-provider-protocol-01-SUMMARY.md`
</output>

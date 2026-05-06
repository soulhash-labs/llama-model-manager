#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid JSON ({exc.msg} at line {exc.lineno} column {exc.colno})") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected a top-level JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def int_or_zero(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def is_stale_local_opencode_provider(name: str, provider: Any, *, active_provider: str = "llamacpp") -> bool:
    if name == active_provider or not isinstance(provider, dict):
        return False
    options = provider.get("options")
    if not isinstance(options, dict):
        return False
    base_url = str(options.get("baseURL") or options.get("baseUrl") or "").strip()
    if not base_url:
        return False
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return False
    return parsed.port == 8080


def _configure_opencode_provider(
    provider: dict[str, Any],
    *,
    name: str,
    api_base: str,
    timeout_ms: int,
    chunk_timeout_ms: int,
    model_name: str,
    display_name: str,
) -> dict[str, Any]:
    provider["npm"] = provider.get("npm", "@ai-sdk/openai-compatible")
    provider["name"] = provider.get("name", name)
    options = provider.get("options")
    if not isinstance(options, dict):
        options = {}
    options["baseURL"] = api_base
    options["timeout"] = int(timeout_ms)
    options["chunkTimeout"] = int(chunk_timeout_ms)
    provider["options"] = options
    models = provider.get("models")
    if not isinstance(models, dict):
        models = {}
    existing_model = models.get(model_name)
    if not isinstance(existing_model, dict):
        existing_model = {}
    existing_model["name"] = display_name
    models[model_name] = existing_model
    provider["models"] = models
    return provider


def _parse_model_catalog(raw: str) -> set[str]:
    return {item.strip() for item in str(raw or "").split(",") if item.strip()}


def _validate_opencode_model_catalog(
    *,
    model_name: str,
    provider_model_ids: list[str],
    available_models: set[str],
) -> list[str]:
    if not available_models:
        return []
    missing: list[str] = []
    for model_id in provider_model_ids:
        if model_id not in available_models and model_name not in available_models:
            missing.append(model_id)
    return missing


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _merge_fallback(value: Any, fallback_model: str) -> Any:
    if isinstance(value, list):
        merged = [fallback_model]
        merged.extend(str(item) for item in value if str(item) != fallback_model)
        return merged
    return fallback_model


def sync_opencode(args: argparse.Namespace) -> None:
    config_path = Path(args.config_file).expanduser()
    state_path = Path(args.state_file).expanduser()
    model_name = args.model_name
    api_base = args.api_base
    provider_model = f"llamacpp/{model_name}"
    full_provider_name = str(args.full_provider_name or "glyphos").strip() or "glyphos"
    fast_provider_name = str(args.fast_provider_name or "glyphos-fast").strip() or "glyphos-fast"
    gateway_api_base = str(args.gateway_api_base or api_base).strip()
    fast_api_base = str(args.fast_api_base or "").strip()
    compaction_reserved = int(args.compaction_reserved)
    if compaction_reserved < 1024:
        raise SystemExit("opencode compaction reserve must be at least 1024")
    generated_provider_model_ids: list[str] = []
    if gateway_api_base:
        generated_provider_model_ids.append(f"{full_provider_name}/{model_name}")
    if fast_api_base:
        generated_provider_model_ids.append(f"{fast_provider_name}/{model_name}")
    available_models = _parse_model_catalog(str(args.available_models or ""))
    missing_models = _validate_opencode_model_catalog(
        model_name=model_name,
        provider_model_ids=[provider_model],
        available_models=available_models,
    )
    if missing_models:
        available = ", ".join(sorted(available_models))
        missing = ", ".join(missing_models)
        raise SystemExit(f"missing opencode model ids: {missing}; available: {available}")

    config = load_json(config_path)
    providers = config.get("provider")
    if not isinstance(providers, dict):
        providers = {}
    providers = {
        str(name): provider
        for name, provider in providers.items()
        if not is_stale_local_opencode_provider(str(name), provider)
    }
    llamacpp = providers.get("llamacpp")
    if not isinstance(llamacpp, dict):
        llamacpp = {}
    llamacpp = _configure_opencode_provider(
        llamacpp,
        name="llama.cpp",
        api_base=api_base,
        timeout_ms=args.timeout_ms,
        chunk_timeout_ms=args.chunk_timeout_ms,
        model_name=model_name,
        display_name=args.display_name,
    )
    providers["llamacpp"] = llamacpp
    if gateway_api_base:
        full_provider = providers.get(full_provider_name)
        if not isinstance(full_provider, dict):
            full_provider = {}
        providers[full_provider_name] = _configure_opencode_provider(
            full_provider,
            name="GlyphOS full",
            api_base=gateway_api_base,
            timeout_ms=args.timeout_ms,
            chunk_timeout_ms=args.chunk_timeout_ms,
            model_name=model_name,
            display_name=f"{args.display_name} (GlyphOS full)",
        )
    if fast_api_base:
        fast_provider = providers.get(fast_provider_name)
        if not isinstance(fast_provider, dict):
            fast_provider = {}
        providers[fast_provider_name] = _configure_opencode_provider(
            fast_provider,
            name="GlyphOS fast",
            api_base=fast_api_base,
            timeout_ms=args.timeout_ms,
            chunk_timeout_ms=args.chunk_timeout_ms,
            model_name=model_name,
            display_name=f"{args.display_name} (GlyphOS fast)",
        )
    config["provider"] = providers
    config["model"] = provider_model
    config["small_model"] = provider_model
    compaction = config.get("compaction")
    if not isinstance(compaction, dict):
        compaction = {}
    compaction["auto"] = True
    compaction["prune"] = True
    compaction["reserved"] = compaction_reserved
    config["compaction"] = compaction
    write_json(config_path, config)

    state = load_json(state_path)
    recent = state.get("recent")
    if not isinstance(recent, list):
        recent = []
    normalized_recent: list[Any] = []
    normalized_recent.append({"id": provider_model, "provider": "llamacpp"})
    for item in recent:
        if isinstance(item, str):
            if item == provider_model:
                continue
            normalized_recent.append(item)
        elif isinstance(item, dict):
            if item.get("id") == provider_model:
                continue
            normalized_recent.append(item)
        else:
            normalized_recent.append(item)
    state["recent"] = normalized_recent
    # OpenCode state has used multiple shapes across releases. Keep the
    # compatibility fields aligned so an old UI cache cannot pin a stale model.
    state["providerID"] = "llamacpp"
    state["modelID"] = model_name
    state["id"] = provider_model
    state["provider"] = "llamacpp"
    diagnostics = state.get("llamaModelManager")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    diagnostics["opencodeSync"] = {
        "preset": args.preset,
        "routeMode": args.route_mode,
        "providerTimeoutMs": int(args.timeout_ms),
        "chunkTimeoutMs": int(args.chunk_timeout_ms),
        "compactionReserved": compaction_reserved,
        "contextWindow": int_or_zero(args.context_window),
        "glyphosProviders": {
            "full": f"{full_provider_name}/{model_name}" if gateway_api_base else "",
            "fast": f"{fast_provider_name}/{model_name}" if fast_api_base else "",
            "fullBaseURL": gateway_api_base,
            "fastBaseURL": fast_api_base,
        },
        "generatedProviderModelIds": generated_provider_model_ids,
        "modelCatalogValidated": bool(available_models),
        "modelCatalogMissing": missing_models,
        "sessionTimeoutObservedMs": 1800000,
        "timeoutSource": (
            "Observed opencode message/session timeout around 1800s is distinct from provider timeout; "
            "LMM sets provider timeout and compaction headroom, but opencode must preserve parent abort causes in its own runtime."
        ),
        "pendingToolAbortGuidance": (
            "If a pending write shows empty input/raw and Tool execution aborted, inspect the parent message error first."
        ),
    }
    state["llamaModelManager"] = diagnostics
    variant = state.get("variant")
    if not isinstance(variant, dict):
        variant = {}
    variant[provider_model] = "default"
    state["variant"] = variant
    write_json(state_path, state)


def sync_oh_my_openagent(args: argparse.Namespace) -> None:
    config_path = Path(args.config_file).expanduser()
    model_name = str(args.model_name).strip()
    full_provider_name = str(args.full_provider_name or "glyphos").strip() or "glyphos"
    fast_provider_name = str(args.fast_provider_name or "glyphos-fast").strip() or "glyphos-fast"
    full_model = f"{full_provider_name}/{model_name}"
    fast_model = f"{fast_provider_name}/{model_name}"
    available_models = _parse_model_catalog(str(args.available_models or ""))
    missing_models = _validate_opencode_model_catalog(
        model_name=model_name,
        provider_model_ids=[fast_model, full_model],
        available_models=available_models,
    )

    config = load_json(config_path)
    agents = config.get("agents")
    if not isinstance(agents, dict):
        agents = {}
    requested_agents = _csv_items(args.agents)
    updated_agents: list[str] = []
    for name in requested_agents:
        agent = agents.get(name)
        if not isinstance(agent, dict):
            continue
        agent["model"] = fast_model
        agent["fallback"] = _merge_fallback(agent.get("fallback"), full_model)
        updated_agents.append(name)

    categories = config.get("categories")
    updated_categories: list[str] = []
    if isinstance(categories, dict):
        for name in _csv_items(args.categories):
            value = categories.get(name)
            if isinstance(value, dict):
                value["model"] = fast_model
                value["fallback"] = _merge_fallback(value.get("fallback"), full_model)
                updated_categories.append(name)
            elif isinstance(value, str):
                categories[name] = fast_model
                updated_categories.append(name)

    diagnostics = config.get("llamaModelManager")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    diagnostics["openagentSync"] = {
        "fastModel": fast_model,
        "fullFallbackModel": full_model,
        "updatedAgents": updated_agents,
        "requestedAgents": requested_agents,
        "updatedCategories": updated_categories,
        "modelCatalogValidated": bool(available_models),
        "modelCatalogMissing": missing_models,
    }
    config["llamaModelManager"] = diagnostics
    write_json(config_path, config)


def sync_openclaw(args: argparse.Namespace) -> None:
    config_path = Path(args.config_file).expanduser()
    provider_model = f"llamacpp/{args.model_id}"
    config = load_json(config_path)

    agents = config.get("agents")
    if not isinstance(agents, dict):
        agents = {}
    defaults = agents.get("defaults")
    if not isinstance(defaults, dict):
        defaults = {}
    workspace = defaults.get("workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        workspace = str(config_path.parent / "workspace")
    defaults["workspace"] = workspace
    model_defaults = defaults.get("model")
    if not isinstance(model_defaults, dict):
        model_defaults = {}
    model_defaults["primary"] = provider_model
    defaults["model"] = model_defaults
    default_models = defaults.get("models")
    if not isinstance(default_models, dict):
        default_models = {}
    model_entry = default_models.get(provider_model)
    if not isinstance(model_entry, dict):
        model_entry = {}
    model_entry["alias"] = args.alias
    default_models[provider_model] = model_entry
    defaults["models"] = default_models
    agents["defaults"] = defaults
    config["agents"] = agents

    models = config.get("models")
    if not isinstance(models, dict):
        models = {}
    providers = models.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    llamacpp = providers.get("llamacpp")
    if not isinstance(llamacpp, dict):
        llamacpp = {}
    llamacpp["baseUrl"] = args.api_base
    llamacpp["apiKey"] = args.api_key
    llamacpp["api"] = "openai-completions"
    provider_models = llamacpp.get("models")
    if not isinstance(provider_models, list):
        provider_models = []
    retained = []
    for item in provider_models:
        if isinstance(item, dict) and item.get("id") != args.model_id:
            retained.append(item)
    retained.append(
        {
            "id": args.model_id,
            "name": args.display_name,
            "reasoning": False,
            "input": ["text"],
            "contextWindow": args.context_window,
            "maxTokens": args.max_tokens,
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        }
    )
    llamacpp["models"] = retained
    providers["llamacpp"] = llamacpp
    models["providers"] = providers
    config["models"] = models
    write_json(config_path, config)
    print(workspace)


def sync_claude(args: argparse.Namespace) -> None:
    settings_path = Path(args.settings_file).expanduser()
    settings = load_json(settings_path)
    env = settings.get("env")
    if not isinstance(env, dict):
        env = {}
    settings["model"] = args.model_id
    env["ANTHROPIC_BASE_URL"] = args.base_url
    env["ANTHROPIC_MODEL"] = args.model_id
    env["ANTHROPIC_CUSTOM_MODEL_OPTION"] = args.model_id
    if args.auth_token:
        env["ANTHROPIC_AUTH_TOKEN"] = args.auth_token
    if args.api_key:
        env["ANTHROPIC_API_KEY"] = args.api_key
    settings["env"] = env
    write_json(settings_path, settings)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync external client configs for llama-model-manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    op = sub.add_parser("opencode")
    op.add_argument("--config-file", required=True)
    op.add_argument("--state-file", required=True)
    op.add_argument("--model-name", required=True)
    op.add_argument("--display-name", required=True)
    op.add_argument("--api-base", required=True)
    op.add_argument("--timeout-ms", required=True, type=int)
    op.add_argument("--chunk-timeout-ms", required=True, type=int)
    op.add_argument("--compaction-reserved", default=16384, type=int)
    op.add_argument("--context-window", default=0, type=int)
    op.add_argument("--preset", default="balanced")
    op.add_argument("--route-mode", default="routed")
    op.add_argument("--gateway-api-base", default="")
    op.add_argument("--fast-api-base", default="")
    op.add_argument("--full-provider-name", default="glyphos")
    op.add_argument("--fast-provider-name", default="glyphos-fast")
    op.add_argument("--available-models", default="")
    op.set_defaults(func=sync_opencode)

    oma = sub.add_parser("oh-my-openagent")
    oma.add_argument("--config-file", required=True)
    oma.add_argument("--model-name", required=True)
    oma.add_argument("--full-provider-name", default="glyphos")
    oma.add_argument("--fast-provider-name", default="glyphos-fast")
    oma.add_argument(
        "--agents",
        default="sisyphus,prometheus,metis,atlas,sisyphus-junior",
    )
    oma.add_argument("--categories", default="")
    oma.add_argument("--available-models", default="")
    oma.set_defaults(func=sync_oh_my_openagent)

    oc = sub.add_parser("openclaw")
    oc.add_argument("--config-file", required=True)
    oc.add_argument("--model-id", required=True)
    oc.add_argument("--display-name", required=True)
    oc.add_argument("--alias", required=True)
    oc.add_argument("--api-base", required=True)
    oc.add_argument("--api-key", required=True)
    oc.add_argument("--context-window", required=True, type=int)
    oc.add_argument("--max-tokens", required=True, type=int)
    oc.set_defaults(func=sync_openclaw)

    gc = sub.add_parser("glyphos")
    gc.add_argument("--config-file", required=True)
    gc.add_argument("--model-name", required=True)
    gc.add_argument("--api-base", required=True)
    gc.add_argument("--timeout-seconds", required=True, type=int)
    gc.set_defaults(func=sync_glyphos)

    cc = sub.add_parser("claude")
    cc.add_argument("--settings-file", required=True)
    cc.add_argument("--model-id", required=True)
    cc.add_argument("--base-url", required=True)
    cc.add_argument("--auth-token", default="")
    cc.add_argument("--api-key", default="")
    cc.set_defaults(func=sync_claude)

    args = parser.parse_args()
    args.func(args)
    return 0


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if yaml is None:
        raise SystemExit("PyYAML is required for glyphos sync")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    if yaml is None:
        raise SystemExit("PyYAML is required for glyphos sync")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    temp_path.replace(path)


def sync_glyphos(args: argparse.Namespace) -> None:
    config_path = Path(args.config_file).expanduser()
    config = load_yaml(config_path)
    ai_compute = config.get("ai_compute")
    if not isinstance(ai_compute, dict):
        ai_compute = {}
    routing = ai_compute.get("routing")
    if not isinstance(routing, dict):
        routing = {}
    routing.setdefault("high_coherence_threshold", 0.8)
    routing.setdefault("low_coherence_threshold", 0.3)
    routing.setdefault("complex_actions", ["ANALYZE", "SYNTHESIZE", "PREDICT", "LEARN", "TEACH"])
    routing.pop("preferred_local_backend", None)
    ai_compute["routing"] = routing

    llamacpp = ai_compute.get("llamacpp")
    if not isinstance(llamacpp, dict):
        llamacpp = {}
    llamacpp["enabled"] = True
    llamacpp["url"] = args.api_base
    llamacpp["model"] = args.model_name
    llamacpp["timeout"] = int(args.timeout_seconds)
    ai_compute["llamacpp"] = llamacpp

    config["ai_compute"] = ai_compute
    write_yaml(config_path, config)


if __name__ == "__main__":
    raise SystemExit(main())

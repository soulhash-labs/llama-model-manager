#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


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


def sync_opencode(args: argparse.Namespace) -> None:
    config_path = Path(args.config_file).expanduser()
    state_path = Path(args.state_file).expanduser()
    model_name = args.model_name
    api_base = args.api_base
    provider_model = f"llamacpp/{model_name}"

    config = load_json(config_path)
    providers = config.get("provider")
    if not isinstance(providers, dict):
        providers = {}
    llamacpp = providers.get("llamacpp")
    if not isinstance(llamacpp, dict):
        llamacpp = {}
    llamacpp["npm"] = llamacpp.get("npm", "@ai-sdk/openai-compatible")
    llamacpp["name"] = llamacpp.get("name", "llama.cpp")
    options = llamacpp.get("options")
    if not isinstance(options, dict):
        options = {}
    options["baseURL"] = api_base
    options["timeout"] = int(args.timeout_ms)
    options["chunkTimeout"] = int(args.chunk_timeout_ms)
    llamacpp["options"] = options
    models = llamacpp.get("models")
    if not isinstance(models, dict):
        models = {}
    existing_model = models.get(model_name)
    if not isinstance(existing_model, dict):
        existing_model = {}
    existing_model["name"] = args.display_name
    models[model_name] = existing_model
    llamacpp["models"] = models
    providers["llamacpp"] = llamacpp
    config["provider"] = providers
    config["model"] = provider_model
    config["small_model"] = provider_model
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
    variant = state.get("variant")
    if not isinstance(variant, dict):
        variant = {}
    variant[provider_model] = "default"
    state["variant"] = variant
    write_json(state_path, state)


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
    op.set_defaults(func=sync_opencode)

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


if __name__ == "__main__":
    raise SystemExit(main())

"""Static guard tests: tripwire against accidental full-file rollback.

These are NOT deep functional tests. They assert that critical strings
still exist in their intended source-of-truth files after every change.

If one of these fails, the change may have clobbered a previously
integrated guard. Before re-adding the string, verify which layer owns it
(see AGENTS.md "No-Clobber / Source-of-Truth Rules").
"""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def test_web_app_static_serving_guard_present():
    source = read("web/app.py")
    assert "relative_to" in source
    assert "serve_static" in source


def test_web_app_allowed_host_guard_present():
    source = read("web/app.py")
    assert "parse_allowed_hosts" in source
    assert "_is_allowed_client" in source
    assert "client_not_allowed" in source


def test_web_app_js_context_budget_controls_present():
    source = read("web/app.js")
    for needle in [
        "LMM_MAX_CONTEXT_TOKENS",
        "LMM_CONTEXT_SAFETY_MARGIN",
        "LMM_CONTEXT_OVERFLOW_MODE",
        "LMM_AGENT_SOFT_CONTEXT_LIMIT",
        "containsContextFlag",
        "validateNoContextFlags",
        "positiveInt",
    ]:
        assert needle in source, f"{needle} not found in web/app.js"


def test_web_app_js_api_helper_robust():
    source = read("web/app.js")
    assert "response.text()" in source
    assert "options.headers" in source


def test_web_app_js_selector_helper_accepts_existing_nodes():
    source = read("web/app.js")
    assert 'typeof selector !== "string"' in source
    assert "return selector || null" in source


def test_gateway_context_budget_config_present():
    source = read("scripts/lmm_config.py")
    for needle in [
        "ContextBudgetConfig",
        "LMM_MAX_CONTEXT_TOKENS",
        "LMM_CONTEXT_SAFETY_MARGIN",
        "LMM_CONTEXT_OVERFLOW_MODE",
        "LMM_AGENT_SOFT_CONTEXT_LIMIT",
    ]:
        assert needle in source, f"{needle} not found in lmm_config.py"


def test_gateway_context_budget_rejection_present():
    source = read("scripts/gateway/handlers_openai.py")
    for needle in [
        "_estimate_tokens",
        "_check_context_budget",
        "Context too large",
    ]:
        assert needle in source, f"{needle} not found in handlers_openai.py"


def test_launcher_context_budget_integration_present():
    source = read("bin/llama-model")
    for needle in [
        "active_context_window",
        "LMM_MAX_CONTEXT_TOKENS",
        "validate_extra_args_no_core_launch_flags",
        "LLAMA_SERVER_EXTRA_ARGS",
    ]:
        assert needle in source, f"{needle} not found in bin/llama-model"


def test_launcher_extra_args_validation_present():
    source = read("bin/llama-model")
    for needle in [
        "Context-size flags are not allowed in extra_args",
        "split_shell_words",
    ]:
        assert needle in source, f"{needle} not found in bin/llama-model"


def test_gui_context_column_present():
    source = read("bin/llama-model-gui")
    assert "context" in source.lower()


def test_agents_md_no_clobber_rules_present():
    source = read("AGENTS.md")
    for needle in [
        "No-Clobber",
        "Source-of-Truth",
        "scripts/lmm_config.py",
        "web/app.js",
        "web/app.py",
        "bin/llama-model",
    ]:
        assert needle in source, f"{needle} not found in AGENTS.md"


def test_claude_md_no_clobber_rules_present():
    source = read("CLAUDE.md")
    for needle in [
        "No-Clobber",
        "Source-of-Truth",
        "scripts/lmm_config.py",
        "web/app.js",
        "web/app.py",
        "bin/llama-model",
    ]:
        assert needle in source, f"{needle} not found in CLAUDE.md"

from __future__ import annotations

import ast
import hashlib
import json
import re
from typing import Any

MAX_TOOL_CONTRACT_CHARS = 12_000
BASH_COMMAND_PREFIXES = (
    "awk ",
    "cat ",
    "cd ",
    "chmod ",
    "cp ",
    "curl ",
    "echo ",
    "env ",
    "find ",
    "git ",
    "grep ",
    "head ",
    "jq ",
    "ls",
    "mkdir ",
    "node ",
    "npm ",
    "python ",
    "python3 ",
    "pwd",
    "rg ",
    "sed ",
    "tail ",
    "tee ",
    "test ",
    "touch ",
    "wc ",
    "xargs ",
)


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _bounded_json(value: Any, *, max_chars: int = MAX_TOOL_CONTRACT_CHARS) -> str:
    text = compact_json(value)
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 32)] + "...[truncated]"


def _content_to_text(content: Any, *, provider: str) -> str:
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if part is None:
                continue
            if isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                text = part.get("text")
                if text is not None:
                    parts.append(str(text))
            elif provider == "anthropic" and isinstance(part, dict) and part.get("type") == "tool_result":
                tool_id = str(part.get("tool_use_id", "")).strip()
                tool_content = part.get("content", "")
                if isinstance(tool_content, list):
                    tool_text = "\n".join(
                        str(item.get("text", ""))
                        for item in tool_content
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                else:
                    tool_text = str(tool_content)
                parts.append(f"tool_result {tool_id}: {tool_text}".strip())
            elif provider == "anthropic" and isinstance(part, dict) and part.get("type") == "tool_use":
                parts.append("tool_use: " + _bounded_json(part))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(piece for piece in parts if piece)
    return str(content)


def messages_to_prompt(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    lines: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content_text = _content_to_text(item.get("content", ""), provider="openai")
        if item.get("tool_calls"):
            content_text = "\n".join(
                piece for piece in [content_text, "tool_calls: " + _bounded_json(item.get("tool_calls"))] if piece
            )
        if item.get("function_call"):
            content_text = "\n".join(
                piece for piece in [content_text, "function_call: " + _bounded_json(item.get("function_call"))] if piece
            )
        if content_text.strip():
            lines.append(f"{role}: {content_text.strip()}")
    return "\n\n".join(lines)


def anthropic_messages_to_text(messages: Any, system: Any = None) -> str:
    lines: list[str] = []

    if system is not None:
        if isinstance(system, str):
            system_text = system.strip()
        elif isinstance(system, list):
            parts: list[str] = []
            for item in system:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            system_text = "\n".join(part for part in parts if part).strip()
        else:
            system_text = str(system).strip()
        if system_text:
            lines.append(f"system: {system_text}")

    if not isinstance(messages, list):
        return "\n\n".join(lines)

    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content_text = _content_to_text(item.get("content", ""), provider="anthropic")
        if content_text.strip():
            lines.append(f"{role}: {content_text.strip()}")
    return "\n\n".join(lines)


def format_tool_contract(payload: dict[str, Any], *, protocol: str) -> str:
    """
    Format tool/function declarations for model-visible routing prompts.

    This does not execute tools. It preserves harness-supplied contracts so the
    routed model can decide whether a provider-shaped tool call is appropriate.
    """
    selected: dict[str, Any] = {}
    for key in ("tools", "tool_choice", "functions", "function_call", "parallel_tool_calls"):
        value = payload.get(key)
        if value is not None:
            selected[key] = value

    if not selected:
        return ""

    body = {
        "protocol": protocol,
        "contract": selected,
        "instructions": (
            "Use these tools/functions only when the user request requires them. "
            "Do not invent undeclared tools. If a tool call is required, return a valid "
            "tool-call request for the declared provider shape with JSON arguments. "
            "If you decide to use the task tool, you must emit a structured tool invocation. "
            "Never print task(...) as plain text. Do not explain the tool call. "
            "If you decide to use the Bash tool, you must emit a structured tool invocation. "
            "Never print shell commands as plain text. Do not explain the shell command. "
            "Never print tool_use: blocks or raw tool_use JSON as plain text. "
            "Do not wrap tool calls in markdown. If a tool is needed, invoke it directly."
        ),
    }
    return "[TOOL_CONTRACT]\n" + _bounded_json(body)


def append_tool_contract_to_prompt(prompt: str, payload: dict[str, Any], *, protocol: str) -> str:
    contract = format_tool_contract(payload, protocol=protocol)
    if not contract:
        return prompt
    if not prompt.strip():
        return contract
    return f"{prompt.rstrip()}\n\n{contract}"


def _declared_tool_names(payload: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    tools = payload.get("tools")
    if isinstance(tools, list):
        for item in tools:
            if not isinstance(item, dict):
                continue
            function = item.get("function")
            if isinstance(function, dict) and function.get("name"):
                names.add(str(function["name"]))
            elif item.get("name"):
                names.add(str(item["name"]))

    functions = payload.get("functions")
    if isinstance(functions, list):
        for item in functions:
            if isinstance(item, dict) and item.get("name"):
                names.add(str(item["name"]))
    return names


def _parse_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_embedded_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract_balanced_object_after(text: str, marker: str) -> str | None:
    start_marker = text.find(marker)
    if start_marker < 0:
        return None
    start = text.find("{", start_marker + len(marker))
    if start < 0:
        return None
    depth = 0
    quote: str | None = None
    escape = False
    for index, char in enumerate(text[start:], start=start):
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _extract_simple_json_field(text: str, key: str) -> Any:
    string_match = re.search(rf'"{re.escape(key)}"\s*:\s*"(?P<value>(?:\\.|[^"\\])*)"', text, flags=re.DOTALL)
    if string_match:
        return string_match.group("value").encode("utf-8").decode("unicode_escape")

    array_match = re.search(rf'"{re.escape(key)}"\s*:\s*(?P<value>\[[^\]]*\])', text, flags=re.DOTALL)
    if array_match:
        try:
            return json.loads(array_match.group("value"))
        except json.JSONDecodeError:
            return None
    return None


def _extract_balanced_call(text: str, name: str) -> str | None:
    stripped = text.strip()
    match = re.search(rf"\b{re.escape(name)}\s*\(", stripped)
    if not match:
        return None
    start = match.start()
    depth = 0
    quote: str | None = None
    escape = False
    for index, char in enumerate(stripped[start:], start=start):
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]
    return None


def _pythonish_call_to_tool_call(text: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    declared_names = _declared_tool_names(payload)
    if "task" not in declared_names:
        return None
    call_text = _extract_balanced_call(text, "task")
    if not call_text:
        return None
    normalized = re.sub(r"\btrue\b", "True", call_text)
    normalized = re.sub(r"\bfalse\b", "False", normalized)
    normalized = re.sub(r"\bnull\b", "None", normalized)
    try:
        parsed = ast.parse(normalized, mode="eval")
    except SyntaxError:
        return None
    call = parsed.body
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != "task":
        return None
    arguments: dict[str, Any] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            return None
        try:
            arguments[keyword.arg] = ast.literal_eval(keyword.value)
        except (ValueError, TypeError):
            return None
    return {
        "id": "call_" + hashlib.sha1(f"task:{compact_json(arguments)}".encode()).hexdigest()[:12],
        "name": "task",
        "arguments": arguments,
        "mode": "textual_pseudo_call",
    }


def _extract_fenced_shell_command(text: str) -> str | None:
    match = re.search(r"```(?:bash|sh|shell)?\s*\n(?P<body>.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    command = match.group("body").strip()
    return command or None


def _extract_bash_xml_command(text: str) -> str | None:
    match = re.search(r"<\s*Bash\b(?P<attrs>[^>]*)/?>", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    attrs = match.group("attrs")
    command_start = attrs.find('command="')
    if command_start >= 0:
        rest = attrs[command_start + len('command="') :]
        marker_positions = [
            position for position in (rest.find('" timeout='), rest.find('" description=')) if position >= 0
        ]
        if marker_positions:
            command = rest[: min(marker_positions)].strip()
        else:
            command = rest.rsplit('"', 1)[0].strip()
    else:
        command_match = re.search(r"\bcommand\s*=\s*'(?P<command>.*)'\s*/?\s*$", attrs, flags=re.DOTALL)
        if not command_match:
            return None
        command = command_match.group("command").strip()
    return command or None


def _extract_tool_code_command(text: str) -> str | None:
    match = re.search(r"<\s*tool_code\b(?P<body>.*?)</\s*tool_code\s*>", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    body = match.group("body")
    code_match = re.search(r"\bcode\s*=\s*\"(?P<command>.*?)\"", body, flags=re.DOTALL)
    if code_match:
        command = code_match.group("command").strip()
        return command or None
    lines = [line.strip() for line in body.splitlines()]
    command_lines = [line for line in lines if _looks_like_shell_command(line)]
    return "\n".join(command_lines) or None


def _extract_bash_json_command(text: str) -> str | None:
    parsed = _parse_json_object(text) or _parse_embedded_json_object(text)
    if not parsed:
        return None
    name = str(
        parsed.get("name")
        or parsed.get("toolName")
        or parsed.get("tool_name")
        or parsed.get("tool")
        or parsed.get("tool_name")
        or ""
    )
    if isinstance(parsed.get("arguments"), dict):
        arguments = parsed["arguments"]
    elif isinstance(parsed.get("input"), dict):
        arguments = parsed["input"]
    elif isinstance(parsed.get("tool_input"), dict):
        arguments = parsed["tool_input"]
    else:
        arguments = parsed
    command = arguments.get("command") if isinstance(arguments, dict) else None
    if isinstance(command, str) and command.strip() and (name.lower() == "bash" or "<tool_call" in text):
        return command.strip()
    return None


def _extract_command_assignment(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("command="):
        return None
    command = stripped[len("command=") :].strip()
    if len(command) >= 2 and command[0] in {"'", '"'}:
        command = command[1:]
    if command.endswith(("'", '"')):
        command = command[:-1]
    return command.strip() or None


def _looks_like_shell_command(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("{", "[")):
        return False
    if stripped.startswith(("#", "$", ">", "- ", "* ")):
        stripped = stripped[1:].strip()
    if stripped.startswith("command="):
        return True
    if not stripped or stripped.endswith(":"):
        return False
    if stripped.startswith("<"):
        return False
    lowered = stripped.lower()
    if lowered.startswith(BASH_COMMAND_PREFIXES):
        return True
    return any(token in stripped for token in (" | ", " && ", " || ", " 2>/", " >/"))


def _shell_text_to_tool_call(text: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    declared_names = _declared_tool_names(payload)
    bash_name = next((name for name in declared_names if name.lower() == "bash"), None)
    if not bash_name:
        return None

    command = _extract_fenced_shell_command(text)
    if command is None:
        command = _extract_bash_json_command(text)
    if command is None:
        command = _extract_bash_xml_command(text)
    if command is None:
        command = _extract_tool_code_command(text)
    if command is None:
        commands = []
        for line in text.splitlines():
            if not _looks_like_shell_command(line):
                continue
            command_assignment = _extract_command_assignment(line)
            commands.append(command_assignment or line.strip().lstrip("$> ").strip())
        command = "\n".join(command for command in commands if command)
    if not command:
        return None

    arguments = {"command": command}
    return {
        "id": "call_" + hashlib.sha1(f"{bash_name}:{compact_json(arguments)}".encode()).hexdigest()[:12],
        "name": bash_name,
        "arguments": arguments,
        "mode": "textual_pseudo_call",
    }


def _function_json_text_to_tool_call(text: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    declared_names = _declared_tool_names(payload)
    if not declared_names:
        return None

    parsed = _parse_json_object(text) or _parse_embedded_json_object(text)
    candidate: dict[str, Any] | None = None
    if isinstance(parsed, dict) and parsed.get("type") == "function" and isinstance(parsed.get("function"), dict):
        candidate = parsed["function"]

    if candidate is None:
        if not re.search(r'"type"\s*:\s*"function"', text):
            return None
        name_match = re.search(r'"name"\s*:\s*"(?P<name>[^"]+)"', text)
        if not name_match:
            return None
        name = name_match.group("name")
        if name not in declared_names:
            return None

        arguments: dict[str, Any] = {}
        raw_arguments = _extract_balanced_object_after(text, '"arguments"')
        if raw_arguments:
            parsed_arguments = _parse_json_object(raw_arguments)
            if isinstance(parsed_arguments, dict):
                arguments.update(parsed_arguments)

        # Some local models emit `"arguments": {"pattern": "..."} "lang": "json"`
        # with the remaining intended arguments outside the arguments object.
        for key in ("task_id", "subagent_type", "description", "prompt", "pattern", "lang", "globs"):
            if key in arguments:
                continue
            value = _extract_simple_json_field(text, key)
            if value is not None:
                arguments[key] = value

        if not arguments:
            return None
    else:
        name = str(candidate.get("name", ""))
        if name not in declared_names:
            return None
        arguments = candidate.get("arguments", {})
        if isinstance(arguments, str):
            parsed_arguments = _parse_json_object(arguments)
            arguments = parsed_arguments if parsed_arguments is not None else {"value": arguments}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}

    return {
        "id": "call_" + hashlib.sha1(f"{name}:{compact_json(arguments)}".encode()).hexdigest()[:12],
        "name": name,
        "arguments": arguments,
        "mode": "textual_pseudo_call",
    }


def _anthropic_tool_use_text_to_tool_call(text: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    declared_names = _declared_tool_names(payload)
    if not declared_names:
        return None

    parsed = _parse_json_object(text) or _parse_embedded_json_object(text)
    if not isinstance(parsed, dict):
        return None

    # Handle {"tool_use": {"type": "tool_use", "name": "Bash", "command": "..."}}
    # where the outer key is "tool_use" instead of a top-level "type" field.
    if (
        "tool_use" in parsed
        and isinstance(parsed["tool_use"], dict)
        and str(parsed.get("type", "")).replace("-", "_") != "tool_use"
    ):
        parsed = parsed["tool_use"]

    if str(parsed.get("type", "")).replace("-", "_") != "tool_use":
        return None

    name = str(parsed.get("name", ""))
    if name not in declared_names:
        return None

    arguments = parsed.get("input", parsed.get("arguments", {}))
    # Some local models emit tool arguments as flat keys (e.g. "command": "...")
    # instead of nested under "input": {"command": "..."}. Wrap them.
    if not isinstance(arguments, dict) or not arguments:
        command = parsed.get("command")
        if command is not None:
            arguments = {"command": str(command)}
    if isinstance(arguments, str):
        parsed_arguments = _parse_json_object(arguments)
        arguments = parsed_arguments if parsed_arguments is not None else {"value": arguments}
    if not isinstance(arguments, dict):
        arguments = {"value": arguments}

    return {
        "id": str(
            parsed.get("id") or "call_" + hashlib.sha1(f"{name}:{compact_json(arguments)}".encode()).hexdigest()[:12]
        ),
        "name": name,
        "arguments": arguments,
        "mode": "textual_pseudo_call",
    }


def _normalize_tool_call(text: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    declared_names = _declared_tool_names(payload)
    if not declared_names:
        return None

    anthropic_tool_use_call = _anthropic_tool_use_text_to_tool_call(text, payload)
    if anthropic_tool_use_call:
        return anthropic_tool_use_call

    function_json_call = _function_json_text_to_tool_call(text, payload)
    if function_json_call:
        return function_json_call

    pseudo_call = _pythonish_call_to_tool_call(text, payload)
    if pseudo_call:
        return pseudo_call

    shell_call = _shell_text_to_tool_call(text, payload)
    if shell_call:
        return shell_call

    parsed = _parse_json_object(text) or _parse_embedded_json_object(text)
    if not parsed:
        return None

    candidate: Any = None
    if isinstance(parsed.get("tool_call"), dict):
        candidate = parsed["tool_call"]
    elif isinstance(parsed.get("tool_calls"), list) and parsed["tool_calls"]:
        candidate = parsed["tool_calls"][0]
    elif isinstance(parsed.get("tool_use"), dict):
        candidate = parsed["tool_use"]
    elif parsed.get("type") == "tool_use":
        candidate = parsed

    if not isinstance(candidate, dict):
        return None

    function = candidate.get("function")
    if isinstance(function, dict):
        name = str(function.get("name", ""))
        arguments = function.get("arguments", {})
    else:
        name = str(candidate.get("name", ""))
        arguments = candidate.get("arguments", candidate.get("input", {}))

    if name not in declared_names:
        return None

    if isinstance(arguments, str):
        parsed_arguments = _parse_json_object(arguments)
        arguments = parsed_arguments if parsed_arguments is not None else {"value": arguments}
    if not isinstance(arguments, dict):
        arguments = {"value": arguments}

    return {
        "id": str(
            candidate.get("id") or "call_" + hashlib.sha1(f"{name}:{compact_json(arguments)}".encode()).hexdigest()[:12]
        ),
        "name": name,
        "arguments": arguments,
        "mode": "structured",
    }


def classify_tool_invocation(text: str, payload: dict[str, Any]) -> dict[str, Any]:
    tool_call = _normalize_tool_call(text, payload)
    if tool_call:
        mode = str(tool_call.get("mode", "structured"))
        repaired = mode == "textual_pseudo_call"
        return {
            "tool_invocation_mode": mode,
            "tool_name": str(tool_call.get("name", "")),
            "repair_attempted": repaired,
            "repair_succeeded": repaired,
        }

    textual_task_seen = "task" in _declared_tool_names(payload) and _extract_balanced_call(text, "task") is not None
    if textual_task_seen:
        return {
            "tool_invocation_mode": "textual_pseudo_call",
            "tool_name": "task",
            "repair_attempted": True,
            "repair_succeeded": False,
        }

    return {
        "tool_invocation_mode": "none",
        "tool_name": "",
        "repair_attempted": False,
        "repair_succeeded": False,
    }


def apply_openai_tool_call_response(response: dict[str, Any], text: str, payload: dict[str, Any]) -> dict[str, Any]:
    tool_call = _normalize_tool_call(text, payload)
    if not tool_call:
        return response

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return response

    choice = choices[0]
    if not isinstance(choice, dict):
        return response

    choice["finish_reason"] = "tool_calls"
    choice["message"] = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": tool_call["id"],
                "type": "function",
                "function": {
                    "name": tool_call["name"],
                    "arguments": compact_json(tool_call["arguments"]),
                },
            }
        ],
    }
    return response


def apply_anthropic_tool_use_response(response: dict[str, Any], text: str, payload: dict[str, Any]) -> dict[str, Any]:
    tool_call = _normalize_tool_call(text, payload)
    if not tool_call:
        return response

    response["stop_reason"] = "tool_use"
    response["content"] = [
        {
            "type": "tool_use",
            "id": tool_call["id"].replace("call_", "toolu_"),
            "name": tool_call["name"],
            "input": tool_call["arguments"],
        }
    ]
    return response


def message_summary(messages: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "count": 0,
        "roles": {},
        "chars": 0,
    }
    if not isinstance(messages, list):
        return summary

    roles: dict[str, int] = {}
    chars = 0
    canonical: list[dict[str, Any]] = []

    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content = item.get("content", "")
        content_chars = len(compact_json(content) if not isinstance(content, str) else content)
        roles[role] = roles.get(role, 0) + 1
        chars += content_chars
        canonical.append({"role": role, "chars": content_chars})

    summary.update(
        {
            "count": len(canonical),
            "roles": roles,
            "chars": chars,
        }
    )
    return summary


def anthropic_messages_summary(messages: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "count": 0,
        "roles": {},
        "chars": 0,
    }
    if not isinstance(messages, list):
        return summary

    roles: dict[str, int] = {}
    chars = 0
    canonical: list[dict[str, Any]] = []

    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content = item.get("content", "")
        if isinstance(content, list):
            content_chars = sum(
                len(str(part.get("text", "")))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            content_chars = len(str(content))
        roles[role] = roles.get(role, 0) + 1
        chars += content_chars
        canonical.append({"role": role, "chars": content_chars})

    summary.update(
        {
            "count": len(canonical),
            "roles": roles,
            "chars": chars,
        }
    )
    return summary


def build_anthropic_response(
    text: str,
    model: str,
    started: float,
    routed: dict[str, Any],
    pipeline: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": f"msg_{int(started * 1000)}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": model,
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 0,
            "output_tokens": max(1, len(text.split())),
        },
        "lmm": {
            "route_target": routed.get("target", "unknown"),
            "route_reason_code": routed.get("reason_code", "unknown"),
            "context_status": pipeline.get("context_status", "unknown"),
            "context_used": bool(pipeline.get("context_used")),
            "glyph_encoding_status": pipeline.get("glyph_encoding_status", "skipped"),
            "latency_ms": routed.get("latency_ms", 0),
        },
    }


__all__ = [
    "compact_json",
    "messages_to_prompt",
    "anthropic_messages_to_text",
    "format_tool_contract",
    "append_tool_contract_to_prompt",
    "classify_tool_invocation",
    "apply_openai_tool_call_response",
    "apply_anthropic_tool_use_response",
    "message_summary",
    "anthropic_messages_summary",
    "build_anthropic_response",
]

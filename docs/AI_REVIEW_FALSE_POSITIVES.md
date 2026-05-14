# AI Review False Positives — LMM Gateway

Date: 2026-05-13

## Context

After the LlamaCppClient single-source-of-truth refactor and the Anthropic `tool_use` protocol fix, a follow-up AI review reported several suspected issues. Manual verification showed most were false positives or intentional design choices.

## Verified Non-Issues

### 1. Circular Import Risk

False.

Current dependency direction:

```text
api_client.py -> client_base.py
api_client.py -> llamacpp_client.py
llamacpp_client.py -> client_base.py
client_base.py -> no project imports
```

`client_base.py` was created specifically to break the original cycle.

### 2. Duplicate LlamaCppClient

False.

`api_client.py` no longer defines `class LlamaCppClient`. The canonical implementation is:

```text
llamacpp_client.py
```

### 3. Missing Exports

Mostly false.

`LlamaCppClient` remains available through the public API. `OllamaClient` compatibility is handled via the existing deprecated `__getattr__` path. There is no `Router` class; the router class is `AdaptiveRouter`.

### 4. Hardcoded Llama.cpp Backend Port

Not a bug.

`http://127.0.0.1:8081` is the stable default llama.cpp backend endpoint. Gateway ports are separately environment-configurable.

### 5. is_available Error Handling

Adequate.

`is_available()` catches connection and HTTP failures and returns `False`, which is appropriate for a health-check method.

### 6. Timeout Differences

Intentional.

Different providers have different expected latency profiles:

| Client         | Timeout | Reason                            |
| -------------- | ------: | --------------------------------- |
| BaseChatClient |     30s | Generic default                   |
| LlamaCppClient |    300s | Local model inference can be slow |
| OllamaClient   |     60s | Medium-latency local backend      |
| Cloud clients  |     30s | Expected faster API responses     |

### 7. Type Hints

Not a bug.

Public function signatures are typed. Internal variable annotations are not required unless a type checker flags them.

### 8. Script Name

Not actionable.

`render-sovereignty-bridge-clip.py` is a standalone visual asset render script. The name is intentional.

## Lesson

AI review output must be verified against actual code and tests before action. Prefer dependency graphs, grep/static guards, and fresh-process import tests over plausibility.

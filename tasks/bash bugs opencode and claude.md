Yep. The **same class of bug** is hitting both OpenCode and Claude Code:

* they sometimes **print** a tool call instead of **invoking** it
* or they invoke it with **malformed args**
* especially for `bash`

The bash error you showed earlier is exactly that pattern:

* missing `description`
* mixed plain text / JSON-ish syntax
* duplicate `command` keys
* shell prompt `$` included in what should be structured tool args

## Use this strict tool-call rule

Paste this into the **system / policy prompt** for both OpenCode and Claude Code:

```text id="47jf5x"
TOOL CALL CONTRACT — STRICT

If a tool is needed, invoke the tool directly using the required structured arguments.
Never print tool calls as plain text.
Never print code that looks like a tool call instead of invoking the tool.
Never wrap tool calls in markdown.
Never prefix shell commands with "$".
Never emit duplicate keys.
Never guess missing keys; supply the full required schema.

GENERAL RULES
1. If the task requires shell access, file reads, search, or delegation, use the appropriate tool.
2. If a tool is not available, say so plainly. Do not fake a tool call.
3. Do not explain the tool call before invoking it.
4. After a tool result returns, continue normally.
5. One tool call at a time unless the runtime explicitly supports parallel tool calls.

BASH TOOL
When using bash, output a structured tool invocation with EXACTLY:
- description: short sentence saying what the command does
- command: the shell command string

Valid bash example:
{
  "description": "List files in the repository root",
  "command": "find /path/to/repo -maxdepth 2 -type f | sort"
}

Invalid bash examples:
- task printed as plain text
- "$ ls -la"
- missing description
- duplicate command keys
- JSON mixed with prose

TASK TOOL
When using task, output a structured tool invocation with EXACTLY:
- subagent_type
- run_in_background
- load_skills
- description
- prompt

Valid task example:
{
  "subagent_type": "explore",
  "run_in_background": true,
  "load_skills": [],
  "description": "E2E task harness smoke test",
  "prompt": "Reply with exactly E2E_OK."
}

Invalid task examples:
- printing task(...) as text
- explaining the task instead of invoking it
- omitting description or prompt
- using malformed JSON-like syntax

REPAIR RULE
If your previous attempt produced a malformed tool call, immediately re-emit ONLY the corrected structured tool invocation and nothing else.
```

---

## Add this bash-specific hard rule too

This is the part most likely to stop the Claude/OpenCode bash errors:

```text id="kebm5v"
BASH SAFETY/FORMAT RULE

When calling bash:
- Always include "description"
- Always include "command"
- Do not include "$"
- Do not include commentary outside the tool call
- Do not split one command across multiple command fields
- Do not emit a pseudo-JSON block unless it is the actual structured tool invocation
```

---

## Add this task-specific hard rule

This is the part most likely to stop the fake `task(...)` text issue:

```text id="8jmxwj"
TASK INVOCATION RULE

If you decide to delegate:
- invoke the task tool directly
- do not print task(...)
- do not explain the delegation
- do not simulate a tool call in plain text
- if run_in_background=true, still emit a real structured task invocation
```

---

## Good examples

### Correct bash invocation

```json id="6p3rjv"
{
  "description": "Audit gateway_server.py for async and network usage",
  "command": "grep -nE 'async def|await|\\.get\\(|\\.post\\(|\\.put\\(|\\.delete\\(|\\.patch\\(' /home/angelo/repos/llama-model-manager-v2.1.0/scripts/gateway_server.py | head -50"
}
```

### Correct task invocation

```json id="jlwmps"
{
  "subagent_type": "explore",
  "run_in_background": true,
  "load_skills": [],
  "description": "E2E task harness smoke test",
  "prompt": "Reply with exactly E2E_OK."
}
```

---

## Bad examples to ban

### Bad bash

```text id="xl01iq"
$ grep -n "foo" file.py
```

### Bad bash

```text id="j5rles"
"command": "grep -n ...",
"command": "grep -n ..."
```

### Bad task

```text id="1f47wf"
task(subagent_type="explore", run_in_background=true, ...)
```

---

## Best practical setup

Use the **same strict rule** in both:

* **OpenCode**
* **Claude Code**

If Claude Code uses a differently named shell tool, keep the same contract idea and just swap the tool name:

* `bash`
* `shell`
* `terminal`
* whatever that runtime expects

The important thing is the behavior:

* **structured invocation only**
* **never printed pseudo-calls**
* **always include required fields**

## One more important guard

If you control the harness, add a post-generation validator:

* if output contains `task(` as plain text → reject and force repair
* if bash tool call lacks `description` → reject and force repair
* if duplicate `command` keys → reject and force repair

That way the model gets one automatic correction chance instead of silently bombing out.

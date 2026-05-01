---
phase: 05-devex
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .pre-commit-config.yaml
  - pyproject.toml
autonomous: true
requirements: [DEVEX-01]
user_setup:
  - service: pre-commit
    why: "Linting hooks"
    dashboard_config:
      - task: "Run 'pre-commit install' to enable git hooks"
        location: "Terminal in repo root"

must_haves:
  truths:
    - "pre-commit runs ruff on all Python files before commit"
    - "ruff catches E, W, F, I, B, C4, UP violations"
    - "pre-commit config includes trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, detect-private-key"
    - "ruff auto-fixes on commit for fixable rules (I, F401)"
  artifacts:
    - path: ".pre-commit-config.yaml"
      provides: "Pre-commit hook configuration"
      contains: "ruff"
    - path: "pyproject.toml"
      provides: "Ruff configuration"
      contains: "[tool.ruff]"
  key_links:
    - from: ".pre-commit-config.yaml"
      to: "pyproject.toml"
      via: "ruff reads [tool.ruff] config"
      pattern: "args:.*pyproject.toml"
---

<objective>
Add pre-commit hooks and Ruff linting configuration to catch bugs and enforce consistent style.

Purpose: LMM has no linting. Ruff catches real bugs (flake8-bugbear) and enforces style without manual effort.
Output: .pre-commit-config.yaml + pyproject.toml with ruff config
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/codebase/CONVENTIONS.md
@docs/ACE-PATTERN-TRANSFER-ANALYSIS.md (Pattern 11: Pre-commit + Ruff)
@/opt/ace/.pre-commit-config.yaml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create pyproject.toml with Ruff configuration</name>
  <files>pyproject.toml</files>
  <action>
Create pyproject.toml at repo root with:

```toml
[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "B",    # flake8-bugbear
    "C4",   # flake8-comprehensions
    "UP",   # pyupgrade
]
ignore = [
    "E501", # line-length handled by formatter
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]  # allow assert in tests
"web/app.py" = ["E501"]  # existing long lines
"bin/**" = ["E501"]  # bash files not checked

[tool.ruff.lint.isort]
known-first-party = ["lmm_config", "lmm_errors", "lmm_storage", "lmm_types", "lmm_health", "lmm_receipts", "lmm_notifications", "lmm_providers"]
```

Do NOT add [project] section — LMM is not a Python package (it's a bash/Python hybrid). The pyproject.toml exists solely for tool config.

After creating, verify ruff can parse it: `python3 -m ruff check --select E scripts/lmm_config.py` (if ruff is installed; skip if not).
  </action>
  <verify>
    <automated>python3 -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
assert 'tool' in data
assert 'ruff' in data['tool']
assert 'line-length' in data['tool']['ruff']
lint = data['tool']['ruff']['lint']
assert 'E' in lint['select']
assert 'B' in lint['select']
assert 'C4' in lint['select']
assert 'UP' in lint['select']
print('pyproject.toml ruff config OK')
"</automated>
  </verify>
  <done>pyproject.toml has valid TOML with ruff config, selects E/W/F/I/B/C4/UP rules, ignores E501 for line length, allows assert in tests</done>
</task>

<task type="auto">
  <name>Task 2: Create .pre-commit-config.yaml</name>
  <files>.pre-commit-config.yaml</files>
  <action>
Create .pre-commit-config.yaml at repo root with:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.9
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
        types_or: [python, pyi]
      - id: ruff-format
        types_or: [python, pyi]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: detect-private-key
      - id: check-merge-conflict

  - repo: meta
    hooks:
      - id: check-hooks-apply
      - id: check-useless-excludes
```

Key design choices:
- `--fix` on ruff: auto-fixes fixable rules (import sorting, unused imports) on commit
- `--exit-non-zero-on-fix`: fails the commit if ruff fixed something (forces re-commit with fixes)
- `check-yaml` and `check-toml`: validates config files (including the new pyproject.toml)
- `detect-private-key`: catches accidentally committed secrets
- `check-merge-conflict`: catches leftover merge conflict markers
- Version pins are explicit (no autoupdate in this pass — add later)

Exclude patterns for things that shouldn't be linted:
- `integrations/public-glyphos-ai-compute/` — vendored dependency
- `web/node_modules/` — if exists
  </action>
  <verify>
    <automated>python3 -c "
import yaml
with open('.pre-commit-config.yaml') as f:
    data = yaml.safe_load(f)
assert 'repos' in data
repos = {r['repo']: r for r in data['repos']}
assert 'https://github.com/astral-sh/ruff-pre-commit' in repos
assert 'https://github.com/pre-commit/pre-commit-hooks' in repos
assert 'meta' in repos
# Check ruff hook has --fix
ruff_hooks = [h for h in repos['https://github.com/astral-sh/ruff-pre-commit']['hooks'] if h['id'] == 'ruff']
assert len(ruff_hooks) == 1
assert '--fix' in ruff_hooks[0]['args']
print('.pre-commit-config.yaml OK')
"</automated>
  </verify>
  <done>.pre-commit-config.yaml has ruff + pre-commit-hooks repos, ruff runs with --fix, all standard hooks present</done>
</task>

<task type="auto">
  <name>Task 3: Verify linting works on existing code</name>
  <files>pyproject.toml, .pre-commit-config.yaml</files>
  <action>
Run ruff against the new lmm_* modules to verify they pass linting. This is a smoke test — don't fix all repo violations (that's a separate effort).

1. Try `python3 -m ruff check scripts/lmm_config.py scripts/lmm_errors.py scripts/lmm_storage.py scripts/lmm_types.py scripts/lmm_health.py scripts/lmm_receipts.py scripts/lmm_notifications.py scripts/lmm_providers.py`
2. If ruff is not installed, skip this task (it will be caught by pre-commit when installed)
3. If ruff finds violations in the new modules, fix them — these are our modules and should be clean.
4. Do NOT fix violations in existing files (web/app.py, bin/llama-model, etc.) — that's out of scope.

If ruff is installed and finds issues, fix them. If ruff is not installed, mark this task as "skipped — ruff not available, will be caught by pre-commit".
  </action>
  <verify>
    <automated>python3 -c "
import subprocess, sys
result = subprocess.run([sys.executable, '-m', 'ruff', 'check', '--select', 'F', 'scripts/lmm_config.py'], capture_output=True, text=True)
# If ruff is installed, check for no critical errors (F rules only)
if result.returncode == 0:
    print('ruff check OK')
else:
    # ruff may not be installed
    if 'command not found' in result.stderr or 'No module named ruff' in result.stderr:
        print('ruff not installed — skipped, pre-commit will catch issues')
    else:
        print(f'ruff found issues: {result.stdout}')
        sys.exit(1)
"</automated>
  </verify>
  <done>New lmm_* modules pass ruff F (pyflakes) rules, or ruff is not installed (will be caught by pre-commit)</done>
</task>

</tasks>

<verification>
- pyproject.toml has valid TOML with ruff configuration
- .pre-commit-config.yaml has ruff + standard hooks
- New lmm_* modules pass linting (or ruff not installed)
- pre-commit install enables hooks locally
</verification>

<success_criteria>
- pyproject.toml ruff config selects E/W/F/I/B/C4/UP rules
- .pre-commit-config.yaml has ruff with --fix, plus standard hooks
- pre-commit install works without errors
- New lmm_* modules are lint-clean (no F, B, or I violations)
</success_criteria>

<output>
After completion, create `.planning/phases/05-devex/05-devex-01-SUMMARY.md`
</output>

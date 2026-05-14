Strictly follow the rules in ./AGENTS.md.

## Context Budget / File Reading Rules

Do not read whole files by default.

Before reading a file:
1. Use `rg`, `grep`, or symbol search to locate relevant functions/classes.
2. Read only the relevant function, class, or approximately 120 lines around the match.
3. If more context is needed, request another narrow range.
4. Avoid reading generated files, lockfiles, build artifacts, large logs, `.old` files, cache files, and vendored files unless explicitly required.
5. When a file has already been read, do not reread it fully. Use targeted search or refer to the previous summary.
6. Keep total working context below 60k tokens unless explicitly instructed otherwise.
7. If context is getting large, compact the current findings into a short summary before continuing.
8. Only read an entire file if you have enough context available and are explicitly requested to do so.

Preferred workflow:
- `rg "pattern" path/`
- inspect matched line numbers
- read only the smallest useful region
- patch surgically
- run focused tests

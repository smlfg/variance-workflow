#!/usr/bin/env bash
# Adapter: OpenCode (primary, tested). Free models (opencode/*-free) only work inside OpenCode.
# vw-requires: opencode
#
# Adapter contract (all adapters):
#   in : env VW_WORKTREE, VW_MODEL, VW_PROMPT_FILE (+ VW_VARIANT, VW_ANGLE, VW_FEATURE)
#        cwd = worktree, stdin = /dev/null, scrubbed env (no tokens), timeout + retry by vw
#   out: edits/commits inside VW_WORKTREE only; exit code 0 = finished
#   never: push, open PRs, touch files outside the worktree
set -euo pipefail
OPENCODE_BIN="${OPENCODE_BIN:-$(command -v opencode || echo "$HOME/.opencode/bin/opencode")}"
# Headless OpenCode aborts the whole run on an auto-denied out-of-tree access unless it is
# denied up front (learned 2026-10-08). Keep it a deny, not an allow.
if [ -z "${OPENCODE_CONFIG_CONTENT:-}" ]; then
  export OPENCODE_CONFIG_CONTENT='{"permission":{"external_directory":"deny"}}'
fi
# Prompt passed from the file as one argv element: no shell evaluation of backticks.
exec "$OPENCODE_BIN" run --dir "$VW_WORKTREE" -m "$VW_MODEL" "$(cat "$VW_PROMPT_FILE")"

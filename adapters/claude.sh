#!/usr/bin/env bash
# Adapter: Claude Code (documented, NOT tested in this repo; check `claude --help` for your version).
# vw-requires: claude
# Auth: prefer `claude login` (stored in its own config dir). If you must use an API key,
# add ANTHROPIC_API_KEY to [runner].pass_env - the model's shell tool can then read it.
set -euo pipefail
cd "$VW_WORKTREE"
exec claude -p "$(cat "$VW_PROMPT_FILE")" \
  --model "$VW_MODEL" \
  --permission-mode acceptEdits \
  --allowedTools "Bash Edit Write Read Glob Grep" \
  --output-format text

#!/usr/bin/env bash
# Adapter: OpenAI Codex CLI (documented; flags checked against `codex exec --help` 2026-10, no model run).
# vw-requires: codex
# Auth: prefer `codex login`. API key via pass_env only if needed (OPENAI_API_KEY).
set -euo pipefail
exec codex exec \
  --cd "$VW_WORKTREE" \
  --model "$VW_MODEL" \
  --sandbox workspace-write \
  --skip-git-repo-check \
  "$(cat "$VW_PROMPT_FILE")"

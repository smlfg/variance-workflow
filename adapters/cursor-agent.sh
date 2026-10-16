#!/usr/bin/env bash
# Adapter: Cursor Agent CLI (documented; flags checked against `cursor-agent --help` 2026-10, no model run).
# vw-requires: cursor-agent
# Auth: prefer `cursor-agent login`. CURSOR_API_KEY via pass_env only if needed.
# --force lets it run shell commands without asking; it is confined by cwd + vw's scope check, not a sandbox.
set -euo pipefail
cd "$VW_WORKTREE"
exec cursor-agent --print --force --trust --output-format text \
  --workspace "$VW_WORKTREE" \
  --model "$VW_MODEL" \
  "$(cat "$VW_PROMPT_FILE")"

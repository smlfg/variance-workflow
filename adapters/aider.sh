#!/usr/bin/env bash
# Adapter: Aider (documented, NOT tested in this repo; check `aider --help`).
# vw-requires: aider
# Model ids use aider/litellm syntax, e.g. "deepseek/deepseek-chat" or "openrouter/z-ai/glm-...".
# Aider needs a provider key (pass_env), so prefer free/local providers for this workflow.
set -euo pipefail
cd "$VW_WORKTREE"
exec aider --model "$VW_MODEL" --yes-always --no-check-update --no-show-model-warnings \
  --auto-commits --message-file "$VW_PROMPT_FILE"

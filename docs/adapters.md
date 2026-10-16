# Harness adapters

A harness is the agent CLI that runs a model (OpenCode, Claude Code, Codex, Cursor Agent,
Aider, ...). `vw` never talks to a model directly; it starts `adapters/<harness>.sh`.

## Contract

| | |
|---|---|
| Input env | `VW_WORKTREE`, `VW_MODEL`, `VW_PROMPT_FILE`, `VW_VARIANT`, `VW_ANGLE`, `VW_FEATURE`, `VW_HOME` |
| cwd | the variant's worktree |
| stdin | `/dev/null` (always) |
| stdout/stderr | captured to `runs/<id>/<variant>/run.log` |
| exit code | `0` = finished; anything else triggers the single retry |
| must not | push, open PRs, write outside the worktree |

`vw` handles timeout, retry, concurrency, environment scrubbing, scope check, WIP commit and push.
An adapter is usually 3 to 10 lines.

## Header tags

```bash
# vw-requires: opencode          # binaries `vw doctor` checks
# vw-pass-env: ANTHROPIC_API_KEY # env vars this harness needs (otherwise dropped)
```

`vw-pass-env` deliberately exposes that variable to the harness *and* to every shell command
the model runs. Prefer harness logins stored in the harness's own config directory
(`claude login`, `codex login`, `cursor-agent login`) over keys in the environment.

## Included adapters

| Adapter | Command | Notes |
|---|---|---|
| `opencode.sh` | `opencode run --dir $WT -m $MODEL "$(cat prompt)"` | sets `OPENCODE_CONFIG_CONTENT={"permission":{"external_directory":"deny"}}`. Free `opencode/*-free` models only work inside OpenCode. |
| `claude.sh` | `claude -p ... --permission-mode acceptEdits` | untested here |
| `codex.sh` | `codex exec --cd $WT --sandbox workspace-write` | flags checked against `codex exec --help` |
| `cursor-agent.sh` | `cursor-agent --print --force --trust --workspace $WT` | flags checked against `cursor-agent --help` |
| `aider.sh` | `aider --yes-always --message-file prompt` | untested here; litellm model ids |
| `stub.sh` | `python3 adapters/stub_model.py` | dry runs of the demo |

## Mixing harnesses

Per model: `[[models]] harness = "codex"`; per variant: `explicit = [{ id = "c", model = "...", harness = "claude" }]`.
Comparing the *same* model in two harnesses is a valid experiment too.

## Adding one

1. Copy `adapters/stub.sh`, replace the command, keep `exec` so signals reach the agent.
2. Pass the prompt from the file as **one argument** (`"$(cat "$VW_PROMPT_FILE")"`) or via the
   harness's prompt-file flag, never interpolated into a double-quoted string (backticks run).
3. Make sure the harness does not prompt interactively; otherwise it hangs until the timeout.
4. `bin/vw -c <config> doctor`, then a run with one variant: `vw run --only a`.

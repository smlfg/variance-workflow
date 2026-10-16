You are {{model_short}} ({{model}}), building **variant {{variant_id}}** of the feature "{{feature}}" in this git repository.
You work alone in your own git worktree. Other models build other variants of the same feature in parallel.
All variants that pass the acceptance tests will be kept side by side in the repo as selectable alternatives.

## The feature

{{spec}}

## Where your code goes (hard rule)

Create or edit files ONLY at these paths:
{{owned}}

Everything else in the repo is read-only for you: the registry, shared code, `tests/acceptance/`, CI files,
dependency files, README. Your variant is discovered automatically; do not register it by hand.

## Contract your variant must implement

{{contract}}

## Acceptance (must pass before you finish)

    {{acceptance_cmd}}

Do not edit, skip or weaken the acceptance tests. If you think a test is wrong, say so in VARIANT_NOTES.md
and still make it pass.

## Notes file (required)

Write `VARIANT_NOTES.md` inside your variant directory:
- First line: `Approach: <one sentence>`.
- Trade-offs you chose and what you gave up.
- What you deliberately did differently from the obvious solution.
- Known limits.

## Rules

- No new third-party dependencies unless the spec allows them.
- Never use /tmp or paths outside the worktree; use the test framework's temp dirs.
- No network access unless the spec says so. No secrets, tokens or real personal data in code or tests.
- Small commits; every message contains `[{{variant_id}}/{{model_short}}]`.
- Do not push, do not open pull requests, do not run `gh`. The wrapper handles git remotes.

{{diverge}}

{{learnings}}

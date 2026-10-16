# variance-workflow

Several AI models build **different variants of the same feature** in parallel, each in its
own git worktree. Instead of "merge the best and close the rest", every variant that passes
the shared acceptance tests **stays in the repo** as a selectable alternative, and you get an
A/B/C/D/E comparison report: behaviour differences, metrics and notes on each model's style.

- **Harness-agnostic:** a model runs through a small adapter script. OpenCode is the default and
  tested; adapters for Claude Code, Codex, Cursor Agent and Aider are included (documented, not
  yet tested here).
- **Model-agnostic:** the model list is plain config. The defaults are free OpenCode models.
- **Zero dependencies:** Python 3.11+ standard library, git and bash.

> Why several models instead of one model asked for five variants? Different models make
> different default choices, much like different people. Five models with five assigned
> design angles cover more of the design space than one model imitating five styles.

## How it works

```mermaid
flowchart LR
    S[SPEC.md + acceptance tests<br/>+ variant registry] --> P[vw plan<br/>freeze base SHA,<br/>assign model + angle per variant]
    P --> W[vw spawn<br/>one git worktree + branch<br/>per variant, render prompt]
    W --> R{{vw run<br/>adapter per harness<br/>cap 6, timeout, retry once}}
    R --> A[variant A<br/>deepseek, angle 1]
    R --> B[variant B<br/>glm, angle 2]
    R --> C[variant C<br/>mimo, angle 3]
    R --> D[variant D ...]
    R --> E[variant E ...]
    A & B & C & D & E --> K[vw collect<br/>acceptance per variant,<br/>probes, diff + code metrics,<br/>similarity]
    K --> M[vw compare<br/>report.md: A/B/C/D/E table,<br/>behaviour diffs, personality notes]
    M --> I[vw integrate<br/>branch variants/FEATURE:<br/>all passing variants side by side]
    M --> L[LEARNINGS.draft.md<br/>one sentence per variant]
    L -. reviewed, appended to LEARNINGS.md .-> P
```

1. **Prepare the target repo once per feature:** a spec, shared acceptance tests that every
   variant must pass, and a *variant seam* (a registry, a plugin directory or a feature flag) so
   several implementations can coexist. See [docs/integration.md](docs/integration.md).
2. **`vw plan`** freezes the base commit and assigns each variant id (a, b, c, ...) a model, a
   harness and a design angle.
3. **`vw spawn`** creates one worktree and branch per variant (`variant/<feature>/<id>-<model>`)
   and renders the prompt: base template + spec + owned paths + the *diverge* instruction + recent
   learnings.
4. **`vw run`** runs all variants in parallel through their harness adapters with the hardening
   rules below. The wrapper commits leftovers as `WIP` and (if enabled) pushes. Models never get
   git or GitHub credentials.
5. **`vw collect`** runs the acceptance tests in every worktree (`VW_VARIANT=<id>`), runs the
   optional probe command (same inputs to every variant), and measures diff size, code style,
   scope violations, commits, retries, run time and pairwise similarity.
6. **`vw compare`** writes `report.md` and a `LEARNINGS.draft.md`.
7. **`vw integrate`** builds the branch `variants/<feature>` from the base: for every passing
   variant it copies **only the variant's owned paths**, runs the acceptance tests on the combined
   tree, and adds the report as `VARIANTS-<feature>.md`.

`vw all` runs steps 2 to 7 in one go.

## Quickstart

Dry run with the stub harness (no model calls, takes a second):

```bash
./examples/demo/run-demo.sh
less .vw/demo/runs/latest/report.md
git -C .vw/demo/target log --oneline variants/slugify
```

The demo target is a tiny `textkit` package whose `slugify` feature has a plugin registry. The
stub produces five variants on purpose: two that commit themselves, one that crashes once (and
is retried on the same worktree), one that edits `README.md` outside its lane (reported, never
integrated) and one that breaks idempotency (fails acceptance, not kept).

Real run on your own repo:

```bash
cp variance.example.toml /path/to/repo/variance.toml   # edit feature, owned paths, commands, models
bin/vw -c /path/to/repo/variance.toml doctor            # adapters on PATH? model ids visible?
bin/vw -c /path/to/repo/variance.toml plan
bin/vw -c /path/to/repo/variance.toml spawn
bin/vw -c /path/to/repo/variance.toml run               # long; safe to run under nohup
bin/vw -c /path/to/repo/variance.toml collect
bin/vw -c /path/to/repo/variance.toml compare
bin/vw -c /path/to/repo/variance.toml integrate
bin/vw -c /path/to/repo/variance.toml status            # per-variant rc/attempts + failures.log
bin/vw -c /path/to/repo/variance.toml clean             # remove worktrees, keep branches
```

Run state lives in `.vw/` next to the config (`runs/<run-id>/` with `plan.json`, per-variant
`prompt.md`, `run.log`, `status.json`, `acceptance.log`, plus `results.json`, `report.md`,
`failures.log`, `integration.json`). Add `.vw/` to the target's `.gitignore`.

## Configuration

See [variance.example.toml](variance.example.toml). The parts that matter most:

| Key | Meaning |
|---|---|
| `[feature].owned` | Paths a variant may write, with `{id}`. **This is what makes coexistence work**: integration only copies these. |
| `[feature].acceptance_cmd` | Shared tests; gets `VW_VARIANT=<id>` (or `a,b,c` on the integration tree). |
| `[feature].probe_cmd` | Optional: prints `{input: output}` JSON; differences become the behaviour table. |
| `[[models]]` | `id`, `short`, optional `harness`. Variants get models round-robin. |
| `[variants].angles` | Design angles, one per variant. Generic ones in [prompts/angles.md](prompts/angles.md). |
| `[variants].explicit` | Full control: id/model/angle per variant (e.g. one model, five angles). |
| `[runner]` | `harness`, `max_concurrent` (6), `timeout_s` (2880), `retries` (1), `stagger_s` (12), `push` (false), author. |

## Prompts

- [prompts/base.md](prompts/base.md): the task, owned paths, contract, acceptance, notes file, rules.
- [prompts/diverge.md](prompts/diverge.md): tells the model that N others build the same thing,
  that variety in *behaviour* is the goal, gives it its angle and lists the angles it should stay
  away from.
- [prompts/angles.md](prompts/angles.md): generic design angles to pick from.

Every model must write `VARIANT_NOTES.md` (first line `Approach: ...`) inside its own directory;
the report quotes it, and the notes ship with the variant.

## Harness adapters

An adapter is a bash script `adapters/<name>.sh` that starts one non-interactive agent run.
Contract: env `VW_WORKTREE`, `VW_MODEL`, `VW_PROMPT_FILE` (+ `VW_VARIANT`, `VW_ANGLE`); cwd is the
worktree; stdin is `/dev/null`; exit code 0 means finished. Details and how to add one:
[docs/adapters.md](docs/adapters.md).

| Adapter | Status |
|---|---|
| `opencode` | default, used for the real build loop |
| `stub` | demo/dry runs, no model |
| `claude`, `codex`, `cursor-agent`, `aider` | documented; codex and cursor-agent flags checked against their `--help`; no model run yet |

## Hardening (kept from the build loop)

Each item comes from a real failure; see [docs/hardening.md](docs/hardening.md).

- stdin from `/dev/null` (otherwise headless runs hang).
- Timeout per attempt (default 48 min); the whole process group gets SIGTERM, then SIGKILL.
- One retry on non-zero exit: **same worktree, same branch, same prompt, same model**.
- Concurrency cap 6 across processes (flock slots); starts staggered by 12 s.
- `failures.log` per run: failures, retries, timeouts, signals with a process snapshot.
- No secrets to models: allowlisted environment, secret-looking names dropped, no GitHub config,
  empty global git config (no credential helper), wrapper-only push. `HOME` is passed through,
  never re-exported.
- OpenCode: `external_directory` denied up front so an out-of-tree access cannot kill the run.
- Variants only write their own paths; anything else is reported and never integrated.

Security beyond "no secrets to models" is optional for this workflow; run it on a throwaway
machine or box if the models get `--force`-style permissions.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Covers the helpers, environment scrubbing, the timeout kill and a full stub run of the demo.

## License

MIT, see [LICENSE](LICENSE).

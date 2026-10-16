# Hardening: where each rule comes from

All from the 2026-10 build loop (smlfg CLI → MCP repos, free OpenCode models).

| Rule | Incident |
|---|---|
| stdin `< /dev/null` | headless `opencode run` waited on stdin and hung |
| timeout per attempt (48 min), process-group kill | a hung run blocks a slot forever; agents spawn child processes that must die with them |
| retry once, same worktree/branch/prompt/model | 5 runs killed by a local RAM watchdog (SIGTERM) on 2026-10-15; a retry must keep the same branch so it never opens a second PR |
| push/PR only after the retry | a retry must not create a second branch or PR |
| concurrency cap 6 (flock, cross-process) | with 8 parallel runs free RAM fell under the watchdog's 1200 MiB limit |
| starts ≥ 12 s apart | OpenCode "database is locked" on simultaneous starts |
| `failures.log` with signal + process snapshot | the kills were invisible ("died silently") until the sender was logged |
| `external_directory: deny` | an auto-denied `/tmp` access aborted the whole headless run, often right before the commit |
| "never /tmp" in the prompt | same incident |
| prompt passed as one argv element from a file | backticks in a double-quoted prompt were executed by bash |
| no GH token, `GH_CONFIG_DIR=/nonexistent`, empty global git config | models must not push, merge or open PRs; the wrapper does it |
| HOME never re-exported | standing rule: a different HOME changes where the harness finds its config and login |
| freeze the base SHA | variants started from a moving branch showed base changes as diff noise |
| wrapper WIP commit | some models finish without committing; the first attempt must still be recorded |
| owned paths + scope report | a model loosened a shared test fake to get green (2026-10-08) |

`vw` implements these in Python; the original bash versions live in the private build tooling
(`run-model.sh`, `opencode-lib.sh`, `opencode-supervise.py`). For the exact signal sender (si_pid),
wrap the adapter command with a supervisor like `opencode-supervise.py`; plain `vw` logs the signal
and a process snapshot.

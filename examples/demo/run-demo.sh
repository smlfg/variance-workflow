#!/usr/bin/env bash
# Dry run of the whole pipeline against a throwaway copy of the demo target, with the stub harness.
# No model runs, no network, no push. Output: .vw/demo/runs/latest/report.md
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; root="$(cd "$here/../.." && pwd)"
demo="$root/.vw/demo"
if [ -d "$demo/target" ]; then git -C "$demo/target" worktree prune || true; fi
rm -rf "$demo"; mkdir -p "$demo"
cp -r "$here/target" "$demo/target"
find "$demo/target" -name __pycache__ -prune -exec rm -rf {} +
git -C "$demo/target" init -q -b main
git -C "$demo/target" add -A
git -C "$demo/target" -c user.name="Samuel Fleig (via Agent)" -c user.email="186922365+smlfg@users.noreply.github.com" \
  commit -q -m "demo target: textkit with slugify registry"
"$root/bin/vw" -c "$here/demo.toml" all
echo; echo "report: $demo/runs/latest/report.md"

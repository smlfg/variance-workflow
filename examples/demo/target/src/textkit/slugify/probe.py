"""Print each probe input's output as JSON for the variant(s) in VW_VARIANT."""
import json
import os
import sys

from textkit.slugify import get

inputs = json.load(open(sys.argv[1], encoding="utf-8"))
ids = [i for i in os.environ.get("VW_VARIANT", "ref").split(",") if i]
out = {}
for vid in ids:
    mod = get(vid)
    res = {}
    for s in inputs:
        try:
            res[s] = mod.slugify(s)
        except Exception as e:  # noqa: BLE001 - behaviour difference worth reporting
            res[s] = f"<{type(e).__name__}>"
    out[vid] = res
print(json.dumps(out[ids[0]] if len(ids) == 1 else out, ensure_ascii=False))

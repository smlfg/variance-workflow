#!/usr/bin/env python3
"""vw - variance workflow: several models build different variants of one feature.

Stdlib only (Python >= 3.11). Pipeline:

    plan -> spawn -> run -> collect -> compare -> integrate

Every subcommand reads the same TOML config and works on one run directory
(.vw/runs/<run-id>/, `latest` is a symlink to the newest run). Models run
through a harness adapter (adapters/<name>.sh); the wrapper, never the model,
commits and (optionally) pushes.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import difflib
import fcntl
import fnmatch
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

VW_HOME = Path(__file__).resolve().parent.parent
LETTERS = "abcdefghijklmnopqrstuvwxyz"

# Environment the harness/model may see. Everything else is dropped.
ENV_ALLOW = {
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TZ", "TMPDIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
    "XDG_STATE_HOME", "XDG_RUNTIME_DIR", "PYTHONPATH", "VIRTUAL_ENV",
}
SECRET_RE = re.compile(r"(TOKEN|SECRET|PASSW|API_?KEY|PRIVATE|CREDENTIAL|AUTH|COOKIE|SESSION)", re.I)


# --------------------------------------------------------------------------- utils
def now() -> str:
    return dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def die(msg: str, code: int = 1) -> None:
    print(f"vw: {msg}", file=sys.stderr)
    sys.exit(code)


def sh(cmd: list[str] | str, cwd: Path | None = None, check: bool = True, env: dict | None = None,
       timeout: float | None = None) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, env=env, timeout=timeout,
                       shell=isinstance(cmd, str), stdin=subprocess.DEVNULL)
    if check and p.returncode != 0:
        die(f"command failed ({p.returncode}): {cmd}\n{p.stderr.strip()}")
    return p


def git(repo: Path, *args: str, check: bool = True) -> str:
    return sh(["git", "-C", str(repo), *args], check=check).stdout.strip()


def append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def render(template: str, values: dict[str, str]) -> str:
    def rep(m: re.Match) -> str:
        return str(values.get(m.group(1), m.group(0)))
    return re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", rep, template)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:24] or "x"


# --------------------------------------------------------------------------- config
class Config:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.dir = self.path.parent
        with open(self.path, "rb") as f:
            self.raw = tomllib.load(f)
        p = self.raw.get("project", {})
        self.repo = self._p(p.get("repo", "."))
        self.base = p.get("base", "HEAD")
        self.state = self._p(p.get("state_dir", ".vw"))
        f = self.raw.get("feature", {})
        if "name" not in f:
            die("config: [feature].name is required")
        self.feature = f["name"]
        self.spec = f.get("spec", "")
        self.owned = f.get("owned", [])
        if not self.owned:
            die("config: [feature].owned must list the paths a variant may write (use {id})")
        self.contract = f.get("contract", "")
        self.acceptance_cmd = f.get("acceptance_cmd", "")
        self.probe_cmd = f.get("probe_cmd", "")
        self.setup_cmd = f.get("setup_cmd", "")
        self.integration_branch = f.get("integration_branch", f"variants/{self.feature}")
        r = self.raw.get("runner", {})
        self.harness = r.get("harness", "opencode")
        self.max_concurrent = int(r.get("max_concurrent", 6))
        self.timeout_s = int(r.get("timeout_s", 2880))
        self.retries = int(r.get("retries", 1))
        self.stagger_s = float(r.get("stagger_s", 12))
        self.slot_dir = self._p(r.get("slot_dir", "~/.cache/variance-workflow/slots"))
        self.slot_wait_s = int(r.get("slot_wait_s", 7200))
        self.push = bool(r.get("push", False))
        self.remote = r.get("remote", "origin")
        self.author_name = r.get("author_name", "Samuel Fleig (via Agent)")
        self.author_email = r.get("author_email", "186922365+smlfg@users.noreply.github.com")
        self.pass_env = list(r.get("pass_env", []))
        self.harness_env = dict(r.get("harness_env", {}))
        self.models = self.raw.get("models", [])
        if not self.models:
            die("config: at least one [[models]] entry is required")
        v = self.raw.get("variants", {})
        self.count = int(v.get("count", 5))
        self.angles = v.get("angles", [])
        self.assign_angles = bool(v.get("assign_angles", True))
        self.explicit = v.get("explicit", [])
        pr = self.raw.get("prompts", {})
        self.prompt_base = self._p(pr.get("base", str(VW_HOME / "prompts/base.md")))
        self.prompt_diverge = self._p(pr.get("diverge", str(VW_HOME / "prompts/diverge.md")))
        self.learnings_file = pr.get("learnings_file", "")
        self.learnings_lines = int(pr.get("learnings_lines", 40))

    def _p(self, s: str) -> Path:
        q = Path(os.path.expanduser(s))
        return q if q.is_absolute() else (self.dir / q).resolve()

    @property
    def runs(self) -> Path:
        return self.state / "runs"


def run_dir(cfg: Config, run_id: str | None) -> Path:
    d = cfg.runs / (run_id or "latest")
    if not d.exists():
        die(f"no run found at {d} (run `vw plan` first)")
    return d.resolve()


def owned_paths(cfg: Config, vid: str) -> list[str]:
    return [o.replace("{id}", vid) for o in cfg.owned]


def is_owned(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if pat.endswith("/") and path.startswith(pat):
            return True
        if fnmatch.fnmatch(path, pat):
            return True
    return False


# --------------------------------------------------------------------------- plan
def cmd_plan(cfg: Config, a) -> None:
    if sh(["git", "-C", str(cfg.repo), "rev-parse", "--git-dir"], check=False).returncode != 0:
        die(f"{cfg.repo} is not a git repo")
    base_sha = git(cfg.repo, "rev-parse", cfg.base)  # frozen base: every variant starts here
    run_id = a.run_id or f"{slug(cfg.feature)}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    rd = cfg.runs / run_id
    if rd.exists():
        die(f"run {run_id} exists")
    variants = []
    if cfg.explicit:
        entries = cfg.explicit
    else:
        entries = [{} for _ in range(cfg.count)]
    for i, e in enumerate(entries):
        vid = e.get("id", LETTERS[i])
        m = e.get("model") or cfg.models[i % len(cfg.models)]["id"]
        mshort = e.get("short") or next((x.get("short") for x in cfg.models if x["id"] == m), None) \
            or slug(m.split("/")[-1])
        angle = e.get("angle")
        if angle is None and cfg.assign_angles and cfg.angles:
            angle = cfg.angles[i % len(cfg.angles)]
        harness = e.get("harness") or next((x.get("harness") for x in cfg.models if x["id"] == m), None) \
            or cfg.harness
        variants.append({
            "id": vid, "model": m, "short": mshort, "angle": angle or "", "harness": harness,
            "branch": f"variant/{slug(cfg.feature)}/{vid}-{mshort}",
            "worktree": str(cfg.state / "worktrees" / run_id / vid),
            "owned": owned_paths(cfg, vid),
        })
    ids = [v["id"] for v in variants]
    if len(set(ids)) != len(ids):
        die(f"duplicate variant ids: {ids}")
    plan = {"run_id": run_id, "feature": cfg.feature, "repo": str(cfg.repo), "base_sha": base_sha,
            "config": str(cfg.path), "created": now(), "variants": variants}
    write_json(rd / "plan.json", plan)
    latest = cfg.runs / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(run_id)
    print(f"planned {run_id}: base {base_sha[:7]}")
    for v in variants:
        print(f"  {v['id']}  {v['model']:<40} {v['harness']:<9} angle: {v['angle'] or '-'}")


# --------------------------------------------------------------------------- prompts
def learnings_tail(cfg: Config) -> str:
    if not cfg.learnings_file:
        return ""
    p = cfg._p(cfg.learnings_file) if not (cfg.repo / cfg.learnings_file).exists() else cfg.repo / cfg.learnings_file
    if not p.exists():
        return ""
    lines = p.read_text(encoding="utf-8").splitlines()[-cfg.learnings_lines:]
    return "## Learnings from earlier runs (apply them)\n" + "\n".join(lines)


def build_prompt(cfg: Config, plan: dict, v: dict) -> str:
    spec_path = cfg.repo / cfg.spec if cfg.spec else None
    spec = spec_path.read_text(encoding="utf-8") if spec_path and spec_path.exists() else "(no spec file)"
    others = [x for x in plan["variants"] if x["id"] != v["id"]]
    values = {
        "feature": cfg.feature, "variant_id": v["id"], "model": v["model"], "model_short": v["short"],
        "angle": v["angle"] or "(none assigned: choose a non-obvious approach yourself)",
        "owned": "\n".join(f"- `{o}`" for o in v["owned"]),
        "contract": cfg.contract.replace("{id}", v["id"]).strip() or "(see spec)",
        "acceptance_cmd": f"VW_VARIANT={v['id']} " + cfg.acceptance_cmd.replace("{id}", v["id"]),
        "spec": spec.strip(), "n_others": str(len(others)),
        "other_angles": "\n".join(f"- {x['id']}: {x['angle']}" for x in others if x["angle"]) or "- (not disclosed)",
    }
    diverge = render(cfg.prompt_diverge.read_text(encoding="utf-8"), values) if cfg.prompt_diverge.exists() else ""
    values["diverge"] = diverge.strip()
    values["learnings"] = learnings_tail(cfg)
    return render(cfg.prompt_base.read_text(encoding="utf-8"), values).strip() + "\n"


# --------------------------------------------------------------------------- spawn
def cmd_spawn(cfg: Config, a) -> None:
    rd = run_dir(cfg, a.run_id)
    plan = read_json(rd / "plan.json")
    for v in plan["variants"]:
        wt = Path(v["worktree"])
        if not wt.exists():
            wt.parent.mkdir(parents=True, exist_ok=True)
            git(cfg.repo, "worktree", "add", "-q", "-B", v["branch"], str(wt), plan["base_sha"])
        (rd / v["id"]).mkdir(exist_ok=True)
        # Prompt lives in the run dir, never inside the worktree (keeps it out of the diff).
        (rd / v["id"] / "prompt.md").write_text(build_prompt(cfg, plan, v), encoding="utf-8")
        if cfg.setup_cmd:
            p = sh(cfg.setup_cmd, cwd=wt, check=False, timeout=900)
            if p.returncode != 0:
                append(rd / v["id"] / "setup.log", p.stdout + p.stderr)
        print(f"spawned {v['id']}: {v['branch']} -> {wt}")


# --------------------------------------------------------------------------- run
class Slots:
    """Cross-process concurrency cap via flock slot files (same idea as opencode-lib.sh)."""

    def __init__(self, d: Path, n: int, wait_s: int):
        self.d, self.n, self.wait_s = d, n, wait_s
        d.mkdir(parents=True, exist_ok=True)

    def acquire(self):
        t0 = time.time()
        while time.time() - t0 < self.wait_s:
            for i in range(1, self.n + 1):
                f = open(self.d / f"{i}.lock", "w")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return i, f
                except BlockingIOError:
                    f.close()
            time.sleep(2)
        return None, None


_stagger_lock = threading.Lock()
_last_start = [0.0]


def adapter_meta(adapter: Path) -> dict[str, list[str]]:
    meta: dict[str, list[str]] = {"pass-env": [], "requires": []}
    for line in adapter.read_text(encoding="utf-8").splitlines()[:40]:
        m = re.match(r"#\s*vw-(pass-env|requires):\s*(.*)", line)
        if m:
            meta[m.group(1)] += m.group(2).split()
    return meta


def model_env(cfg: Config, rd: Path, v: dict, prompt: Path, extra_pass: list[str]) -> dict[str, str]:
    env = {k: val for k, val in os.environ.items() if k in ENV_ALLOW and not SECRET_RE.search(k)}
    for k in cfg.pass_env + extra_pass:  # explicit opt-in only (e.g. a harness that needs its key)
        if k in os.environ:
            env[k] = os.environ[k]
    empty_gitcfg = rd / "gitconfig-empty"
    empty_gitcfg.touch()
    env.update({
        # no GitHub / git credentials for the model: wrapper pushes.
        "GH_CONFIG_DIR": "/nonexistent", "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false",
        "GIT_CONFIG_GLOBAL": str(empty_gitcfg), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": cfg.author_name, "GIT_AUTHOR_EMAIL": cfg.author_email,
        "GIT_COMMITTER_NAME": cfg.author_name, "GIT_COMMITTER_EMAIL": cfg.author_email,
        "VW_HOME": str(VW_HOME), "VW_WORKTREE": v["worktree"], "VW_MODEL": v["model"],
        "VW_VARIANT": v["id"], "VW_ANGLE": v["angle"], "VW_PROMPT_FILE": str(prompt),
        "VW_FEATURE": cfg.feature, "PYTHONUNBUFFERED": "1",
    })
    env.update({k: str(val) for k, val in cfg.harness_env.items()})
    return env


def ps_snapshot() -> str:
    p = sh(["ps", "-eo", "pid,ppid,rss,stat,cmd", "--sort=-rss"], check=False)
    return "\n".join(p.stdout.splitlines()[:20])


def invoke(cfg: Config, adapter: Path, env: dict, wt: str, log: Path, failures: Path, tag: str) -> int:
    with open(log, "a", encoding="utf-8") as lf:
        proc = subprocess.Popen(["bash", str(adapter)], cwd=wt, env=env, stdin=subprocess.DEVNULL,
                                stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rc = proc.wait(timeout=cfg.timeout_s)
        except subprocess.TimeoutExpired:
            append(failures, f"[{now()}] TIMEOUT tag={tag} after {cfg.timeout_s}s -> SIGTERM process group")
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                rc = proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                rc = proc.wait()
            rc = 124 if rc in (-signal.SIGTERM, -signal.SIGKILL) else rc
    if rc < 0:
        sig = signal.Signals(-rc).name
        append(failures, f"[{now()}] SIGNAL tag={tag} child killed by {sig} (sender unknown from here;"
                         f" wrap adapter with opencode-supervise.py for si_pid)\nps_snapshot:\n{ps_snapshot()}")
        rc = 128 - rc
    return rc


def run_one(cfg: Config, rd: Path, plan: dict, v: dict, slots: Slots) -> dict:
    vd = rd / v["id"]
    log, prompt = vd / "run.log", vd / "prompt.md"
    failures = rd / "failures.log"
    tag = f"{plan['run_id']}/{v['id']}/{v['short']}"
    adapter = VW_HOME / "adapters" / f"{v['harness']}.sh"
    st = {"id": v["id"], "model": v["model"], "harness": v["harness"], "attempts": 0, "rc": None}
    if not adapter.exists():
        st.update(rc=2, error=f"adapter {adapter.name} missing")
        write_json(vd / "status.json", st)
        return st
    meta = adapter_meta(adapter)
    env = model_env(cfg, rd, v, prompt, meta["pass-env"])
    slot, fh = slots.acquire()
    if slot is None:
        st.update(rc=3, error="no slot")
        append(failures, f"[{now()}] SKIP tag={tag} no slot within {cfg.slot_wait_s}s (cap={cfg.max_concurrent})")
        write_json(vd / "status.json", st)
        return st
    try:
        with _stagger_lock:  # avoid opencode "database is locked" on simultaneous starts
            wait = _last_start[0] + cfg.stagger_s - time.time()
            if wait > 0:
                time.sleep(wait)
            _last_start[0] = time.time()
        log.write_text(f"===== {now()} start {tag} slot={slot} model={v['model']} =====\n", encoding="utf-8")
        t0 = time.time()
        rc = invoke(cfg, adapter, env, v["worktree"], log, failures, tag)
        first_rc, attempts = rc, 1
        while rc != 0 and attempts <= cfg.retries:
            # Retry: same worktree, same branch, same prompt/model/env. Never a new branch.
            append(log, f"\n===== RETRY {now()} same-worktree={v['worktree']} same-model={v['model']} =====")
            rc = invoke(cfg, adapter, env, v["worktree"], log, failures, tag)
            attempts += 1
        if first_rc != 0:
            append(failures, f"[{now()}] FAIL tag={tag} first_rc={first_rc} attempts={attempts} final_rc={rc}")
        st.update(rc=rc, first_rc=first_rc, attempts=attempts, seconds=round(time.time() - t0, 1), slot=slot)
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
    st.update(post_run(cfg, plan, v, rc))
    write_json(vd / "status.json", st)
    return st


def post_run(cfg: Config, plan: dict, v: dict, rc: int) -> dict:
    """Wrapper-side: scope check, WIP commit, optional push. The model never pushes."""
    wt = Path(v["worktree"])
    base = plan["base_sha"]
    model_commits = int(git(wt, "rev-list", "--count", f"{base}..HEAD") or 0)
    sh(["git", "-C", str(wt), "add", "-A"], check=False)
    dirty = sh(["git", "-C", str(wt), "diff", "--cached", "--quiet"], check=False).returncode != 0
    wip = False
    if dirty:
        sh(["git", "-C", str(wt), "-c", f"user.name={cfg.author_name}", "-c", f"user.email={cfg.author_email}",
            "commit", "-q", "--no-verify", "-m",
            f"WIP [{v['id']}/{v['short']}]: auto-commit after run (rc={rc})"], check=False)
        wip = True
    changed = [p for p in git(wt, "diff", "--name-only", f"{base}..HEAD").splitlines() if p]
    out_of_scope = [p for p in changed if not is_owned(p, v["owned"])]
    pushed = None
    if cfg.push and changed:
        p = sh(["git", "-C", str(wt), "push", "-q", "-u", cfg.remote, v["branch"]], check=False)
        pushed = p.returncode == 0
    return {"model_commits": model_commits, "wip_commit": wip, "changed": changed,
            "out_of_scope": out_of_scope, "head": git(wt, "rev-parse", "--short", "HEAD"), "pushed": pushed}


def cmd_run(cfg: Config, a) -> None:
    rd = run_dir(cfg, a.run_id)
    plan = read_json(rd / "plan.json")
    todo = [v for v in plan["variants"] if not a.only or v["id"] in a.only.split(",")]
    slots = Slots(cfg.slot_dir, cfg.max_concurrent, cfg.slot_wait_s)
    print(f"running {len(todo)} variant(s), cap={cfg.max_concurrent}, timeout={cfg.timeout_s}s, retries={cfg.retries}")
    with cf.ThreadPoolExecutor(max_workers=max(1, len(todo))) as ex:
        for st in ex.map(lambda v: run_one(cfg, rd, plan, v, slots), todo):
            flag = "ok " if st["rc"] == 0 else "ERR"
            print(f"  {flag} {st['id']} {st['model']} rc={st['rc']} attempts={st.get('attempts')} "
                  f"out_of_scope={len(st.get('out_of_scope', []))}")


# --------------------------------------------------------------------------- collect
COUNT_RES = [
    (re.compile(r"Ran (\d+) tests?"), "total"),
    (re.compile(r"(\d+) passed"), "passed"),
    (re.compile(r"(\d+) failed"), "failed"),
    (re.compile(r"failures=(\d+)"), "failed"),
    (re.compile(r"errors?=(\d+)"), "errors"),
]


def parse_counts(text: str) -> dict:
    c: dict[str, int] = {}
    for rx, k in COUNT_RES:
        for m in rx.finditer(text):
            c[k] = c.get(k, 0) + int(m.group(1))
    return c


def code_stats(wt: Path, files: list[str]) -> dict:
    loc = comments = funcs = classes = 0
    imports: set[str] = set()
    text_all = []
    for f in files:
        p = wt / f
        if not p.is_file() or p.suffix not in {".py", ".ts", ".js", ".sh", ".go", ".rs"}:
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        text_all.append(t)
        for line in t.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith(("#", "//")) or s.startswith(('"""', "'''")):
                comments += 1
            else:
                loc += 1
            if re.match(r"(async\s+)?def |function ", s):
                funcs += 1
            if s.startswith("class "):
                classes += 1
            m = re.match(r"(?:from|import)\s+([\w\.]+)", s)
            if m:
                imports.add(m.group(1).split(".")[0])
    return {"loc": loc, "comment_lines": comments,
            "comment_ratio": round(comments / max(1, loc + comments), 2),
            "functions": funcs, "classes": classes, "imports": sorted(imports), "_text": "\n".join(text_all)}


def cmd_collect(cfg: Config, a) -> None:
    rd = run_dir(cfg, a.run_id)
    plan = read_json(rd / "plan.json")
    base = plan["base_sha"]
    results = []
    for v in plan["variants"]:
        wt = Path(v["worktree"])
        vd = rd / v["id"]
        st = read_json(vd / "status.json") if (vd / "status.json").exists() else {}
        r = {"id": v["id"], "model": v["model"], "short": v["short"], "angle": v["angle"],
             "branch": v["branch"], "status": st}
        env = dict(os.environ, VW_VARIANT=v["id"])
        if cfg.acceptance_cmd:
            t0 = time.time()
            try:
                p = sh(cfg.acceptance_cmd.replace("{id}", v["id"]), cwd=wt, check=False, env=env, timeout=900)
                out, rc = p.stdout + p.stderr, p.returncode
            except subprocess.TimeoutExpired:
                out, rc = "timeout", 124
            (vd / "acceptance.log").write_text(out, encoding="utf-8")
            r["acceptance"] = {"rc": rc, "passed": rc == 0, "seconds": round(time.time() - t0, 2),
                               "counts": parse_counts(out), "tail": out.strip().splitlines()[-3:]}
        if cfg.probe_cmd:
            try:
                p = sh(cfg.probe_cmd.replace("{id}", v["id"]), cwd=wt, check=False, env=env, timeout=300)
                r["probes"] = json.loads(p.stdout) if p.returncode == 0 else {"_error": p.stderr.strip()[-400:]}
            except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
                r["probes"] = {"_error": str(e)}
        numstat = git(wt, "diff", "--numstat", f"{base}..HEAD", check=False)
        add = rem = 0
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].isdigit():
                add, rem = add + int(parts[0]), rem + int(parts[1])
        files = [p for p in git(wt, "diff", "--name-only", f"{base}..HEAD", check=False).splitlines() if p]
        owned_files = [f for f in files if is_owned(f, v["owned"])]
        cs = code_stats(wt, owned_files)
        (vd / "source.txt").write_text(cs.pop("_text"), encoding="utf-8")
        msgs = git(wt, "log", "--format=%s", f"{base}..HEAD", check=False).splitlines()
        notes = next((wt / f for f in owned_files if f.endswith("VARIANT_NOTES.md")), None)
        notes_text = notes.read_text(encoding="utf-8") if notes and notes.exists() else ""
        r["diff"] = {"files": len(files), "added": add, "removed": rem, "owned_files": owned_files,
                     "out_of_scope": [f for f in files if f not in owned_files]}
        r["code"] = cs
        r["commits"] = {"total": len(msgs), "wip": sum(m.startswith("WIP ") for m in msgs), "messages": msgs[:10]}
        r["notes"] = {"present": bool(notes_text), "words": len(notes_text.split()),
                      "approach": first_line(notes_text)}
        results.append(r)
    # pairwise similarity of variant sources: near-duplicates defeat the purpose
    sims = {}
    srcs = {r["id"]: (rd / r["id"] / "source.txt").read_text(encoding="utf-8") for r in results}
    ids = list(srcs)
    for i, x in enumerate(ids):
        for y in ids[i + 1:]:
            sims[f"{x}-{y}"] = round(difflib.SequenceMatcher(None, srcs[x], srcs[y]).ratio(), 2) \
                if srcs[x] and srcs[y] else None
    write_json(rd / "results.json", {"run_id": plan["run_id"], "collected": now(), "variants": results,
                                     "similarity": sims})
    print(f"collected {len(results)} variant(s) -> {rd / 'results.json'}")


def first_line(md: str) -> str:
    for line in md.splitlines():
        s = line.strip().lstrip("#-* ").strip()
        if s and not s.lower().startswith(("variant", "approach:")):
            return s[:200]
        if s.lower().startswith("approach:"):
            return s.split(":", 1)[1].strip()[:200]
    return ""


# --------------------------------------------------------------------------- compare
def personality(r: dict) -> str:
    st, c, d = r.get("status", {}), r["code"], r["diff"]
    bits = []
    loc = c["loc"]
    bits.append("terse" if loc < 30 else "compact" if loc < 80 else "expansive" if loc < 200 else "sprawling")
    bits.append(f"{loc} LOC")
    cr = c["comment_ratio"]
    bits.append("heavily commented" if cr > 0.3 else "lightly commented" if cr > 0.08 else "almost no comments")
    if r["commits"]["total"] - r["commits"]["wip"] > 0:
        bits.append(f"committed itself ({r['commits']['total'] - r['commits']['wip']}x)")
    else:
        bits.append("left committing to the wrapper")
    if d["out_of_scope"]:
        bits.append(f"strayed outside its lane ({len(d['out_of_scope'])} file(s))")
    else:
        bits.append("stayed in its lane")
    if st.get("attempts", 1) > 1:
        bits.append("needed a retry")
    if not r["notes"]["present"]:
        bits.append("skipped the notes")
    ext = [i for i in c["imports"] if i not in {"re", "typing", "__future__"}]
    if ext:
        bits.append("uses " + ", ".join(ext[:4]))
    if st.get("seconds"):
        bits.append(f"{int(st['seconds'] // 60)}m{int(st['seconds'] % 60):02d}s")
    return "; ".join(bits)


def md_cell(x) -> str:
    s = json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else repr(x)
    return s.replace("|", "\\|")[:72]


def cmd_compare(cfg: Config, a) -> None:
    rd = run_dir(cfg, a.run_id)
    plan = read_json(rd / "plan.json")
    res = read_json(rd / "results.json")
    vs = res["variants"]
    L = [f"# Variant comparison: `{plan['feature']}`", "",
         f"Run `{plan['run_id']}`, base `{plan['base_sha'][:7]}`, collected {res['collected']}.", "",
         "Every variant had the same spec, the same acceptance tests and its own worktree. "
         "The goal is variety, not a winner: all variants that pass acceptance are kept.", "",
         "## Overview", "",
         "| Variant | Model | Angle | Acceptance | Tests | Attempts | Files (+/-) | LOC | Out of scope |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in vs:
        acc = r.get("acceptance", {})
        cnt = acc.get("counts", {})
        tests = f"{cnt.get('total', cnt.get('passed', '?'))} tests, {cnt.get('failed', 0) + cnt.get('errors', 0)} failing checks" \
            if acc else "-"
        L.append(f"| **{r['id'].upper()}** | `{r['model']}` | {r['angle'] or '-'} | "
                 f"{'PASS' if acc.get('passed') else 'FAIL' if acc else '-'} | {tests} | "
                 f"{r['status'].get('attempts', '-')} | {r['diff']['files']} (+{r['diff']['added']}/-{r['diff']['removed']}) | "
                 f"{r['code']['loc']} | {len(r['diff']['out_of_scope'])} |")
    # behaviour differences
    probes = [r for r in vs if isinstance(r.get("probes"), dict) and "_error" not in r["probes"]]
    if probes:
        keys = list(dict.fromkeys(k for r in probes for k in r["probes"]))
        differ = [k for k in keys if len({json.dumps(r["probes"].get(k), ensure_ascii=False) for r in probes}) > 1]
        same = len(keys) - len(differ)
        L += ["", "## Behaviour differences", "",
              f"{len(keys)} probe inputs; {len(differ)} produce different outputs across variants, {same} agree.", ""]
        if differ:
            L.append("| Input | " + " | ".join(r["id"].upper() for r in probes) + " |")
            L.append("|---|" + "---|" * len(probes))
            for k in differ:
                L.append(f"| {md_cell(k)} | " + " | ".join(md_cell(r["probes"].get(k)) for r in probes) + " |")
    errs = [r for r in vs if isinstance(r.get("probes"), dict) and "_error" in r["probes"]]
    for r in errs:
        L.append(f"\n> Probe error in {r['id'].upper()}: `{r['probes']['_error'][:200]}`")
    # similarity
    if res.get("similarity"):
        L += ["", "## Similarity (source text, 0 = unrelated, 1 = identical)", ""]
        hi = {k: s for k, s in res["similarity"].items() if s is not None and s >= 0.8}
        L.append("| Pair | Ratio |")
        L.append("|---|---|")
        for k, s in res["similarity"].items():
            L.append(f"| {k.upper()} | {s if s is not None else '-'}{' ⚠ near-duplicate' if k in hi else ''} |")
        if hi:
            L += ["", "Near-duplicates add little variety. Consider re-rolling one of them with a sharper angle."]
    # metrics
    L += ["", "## Metrics", "", "| Variant | Run time | Acceptance time | Functions | Classes | Comment ratio | Imports | Commits (WIP) |",
          "|---|---|---|---|---|---|---|---|"]
    for r in vs:
        st, c = r["status"], r["code"]
        L.append(f"| {r['id'].upper()} | {st.get('seconds', '-')}s | {r.get('acceptance', {}).get('seconds', '-')}s | "
                 f"{c['functions']} | {c['classes']} | {c['comment_ratio']} | {', '.join(c['imports']) or '-'} | "
                 f"{r['commits']['total']} ({r['commits']['wip']}) |")
    # personality
    L += ["", "## Model personality notes", "",
          "Heuristic, from the diff and the run. Add your own impression in the last column when you review.", "",
          "| Variant | Model | Approach (from VARIANT_NOTES.md) | Observed style | Your note |", "|---|---|---|---|---|"]
    for r in vs:
        L.append(f"| {r['id'].upper()} | `{r['short']}` | {r['notes']['approach'] or '(no notes)'} | {personality(r)} | |")
    outs = [r for r in vs if r["diff"]["out_of_scope"]]
    if outs:
        L += ["", "## Scope violations", "",
              "These files were changed outside the variant's own paths. `vw integrate` never carries them over."]
        for r in outs:
            L.append(f"- {r['id'].upper()}: " + ", ".join(f"`{f}`" for f in r["diff"]["out_of_scope"]))
    integ = rd / "integration.json"
    if integ.exists():
        ij = read_json(integ)
        L += ["", "## Integration", "", f"Branch `{ij['branch']}` at `{ij.get('head', '?')}`: "
              f"included {', '.join(x.upper() for x in ij['included']) or 'none'}; "
              f"skipped {', '.join(x.upper() for x in ij['skipped']) or 'none'}. "
              f"Acceptance on the combined tree: {'PASS' if ij.get('combined_passed') else 'FAIL'}."]
    (rd / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    # learnings draft: one sentence per variant (character, not verdict)
    D = [f"## {plan['feature']} ({plan['run_id']})"]
    for r in vs:
        ok = r.get("acceptance", {}).get("passed")
        D.append(f"- {r['id'].upper()} `{r['short']}` ({r['angle'] or 'free choice'}): "
                 f"{'kept' if ok else 'not kept'}; {personality(r)}.")
    (rd / "LEARNINGS.draft.md").write_text("\n".join(D) + "\n", encoding="utf-8")
    print(f"report -> {rd / 'report.md'}")


# --------------------------------------------------------------------------- integrate
def cmd_integrate(cfg: Config, a) -> None:
    rd = run_dir(cfg, a.run_id)
    plan = read_json(rd / "plan.json")
    res = read_json(rd / "results.json")
    branch = a.branch or cfg.integration_branch
    wt = cfg.state / "worktrees" / plan["run_id"] / "_integration"
    if not wt.exists():
        git(cfg.repo, "worktree", "add", "-q", "-B", branch, str(wt), plan["base_sha"])
    included, skipped = [], []
    gitc = ["git", "-C", str(wt), "-c", f"user.name={cfg.author_name}", "-c", f"user.email={cfg.author_email}"]
    for r in res["variants"]:
        v = next(x for x in plan["variants"] if x["id"] == r["id"])
        ok = r.get("acceptance", {}).get("passed", False)
        if not ok and not a.include_failed:
            skipped.append(r["id"])
            continue
        files = [f for f in r["diff"]["owned_files"]
                 if sh(["git", "-C", str(wt), "cat-file", "-e", f"{v['branch']}:{f}"], check=False).returncode == 0]
        if not files:
            skipped.append(r["id"])
            continue
        # Only the variant's own paths come over. Out-of-scope edits stay on its branch.
        sh(["git", "-C", str(wt), "checkout", v["branch"], "--", *files])
        sh(gitc + ["commit", "-q", "-m",
                   f"feat({plan['feature']}): add variant {r['id']} ({r['short']}, angle: {r['angle'] or 'free'})\n\n"
                   f"From {v['branch']} @ {r['status'].get('head', '?')}. Model: {r['model']}."], check=False)
        included.append(r["id"])
    combined = None
    if cfg.acceptance_cmd and included:
        ids = ",".join(included)
        p = sh(cfg.acceptance_cmd.replace("{id}", ids), cwd=wt, check=False,
               env=dict(os.environ, VW_VARIANT=ids), timeout=1800)
        (rd / "integration-acceptance.log").write_text(p.stdout + p.stderr, encoding="utf-8")
        combined = p.returncode == 0
    report = rd / "report.md"
    head = git(wt, "rev-parse", "--short", "HEAD")
    write_json(rd / "integration.json", {"branch": branch, "worktree": str(wt), "head": head,
                                         "included": included, "skipped": skipped, "combined_passed": combined})
    if report.exists():
        cmd_compare(cfg, a)
        shutil.copy(report, wt / f"VARIANTS-{slug(plan['feature'])}.md")
        sh(gitc + ["add", f"VARIANTS-{slug(plan['feature'])}.md"], check=False)
        sh(gitc + ["commit", "-q", "-m", f"docs({plan['feature']}): A/B comparison report for {plan['run_id']}"],
           check=False)
    if cfg.push:
        sh(["git", "-C", str(wt), "push", "-q", "-u", cfg.remote, branch], check=False)
    print(f"integration branch {branch}: included {included}, skipped {skipped}, combined acceptance: {combined}")


# --------------------------------------------------------------------------- misc
def cmd_status(cfg: Config, a) -> None:
    rd = run_dir(cfg, a.run_id)
    plan = read_json(rd / "plan.json")
    for v in plan["variants"]:
        f = rd / v["id"] / "status.json"
        st = read_json(f) if f.exists() else {}
        print(f"{v['id']} {v['model']:<40} rc={st.get('rc', '-')} attempts={st.get('attempts', '-')} head={st.get('head', '-')}")
    fl = rd / "failures.log"
    if fl.exists() and fl.stat().st_size:
        print(f"\nfailures.log ({fl}):\n" + fl.read_text(encoding="utf-8")[-2000:])


def cmd_clean(cfg: Config, a) -> None:
    rd = run_dir(cfg, a.run_id)
    plan = read_json(rd / "plan.json")
    for v in plan["variants"] + [{"worktree": str(cfg.state / "worktrees" / plan["run_id"] / "_integration")}]:
        if Path(v["worktree"]).exists():
            git(cfg.repo, "worktree", "remove", "--force", v["worktree"], check=False)
    git(cfg.repo, "worktree", "prune", check=False)
    print("worktrees removed (branches kept)")


def cmd_doctor(cfg: Config, a) -> None:
    ok = True
    print(f"config   {cfg.path}\nrepo     {cfg.repo}\nfeature  {cfg.feature}\nowned    {cfg.owned}")
    harnesses = {cfg.harness} | {m.get("harness") for m in cfg.models if m.get("harness")}
    for h in sorted(x for x in harnesses if x):
        ad = VW_HOME / "adapters" / f"{h}.sh"
        if not ad.exists():
            print(f"[x] adapter {h}: missing"); ok = False; continue
        meta = adapter_meta(ad)
        for b in meta["requires"]:
            found = shutil.which(b)
            if not found and b == "opencode":
                cand = os.environ.get("OPENCODE_BIN") or os.path.expanduser("~/.opencode/bin/opencode")
                found = cand if os.path.exists(cand) else None
            print(f"[{'ok' if found else 'x'}] adapter {h}: needs `{b}` -> {found or 'not on PATH'}")
            ok &= bool(found)
    if "opencode" in harnesses:
        bin_ = os.environ.get("OPENCODE_BIN") or shutil.which("opencode") or os.path.expanduser("~/.opencode/bin/opencode")
        if os.path.exists(bin_):
            listed = set(sh([bin_, "models"], check=False, timeout=60).stdout.split())
            for m in cfg.models:
                if m.get("harness", cfg.harness) != "opencode":
                    continue
                hit = m["id"] in listed
                print(f"[{'ok' if hit else 'x'}] model {m['id']}: "
                      f"{'available' if hit else 'NOT listed by `opencode models` (unknown id, or hidden by a provider whitelist in opencode.jsonc)'}")
                ok &= hit
    print("doctor: " + ("all good" if ok else "problems found"))
    sys.exit(0 if ok else 1)


def cmd_all(cfg: Config, a) -> None:
    cmd_plan(cfg, a)
    a.run_id = None
    for f in (cmd_spawn, cmd_run, cmd_collect, cmd_compare, cmd_integrate):
        f(cfg, a)


def main() -> None:
    ap = argparse.ArgumentParser(prog="vw", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default=os.environ.get("VW_CONFIG", "variance.toml"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "spawn", "run", "collect", "compare", "integrate", "status", "clean", "doctor", "all"):
        s = sub.add_parser(name)
        s.add_argument("--run-id", dest="run_id", default=None)
        if name in ("run", "all"):
            s.add_argument("--only", default="", help="comma-separated variant ids")
        if name in ("integrate", "all"):
            s.add_argument("--branch", default=None)
            s.add_argument("--include-failed", action="store_true")
    a = ap.parse_args()
    cfg = Config(Path(a.config))
    globals()[f"cmd_{a.cmd}"](cfg, a)


if __name__ == "__main__":
    main()

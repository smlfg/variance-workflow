"""Self-tests for vw: pure helpers plus a full stub dry run of the demo target. Stdlib only, offline."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("vw", ROOT / "bin/vw.py")
vw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vw)


class Helpers(unittest.TestCase):
    def test_is_owned(self):
        pats = ["src/pkg/variants/v_a/", "tests/variants/test_v_a*.py"]
        self.assertTrue(vw.is_owned("src/pkg/variants/v_a/__init__.py", pats))
        self.assertTrue(vw.is_owned("tests/variants/test_v_a_extra.py", pats))
        self.assertFalse(vw.is_owned("src/pkg/variants/v_b/__init__.py", pats))
        self.assertFalse(vw.is_owned("README.md", pats))

    def test_render_leaves_unknown(self):
        self.assertEqual(vw.render("{{a}} {{ b }} {{zz}}", {"a": "1", "b": "2"}), "1 2 {{zz}}")

    def test_parse_counts(self):
        self.assertEqual(vw.parse_counts("Ran 5 tests in 0.1s\nFAILED (failures=2, errors=1)"),
                         {"total": 5, "failed": 2, "errors": 1})
        self.assertEqual(vw.parse_counts("3 passed, 1 failed in 0.2s")["passed"], 3)


class EnvScrub(unittest.TestCase):
    def test_no_secrets_reach_the_model(self):
        with tempfile.TemporaryDirectory() as d:
            cfgp = Path(d) / "c.toml"
            cfgp.write_text('[feature]\nname="f"\nowned=["x/{id}/"]\n[[models]]\nid="m"\n'
                            '[runner]\npass_env=["MY_HARNESS_KEY"]\n', encoding="utf-8")
            cfg = vw.Config(cfgp)
            old = dict(os.environ)
            os.environ.update({"GH_TOKEN": "x", "GITHUB_TOKEN": "x", "OPENAI_API_KEY": "x", "AWS_SECRET": "x",
                               "MY_HARNESS_KEY": "ok", "RANDOM_VAR": "x"})
            try:
                env = vw.model_env(cfg, Path(d), {"id": "a", "worktree": d, "model": "m", "angle": ""},
                                   Path(d) / "p.md", [])
            finally:
                os.environ.clear()
                os.environ.update(old)
            for k in ("GH_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "AWS_SECRET", "RANDOM_VAR"):
                self.assertNotIn(k, env)
            self.assertEqual(env["MY_HARNESS_KEY"], "ok")  # explicit opt-in only
            self.assertEqual(env["GH_CONFIG_DIR"], "/nonexistent")
            self.assertEqual(Path(env["GIT_CONFIG_GLOBAL"]).read_text(), "")  # no credential helpers
            self.assertNotEqual(env.get("HOME"), d)  # HOME is passed through, never re-exported


class Timeout(unittest.TestCase):
    def test_timeout_kills_process_group(self):
        with tempfile.TemporaryDirectory() as d:
            cfgp = Path(d) / "c.toml"
            cfgp.write_text('[feature]\nname="f"\nowned=["x/{id}/"]\n[[models]]\nid="m"\n[runner]\ntimeout_s=1\n',
                            encoding="utf-8")
            cfg = vw.Config(cfgp)
            ad = Path(d) / "slow.sh"
            ad.write_text("sleep 30 & sleep 30\n", encoding="utf-8")
            fl = Path(d) / "failures.log"
            rc = vw.invoke(cfg, ad, dict(os.environ), d, Path(d) / "run.log", fl, "t")
            self.assertEqual(rc, 124)
            self.assertIn("TIMEOUT tag=t", fl.read_text())


class DemoDryRun(unittest.TestCase):
    def test_demo_end_to_end(self):
        p = subprocess.run([str(ROOT / "examples/demo/run-demo.sh")], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=300)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        run = (ROOT / ".vw/demo/runs/latest").resolve()
        res = json.loads((run / "results.json").read_text())
        by = {r["id"]: r for r in res["variants"]}
        self.assertEqual(sorted(by), list("abcde"))
        for vid in "abcd":
            self.assertTrue(by[vid]["acceptance"]["passed"], vid)
        self.assertFalse(by["e"]["acceptance"]["passed"])           # non-idempotent stub
        self.assertEqual(by["c"]["status"]["attempts"], 2)          # retried once, same worktree
        self.assertTrue(by["c"]["status"]["wip_commit"])            # wrapper committed for it
        self.assertEqual(by["d"]["diff"]["out_of_scope"], ["README.md"])
        integ = json.loads((run / "integration.json").read_text())
        self.assertEqual(integ["included"], list("abcd"))
        self.assertTrue(integ["combined_passed"])
        tgt = ROOT / ".vw/demo/target"
        readme = subprocess.run(["git", "-C", str(tgt), "show", "variants/slugify:README.md"],
                                capture_output=True, text=True).stdout
        self.assertNotIn("best one", readme)                        # out-of-scope edit not integrated
        authors = set(subprocess.run(["git", "-C", str(tgt), "log", "--format=%an <%ae>", "variants/slugify"],
                                     capture_output=True, text=True).stdout.splitlines())
        self.assertEqual(authors, {"Samuel Fleig (via Agent) <186922365+smlfg@users.noreply.github.com>"})
        self.assertIn("FAIL tag=", (run / "failures.log").read_text())
        report = (run / "report.md").read_text()
        for h in ("## Behaviour differences", "## Model personality notes", "## Integration"):
            self.assertIn(h, report)
        prompt = (run / "a" / "prompt.md").read_text()
        self.assertIn("v_a", prompt)
        self.assertNotIn("{id}", prompt)
        self.assertIn("Your assigned design angle", prompt)


if __name__ == "__main__":
    unittest.main()

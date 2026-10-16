#!/usr/bin/env python3
"""Stub "model" for dry runs of the demo target. No LLM, no network.

Reads VW_VARIANT / VW_ANGLE / VW_PROMPT_FILE like a real harness would and writes a
canned variant package. Deliberately exercises the workflow's edge cases:
  a  commits itself, German transliteration
  b  commits itself, keeps Unicode letters
  c  fails on the first attempt (tests retry on the same worktree), then minimal regex
  d  word-aware, but also edits README.md (tests the scope check; edit is not integrated)
  e  short slug + hash suffix: NOT idempotent, fails acceptance (tests "not kept")
"""
import os
import subprocess
import sys
from pathlib import Path

vid = os.environ["VW_VARIANT"]
angle = os.environ.get("VW_ANGLE", "")
model = os.environ.get("VW_MODEL", "stub")
wt = Path(os.environ["VW_WORKTREE"])
prompt = Path(os.environ["VW_PROMPT_FILE"])
assert prompt.read_text(encoding="utf-8").strip(), "empty prompt"
print(f"[stub] variant={vid} model={model} angle={angle!r} prompt={len(prompt.read_text())} chars")

IMPL = {
"a": ('German-aware transliteration (ä->ae, ß->ss) then ASCII', '''
import re
import unicodedata

_MAP = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss", "&": " und "})


def slugify(text: str) -> str:
    """Transliterate German umlauts first, then strip the remaining accents."""
    if not any(ch.isalnum() for ch in text):
        return ""
    t = unicodedata.normalize("NFKD", text.translate(_MAP)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:80].strip("-")
'''),
"b": ('Unicode-preserving: keep letters of any script, casefold', '''
import re
import unicodedata


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFC", text).casefold()
    t = re.sub(r"[\\W_]+", "-", t)
    return t.strip("-")[:80].strip("-")
'''),
"c": ('Minimal: one regex over NFKD-ASCII, nothing clever', '''
import re
import unicodedata


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return "-".join(re.findall(r"[a-z0-9]+", t))[:80].strip("-")
'''),
"d": ('Word-aware: symbols become words, filler words dropped, cut at a word boundary', '''
import re
import unicodedata

SYMBOLS = {"&": " and ", "@": " at ", "%": " percent ", "+": " plus "}
FILLER = {"the", "a", "an", "of", "der", "die", "das", "le", "la", "l"}


def slugify(text: str) -> str:
    """Readable slugs: meaning over fidelity."""
    if not any(ch.isalnum() for ch in text):
        return ""
    for k, v in SYMBOLS.items():
        text = text.replace(k, v)
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    words = [w for w in re.findall(r"[a-z0-9]+", t) if w not in FILLER]
    out = ""
    for w in words:  # never cut inside a word
        cand = f"{out}-{w}" if out else w
        if len(cand) > 80:
            break
        out = cand
    return out
'''),
"e": ('Stable ids: first three words plus a short hash for uniqueness', '''
import hashlib
import re
import unicodedata


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", t)
    if not words:
        return ""
    return "-".join(words[:3]) + "-" + hashlib.sha1(text.encode()).hexdigest()[:6]
'''),
}

summary, body = IMPL.get(vid, IMPL["c"])

# c: fail once, then succeed on the retry (marker lives in the run dir, not the repo)
marker = prompt.parent / ".stub_failed_once"
if vid == "c" and not marker.exists():
    marker.write_text("1")
    print("[stub] simulated crash on first attempt", file=sys.stderr)
    sys.exit(1)

pkg = wt / "src/textkit/slugify/variants" / f"v_{vid}"
pkg.mkdir(parents=True, exist_ok=True)
meta = {"id": vid, "angle": angle, "model": model, "summary": summary}
(pkg / "__init__.py").write_text(f'"""Variant {vid}: {summary}."""\n' + body + f"\n\nVARIANT = {meta!r}\n",
                                 encoding="utf-8")
(pkg / "VARIANT_NOTES.md").write_text(
    f"# Variant {vid}\n\nApproach: {summary}.\n\nTrade-offs: stub output, written for the dry run.\n", encoding="utf-8")

if vid == "d":
    with open(wt / "README.md", "a", encoding="utf-8") as f:
        f.write("\nVariant d is the best one!\n")  # out of scope on purpose

if vid in ("a", "b", "d"):
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"feat(slugify): variant {vid} [{vid}/{model.split('/')[-1]}]"],
                   cwd=wt, check=True)
print("[stub] done")

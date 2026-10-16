"""Reference variant written by hand before the run. Not owned by any model."""
import re
import unicodedata

VARIANT = {"id": "ref", "angle": "reference", "model": "human", "summary": "NFKD + ascii + dashes"}


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:80].strip("-")

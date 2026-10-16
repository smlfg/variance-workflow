"""slugify feature with a variant registry.

Each variant is a package `textkit.slugify.variants.v_<id>` that exposes
`slugify(text: str) -> str` and a `VARIANT` dict (id, angle, model, summary).
Variants are discovered at import time; adding one never touches this file,
so parallel variant branches never conflict here.
"""
from __future__ import annotations

import importlib
import os
import pkgutil
from types import ModuleType

from . import variants as _variants_pkg

ENV = "TEXTKIT_SLUGIFY"
DEFAULT = "ref"


def available() -> dict[str, ModuleType]:
    found: dict[str, ModuleType] = {}
    for info in pkgutil.iter_modules(_variants_pkg.__path__):
        if info.name.startswith("v_"):
            mod = importlib.import_module(f"{_variants_pkg.__name__}.{info.name}")
            if callable(getattr(mod, "slugify", None)):
                found[info.name[2:]] = mod
    return found


def get(variant: str | None = None) -> ModuleType:
    name = variant or os.environ.get(ENV) or DEFAULT
    mods = available()
    if name not in mods:
        raise KeyError(f"unknown slugify variant {name!r}; available: {sorted(mods)}")
    return mods[name]


def slugify(text: str, variant: str | None = None) -> str:
    return get(variant).slugify(text)

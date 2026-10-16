# Feature: slugify

Turn arbitrary user text (titles, names, mixed languages) into a URL slug.

## Hard contract (checked by tests/acceptance, do not edit those tests)
- `slugify(text: str) -> str`, pure and deterministic.
- Output is lowercase (`s == s.lower()`), contains no whitespace, no leading or trailing `-`, no `--`.
- At most 80 characters.
- Idempotent: `slugify(slugify(x)) == slugify(x)`.
- Input that has no letters or digits gives `""`.
- Plain ASCII words survive: `"Hello World"` contains `hello` and `world`.

## Open on purpose (this is where variants should differ)
- What happens to non-ASCII letters (transliterate, keep, drop)?
- Do symbols carry meaning (`&` -> `and`/`und`, `@` -> `at`, `%` -> `percent`)?
- Long input: hard cut, cut at a word boundary, drop filler words?
- Separators, apostrophes, digits, CJK text.

## Packaging
Your variant is the package `src/textkit/slugify/variants/v_<id>/` with
`__init__.py` exporting `slugify` and a `VARIANT` dict:
`{"id": "<id>", "angle": "...", "model": "...", "summary": "<one line>"}`.
No new third-party dependencies (stdlib only).

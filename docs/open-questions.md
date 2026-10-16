# Open design questions

1. **Coexistence mode in the target repo.** Registry + plugin directory (default), feature flag,
   top-level `variants/<id>/` directories, or branches only? Depends on whether variants differ in
   one function, in architecture, or in UI. See docs/integration.md.
2. **Who builds the seam?** The registry and the shared acceptance tests have to exist before the
   run. Human, one dedicated model run, or a "phase 0" in `vw`?
3. **Failing variants.** Drop them (default), integrate them behind `--include-failed` marked
   experimental, or give them one repair run with the failing test output?
4. **Near-duplicates.** When two variants are > 0.8 similar, automatically re-roll one with a
   sharper angle, or just report it?
5. **Angles: assigned or free?** Assigned angles guarantee spread; free choice shows each model's
   real "personality". Mix (e.g. 3 assigned, 2 free)?
6. **Sibling awareness.** Parallel and blind (default), or sequential where later models see the
   approach lines of earlier ones and must differ?
7. **Same model, several angles?** Useful when only one or two free models are reliable.
8. **Default variant.** Which variant does the registry pick when nothing is selected: the
   reference, the first passing one, or a configured one?
9. **Long-term life of variants.** Keep all forever, or prune after real usage data (A/B flag)?
   Who maintains five implementations when the contract changes?
10. **Personality notes.** Heuristics only (current), plus an LLM judge pass over all diffs, plus
    your own column in the report?
11. **Where it lives.** Standalone public repo (`smlfg/variance-workflow`), or a folder inside
    the target repo?

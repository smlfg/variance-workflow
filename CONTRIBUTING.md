# Contributing

- Stdlib only (Python 3.11+), bash for adapters.
- `python3 -m unittest discover -s tests` must pass; it includes a full stub dry run.
- New harness: add `adapters/<name>.sh` following docs/adapters.md and mark it untested until a real run worked.
- Small commits, one topic each.

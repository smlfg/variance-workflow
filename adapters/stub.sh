#!/usr/bin/env bash
# Adapter: stub harness for dry runs. No model, no network: writes a canned variant
# for the demo target based on VW_VARIANT/VW_ANGLE. Used by `examples/demo/run-demo.sh`.
# vw-requires: python3
set -euo pipefail
exec python3 "$VW_HOME/adapters/stub_model.py"

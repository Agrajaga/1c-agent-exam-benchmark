#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec python3.12 tools/serve_result_site.py "$@"

#!/bin/sh
# Starts the local stand and opens http://127.0.0.1:8879/. Needs Python 3.11+.
cd "$(dirname "$0")"
for py in .venv/bin/python python3.13 python3.12 python3.11 python3; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    exec "$py" -X utf8 tools/start_demo.py
  fi
done
echo "Python 3.11+ is required: brew install python@3.12 (macOS) or sudo apt install python3 (Linux)" >&2
exit 1

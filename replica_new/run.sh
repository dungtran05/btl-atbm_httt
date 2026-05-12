#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

if [[ ! -f .env ]]; then
  echo "Warning: missing .env — create one (see replica_new/.env in repo)."
fi

exec python app.py

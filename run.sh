#!/usr/bin/env bash
# Convenience launcher for the HealthGMP chatbot.
#   ./run.sh           → set up venv, install deps, run the Streamlit app
#   ./run.sh test      → run the unit + offline e2e tests (no API key needed)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install -q -r requirements.txt

if [ "${1:-}" = "test" ]; then
  python -m pytest -q
else
  streamlit run app.py
fi

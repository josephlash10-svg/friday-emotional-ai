#!/usr/bin/env sh
# Start Friday on Linux or macOS (the RUN.bat of these systems). Usage: ./run.sh
cd "$(dirname "$0")" || exit 1
if [ ! -x venv/bin/python ]; then
  echo "No Python environment yet. Run the setup in README.md first:"
  echo "  python3 -m venv venv && venv/bin/pip install -r requirements.txt && venv/bin/python scripts/download_models.py"
  exit 1
fi
venv/bin/python -u src/friday.py "$@"
echo
echo "Friday has stopped."

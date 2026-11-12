#!/bin/sh
# Starts the app (port 8501) and the endpoint for the discrepancy checker (port 8000).
set -e
DATA="${EVAL_DATA_DIR:-/app}"
if [ "$DATA" != "/app" ] && [ ! -d "$DATA/answer_key" ]; then
  echo "First start: copying the answer key, baselines, reviews and data rooms to $DATA"
  mkdir -p "$DATA"
  for d in answer_key submissions reviews data_room judge reports; do
    [ -d "/app/$d" ] && cp -r "/app/$d" "$DATA/"
  done
fi
if [ -z "$EVAL_APP_PASSWORD" ] || [ -z "$EVAL_API_KEY" ]; then
  echo "Refusing to start: set EVAL_APP_PASSWORD and EVAL_API_KEY. The answer key must not be open to everyone."
  exit 1
fi
python -m eval serve --host 0.0.0.0 --port 8000 &
exec streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false

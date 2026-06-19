#!/bin/sh
set -eu

cd /app

child_pid=""
stopping=0

terminate() {
  stopping=1
  if [ -n "$child_pid" ]; then
    kill -TERM "$child_pid" 2>/dev/null || true
  fi
}

trap terminate INT TERM

while [ "$stopping" -eq 0 ]; do
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
  child_pid="$!"

  set +e
  wait "$child_pid"
  status="$?"
  set -e

  child_pid=""

  if [ "$stopping" -eq 1 ]; then
    exit "$status"
  fi

  if [ "$status" -eq 0 ]; then
    echo "YKS server exited cleanly, restarting..."
    sleep 2
    continue
  fi

  echo "YKS server exited with status $status"
  exit "$status"
done

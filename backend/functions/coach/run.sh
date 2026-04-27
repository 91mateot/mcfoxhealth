#!/bin/bash
# Entrypoint for Lambda Web Adapter.
# The adapter (AWS_LAMBDA_EXEC_WRAPPER=/opt/bootstrap) will start this,
# then proxy the Function URL (RESPONSE_STREAM mode) to uvicorn on $PORT.
# Use `python -m uvicorn` because pip installs the `uvicorn/` package next
# to our code at /var/task, which shadows the uvicorn console script on PATH.
exec python -m uvicorn app:app --host 0.0.0.0 --port "${PORT:-8080}" --no-access-log

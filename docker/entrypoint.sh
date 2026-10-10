#!/bin/sh
set -e
python /app/docker/configure.py
if [ "${DZOMDU_REQUIRE_CUDA:-0}" = "1" ]; then
    python /app/docker/check_gpu.py
fi
exec "$@"

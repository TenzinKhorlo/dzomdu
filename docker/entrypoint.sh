#!/bin/sh
set -e
python /app/docker/configure.py
exec "$@"

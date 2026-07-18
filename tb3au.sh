#!/bin/sh
# Daily joke render for the tb3au e-ink clock (invoked by cron; see README §5).
# Portable: resolves the repo root from this script's own location, so the
# cron entry can point at any path the repo is cloned to.
DIR="$(cd "$(dirname "$0")" && pwd)"
python "$DIR/tb3au.py"

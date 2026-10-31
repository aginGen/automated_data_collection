#!/bin/sh
exec python3 "$(dirname "$(realpath "$0")")/launch.py" "$@"

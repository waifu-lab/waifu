#!/bin/sh
set -e

if command -v uv >/dev/null 2>&1; then
    uv tool install waifu-ai
elif command -v pip >/dev/null 2>&1; then
    pip install waifu-ai
elif command -v pip3 >/dev/null 2>&1; then
    pip3 install waifu-ai
else
    echo "Error: neither uv nor pip found. Please install Python first." >&2
    exit 1
fi

echo "waifu installed. Run 'waifu init' to get started."

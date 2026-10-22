#!/bin/sh
set -e

if command -v uv >/dev/null 2>&1; then
    uv tool install waifucore
elif command -v pip >/dev/null 2>&1; then
    pip install waifucore
elif command -v pip3 >/dev/null 2>&1; then
    pip3 install waifucore
else
    echo "Error: neither uv nor pip found. Please install Python first." >&2
    exit 1
fi

if command -v waifu >/dev/null 2>&1; then
    waifu completion install || echo "Run 'waifu completion install <shell>' to enable tab completion."
else
    echo "Open a new terminal and run 'waifu completion install' to enable tab completion."
fi

echo "waifu installed. Run 'waifu init' to get started."

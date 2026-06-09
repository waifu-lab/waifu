#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv tool install waifu-ai
} elseif (Get-Command pip -ErrorAction SilentlyContinue) {
    pip install waifu-ai
} elseif (Get-Command pip3 -ErrorAction SilentlyContinue) {
    pip3 install waifu-ai
} else {
    Write-Error "Neither uv nor pip found. Please install Python first."
    exit 1
}

Write-Host "waifu installed. Run 'waifu init' to get started."

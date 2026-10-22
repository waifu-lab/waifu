#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv tool install waifucore
} elseif (Get-Command pip -ErrorAction SilentlyContinue) {
    pip install waifucore
} elseif (Get-Command pip3 -ErrorAction SilentlyContinue) {
    pip3 install waifucore
} else {
    Write-Error "Neither uv nor pip found. Please install Python first."
    exit 1
}

if (Get-Command waifu -ErrorAction SilentlyContinue) {
    waifu completion install powershell
} else {
    Write-Host "Open a new terminal and run 'waifu completion install' to enable tab completion."
}

Write-Host "waifu installed. Run 'waifu init' to get started."

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt

if (-not (Test-Path ".env")) {
    Write-Host "Canh bao: Khong co file .env trong thu muc replica - hay tao hoac copy tu repo."
}

python app.py

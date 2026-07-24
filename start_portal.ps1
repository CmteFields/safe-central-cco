$ErrorActionPreference = 'Stop'

if (-not $env:GEMINI_API_KEY) {
    $env:GEMINI_API_KEY = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'User')
}

if (-not $env:GEMINI_API_KEY) {
    Write-Warning 'GEMINI_API_KEY não configurada. Instrutores funcionará normalmente; consultas com IA usarão o índice local.'
}

$portalRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $portalRoot
Start-Process 'http://127.0.0.1:8765/'
Write-Host 'Central CCO iniciada em http://127.0.0.1:8765/' -ForegroundColor Green
Write-Host 'Mantenha esta janela aberta. Pressione Ctrl+C para encerrar.'
python backend/server.py

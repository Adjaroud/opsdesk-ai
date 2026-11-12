param([int]$ApiPort = 18000, [int]$UiPort = 8501)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
. (Join-Path $PSScriptRoot 'load-env.ps1')
$demoPython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $demoPython)) {
    throw 'Environnement absent. Suivez les commandes du README pour installer Python.'
}
& $demoPython -m app.seed
if ($LASTEXITCODE -ne 0) { throw 'Initialisation impossible.' }
if (Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $ApiPort occupe. Arretez votre ancienne demo ou utilisez -ApiPort 18001."
}
if (Get-NetTCPConnection -LocalPort $UiPort -State Listen -ErrorAction SilentlyContinue) {
    throw "Port UI $UiPort occupe. Arretez votre ancienne demo ou utilisez -UiPort 8502."
}
$previousApiUrl = $env:OPSDESK_API_URL
$env:OPSDESK_API_URL = "http://127.0.0.1:$ApiPort"
$apiProcess = Start-Process -FilePath $demoPython -ArgumentList @('-m', 'uvicorn', 'app.api:app', '--host', '127.0.0.1', '--port', "$ApiPort") -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru
try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if ($apiProcess.HasExited) { throw "Backend arrete : verifiez que le port $ApiPort est libre." }
        try {
            $health = Invoke-RestMethod "$env:OPSDESK_API_URL/health" -TimeoutSec 2
            if ($health.status -eq 'ok' -and $health.demo) { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw 'Backend indisponible apres le demarrage.' }
    Write-Host "Demo : http://127.0.0.1:$UiPort - Ctrl+C pour arreter."
    & $demoPython -m streamlit run app/ui.py --server.address 127.0.0.1 --server.port $UiPort --server.headless true --browser.gatherUsageStats false
} finally {
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $($apiProcess.Id)" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
    if (-not $apiProcess.HasExited) { Stop-Process -Id $apiProcess.Id }
    $env:OPSDESK_API_URL = $previousApiUrl
}

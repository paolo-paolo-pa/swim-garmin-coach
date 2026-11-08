param([int]$Port=8766, [switch]$NoBrowser)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskPython=Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path (Join-Path $taskRoot 'frontend\.output\public\index.html'))) {
    throw 'Compila prima il frontend: cd frontend; npm ci; npm run build'
}
try {
    $taskResponse=Invoke-WebRequest "http://127.0.0.1:$Port/api/platform/summary?days=7" -TimeoutSec 3
    if ($taskResponse.StatusCode -eq 200) {
        if (-not $NoBrowser) {Start-Process "http://127.0.0.1:$Port/"}
        Write-Output "Dashboard già avviata: http://127.0.0.1:$Port/"
        return
    }
} catch {}
$taskArgs=@('-m','uvicorn','garmin_coach.app.server:app','--host','127.0.0.1','--port',"$Port",'--log-level','warning')
$taskProcess=Start-Process -FilePath $taskPython -ArgumentList $taskArgs -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskRoot 'data\dashboard.stdout.log') -RedirectStandardError (Join-Path $taskRoot 'data\dashboard.stderr.log')
Set-Content -LiteralPath (Join-Path $taskRoot 'data\dashboard.pid') -Value $taskProcess.Id
if (-not $NoBrowser) {Start-Process "http://127.0.0.1:$Port/"}
Write-Output "Dashboard avviata: http://127.0.0.1:$Port/ (PID $($taskProcess.Id))"

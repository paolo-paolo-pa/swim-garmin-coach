$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskPidFile=Join-Path $taskRoot 'data\dashboard.pid'
if (-not (Test-Path $taskPidFile)) {Write-Output 'Nessun PID registrato. Per il comando in primo piano usa Ctrl+C.';return}
$taskProcessId=[int](Get-Content -LiteralPath $taskPidFile)
$taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$taskProcessId"
if ($taskProcess -and $taskProcess.CommandLine -match 'uvicorn garmin_coach.app.server:app') {
    # Il launcher Python del virtualenv Windows può avere un figlio reale.
    $taskChildren=Get-CimInstance Win32_Process -Filter "ParentProcessId=$taskProcessId"
    foreach($taskChild in $taskChildren) {
        if ($taskChild.CommandLine -match 'uvicorn garmin_coach.app.server:app') {
            Stop-Process -Id $taskChild.ProcessId -ErrorAction SilentlyContinue
        }
    }
    Stop-Process -Id $taskProcessId -ErrorAction SilentlyContinue
    Write-Output 'Dashboard arrestata.'
} else {Write-Output 'Il processo registrato non è la dashboard: nessun processo arrestato.'}

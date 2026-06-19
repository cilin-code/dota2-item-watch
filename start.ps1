$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runDir = Join-Path $root ".run"
$pidFile = Join-Path $runDir "cmd.pid"

if (-not (Test-Path $runDir)) {
    New-Item -ItemType Directory -Path $runDir | Out-Null
}

$currentCmdPid = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId

if (Test-Path $pidFile) {
    $oldCmdPid = (Get-Content $pidFile -Raw).Trim()
    if ($oldCmdPid -match '^\d+$' -and [int]$oldCmdPid -ne [int]$currentCmdPid) {
        Stop-Process -Id ([int]$oldCmdPid) -Force
    }
}

Set-Content -Path $pidFile -Value $currentCmdPid -Encoding ASCII

Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force
}
Start-Sleep -Seconds 1

Set-Location (Join-Path $root "backend")
$host.UI.RawUI.WindowTitle = "Dota 2 Steam Monitor"

Write-Host "========================================"
Write-Host "  Dota 2 Steam Monitor"
Write-Host "  http://localhost:8000"
Write-Host "========================================"
Write-Host ""

Start-Process "http://localhost:8000"
& (Join-Path $root ".venv\Scripts\python.exe") -m uvicorn main:app --host 127.0.0.1 --port 8000

Write-Host ""
Write-Host "Server stopped. Press any key to close this window."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

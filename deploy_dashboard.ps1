$python = "C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Set-Location $root

$existing = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq 'python.exe' -and $_.CommandLine -match 'uvicorn app.dashboard:app'
}

if ($existing) {
  $existing | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Start-Sleep -Seconds 1
}

Start-Process -FilePath $python `
  -ArgumentList "-m", "uvicorn", "app.dashboard:app", "--host", "0.0.0.0", "--port", "8050", "--workers", "1", "--proxy-headers", "--no-access-log", "--log-level", "warning" `
  -WorkingDirectory $root

Write-Host "Dashboard deployed at http://0.0.0.0:8050 (bind)"
Write-Host "Health check: http://127.0.0.1:8050/healthz"

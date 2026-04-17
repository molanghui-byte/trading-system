$python = "C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Set-Location $root

Start-Process -FilePath $python `
  -ArgumentList "-m", "uvicorn", "app.dashboard:app", "--host", "127.0.0.1", "--port", "8050", "--no-access-log", "--log-level", "warning" `
  -WorkingDirectory $root

Start-Process "http://127.0.0.1:8050/"

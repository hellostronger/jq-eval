$env:PYTHONIOENCODING='utf-8'
Set-Location $PSScriptRoot
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 *>&1 | Tee-Object -FilePath (Join-Path $PSScriptRoot 'uvicorn.log') -Append

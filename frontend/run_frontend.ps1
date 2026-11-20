Set-Location $PSScriptRoot
$env:ESBUILD_WORKER_THREADS='1'
& node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3000 *>&1 | Tee-Object -FilePath (Join-Path $PSScriptRoot 'vite.log') -Append

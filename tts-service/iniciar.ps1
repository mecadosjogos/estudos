# Sobe o serviço de TTS local em http://127.0.0.1:8100 -- fica rodando em
# primeiro plano, Ctrl+C pra derrubar. Qualquer script na máquina pode
# chamar POST /synthesize, GET /speakers, GET /healthz -- não é exclusivo
# do worker do Estudos.

$ErrorActionPreference = "Stop"
$serviceDir = $PSScriptRoot
$venvPython = Join-Path $serviceDir ".venv\Scripts\python.exe"

Set-Location $serviceDir
& $venvPython -m uvicorn main:app --host 127.0.0.1 --port 8100

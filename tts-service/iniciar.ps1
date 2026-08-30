# Sobe o serviço de TTS local em http://127.0.0.1:8100 -- fica rodando em
# primeiro plano, Ctrl+C pra derrubar. Qualquer script na máquina pode
# chamar POST /synthesize, GET /speakers, GET /healthz -- não é exclusivo
# do worker do Estudos.

$ErrorActionPreference = "Stop"
$serviceDir = $PSScriptRoot
$venvPython = Join-Path $serviceDir ".venv\Scripts\python.exe"

# XTTS v2 pede aceite dos termos de uso (licença não-comercial, CPML) na
# primeira execução -- essa variável responde "sim" sem interação (senão o
# serviço trava esperando um y/n no terminal, o que quebraria rodar isso
# como serviço em segundo plano). Termos: https://coqui.ai/cpml.txt -- leia
# antes de rodar pela primeira vez.
$env:COQUI_TOS_AGREED = "1"

Set-Location $serviceDir
& $venvPython -m uvicorn main:app --host 127.0.0.1 --port 8100

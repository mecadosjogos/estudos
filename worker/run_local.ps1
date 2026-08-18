# Roda o worker localmente no Windows, apontando as DLLs de CUDA (cuBLAS/cuDNN)
# instaladas via pip para dentro do PATH do processo. Sem isso, faster-whisper
# falha com "cublas64_12.dll is not found" mesmo com a GPU disponível — o pip
# instala as DLLs dentro do venv, mas não registra no PATH do sistema.
#
# Uso: .\worker\run_local.ps1            (drena a fila inteira e sai sozinho)
#      .\worker\run_local.ps1 --once     (processa só um job e sai)
#      .\worker\run_local.ps1 --watch    (fica rodando, pegando job assim que aparecer)
#
# Ou dê dois cliques em worker\transcrever-agora.bat — mesma coisa, sem terminal.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot "server\.venv\Scripts\python.exe"

$cublasDir = Join-Path $repoRoot "server\.venv\Lib\site-packages\nvidia\cublas\bin"
$cudnnDir = Join-Path $repoRoot "server\.venv\Lib\site-packages\nvidia\cudnn\bin"
$env:PATH = "$cublasDir;$cudnnDir;$env:PATH"

Set-Location $repoRoot
& $venvPython -m worker.main @args

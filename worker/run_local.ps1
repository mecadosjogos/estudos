# Roda o worker localmente no Windows, apontando as DLLs de CUDA (cuBLAS/cuDNN)
# instaladas via pip para dentro do PATH do processo. Sem isso, faster-whisper
# falha com "cublas64_12.dll is not found" mesmo com a GPU disponível — o pip
# instala as DLLs dentro do venv, mas não registra no PATH do sistema.
#
# Antes de drenar a fila, o worker também pergunta pro servidor quais aulas
# têm áudio ainda sem transcrição (fora da matéria LIXO) e enfileira sozinho
# -- "etapa 0" do RUNBOOK.md. Não precisa abrir um chat só pra isso.
#
# Uso: .\worker\run_local.ps1            (acha pendente + drena a fila inteira, sai sozinho)
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

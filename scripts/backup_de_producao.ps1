# Baixa o backup mais recente (banco sem a tabela user + mp3 de cada aula)
# da VPS de produção e grava em data-backup/, pronto pra revisar e commitar.
#
# Uso: .\scripts\backup_de_producao.ps1
#      .\scripts\backup_de_producao.ps1 --server-url http://127.0.0.1:8000   (testar local primeiro)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot "server\.venv\Scripts\python.exe"

Set-Location $repoRoot
& $venvPython (Join-Path $repoRoot "scripts\backup_from_vps.py") @args

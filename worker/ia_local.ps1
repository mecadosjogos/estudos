# Liga o ouvinte da IA local das dissertativas (worker/ia_local.py): fica
# rodando, pega na VPS o trabalho de gerar e corrigir dissertativas e
# executa no modelo local (llama.cpp, repositório irmão LlamaCppLocal) --
# ou no Claude CLI, se autorizado nesta máquina. Ctrl+C derruba (e derruba
# junto o llama-server, devolvendo VRAM e RAM).
#
# Uso: .\worker\ia_local.ps1                          (modelo padrão desta máquina, servidor do .env)
#      .\worker\ia_local.ps1 -Modelo gemma4-26b-a4b   (só nesta execução -- pra comparar modelos)
#      .\worker\ia_local.ps1 -Servidor local          (Docker dev em 127.0.0.1:8000)
#      .\worker\ia_local.ps1 -Servidor vps            (SERVER_URL do .env, produção)
#
# Autorizar/revogar o Claude, gravar o modelo padrão desta máquina:
#      .\worker\ia_local.ps1 -Comando autorizar-claude -Horas 3
#      .\worker\ia_local.ps1 -Comando revogar-claude
#      .\worker\ia_local.ps1 -Comando usar-modelo -Modelo gpt-oss-20b
#      .\worker\ia_local.ps1 -Comando status

param(
	[string]$Modelo = "",
	[ValidateSet("", "vps", "local")][string]$Servidor = "",
	[ValidateSet("", "autorizar-claude", "revogar-claude", "usar-modelo", "status")][string]$Comando = "",
	[double]$Horas = 0
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot "server\.venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"

$argumentos = @("-m", "worker.ia_local")
if ($Comando -eq "usar-modelo") {
	if (-not $Modelo) { throw "usar-modelo precisa de -Modelo <id>" }
	$argumentos += @("usar-modelo", $Modelo)
} elseif ($Comando -eq "autorizar-claude") {
	$argumentos += @("autorizar-claude")
	if ($Horas -gt 0) { $argumentos += @("--horas", "$Horas") }
} elseif ($Comando) {
	$argumentos += @($Comando)
} else {
	if ($Modelo) { $argumentos += @("--modelo", $Modelo) }
	if ($Servidor) { $argumentos += @("--servidor", $Servidor) }
}

Set-Location $repoRoot
& $venvPython @argumentos

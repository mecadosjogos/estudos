# Mantém o ouvinte da IA local (worker/ia_local.py) ligado sem janela --
# é o que a tarefa agendada "Estudos - IA local" roda no logon do Windows
# (ver RUNBOOK.md, "IA local — dissertativas"). Se o ouvinte cair (rede,
# erro inesperado), espera 30 s e sobe de novo. O log fica em
# %LOCALAPPDATA%\Estudos\ia_local.log, fora do OneDrive (não sincroniza
# com o desktop), e é recomeçado quando passa de 5 MB.
#
# Servidor e modelo: os padrões desta máquina (SERVER_URL do .env; modelo
# gravado com `ia_local.ps1 -Comando usar-modelo`).
#
# Uso manual (normalmente não precisa -- a tarefa agendada chama):
#      powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File worker\ia_local_servico.ps1

$ErrorActionPreference = "Continue"
$pasta = Join-Path $env:LOCALAPPDATA "Estudos"
New-Item -ItemType Directory -Force $pasta | Out-Null
$log = Join-Path $pasta "ia_local.log"
$script = Join-Path $PSScriptRoot "ia_local.ps1"

while ($true) {
	if ((Test-Path $log) -and (Get-Item $log).Length -gt 5MB) {
		Move-Item $log "$log.anterior" -Force
	}
	"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] iniciando o ouvinte" | Out-File $log -Append -Encoding utf8
	# Out-File -Encoding utf8, não `*>>`: no PowerShell 5.1 o redirecionamento
	# grava em UTF-16 e o log fica ilegível no Get-Content/editor.
	& $script 2>&1 | ForEach-Object { "$_" } | Out-File $log -Append -Encoding utf8
	"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] o ouvinte saiu (código $LASTEXITCODE); de novo em 30 s" | Out-File $log -Append -Encoding utf8
	Start-Sleep -Seconds 30
}

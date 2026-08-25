# Núcleo compartilhado: dispara uma skill do Claude Code sozinha, sem
# ninguém olhando, com batimento de vida a cada 15s e log em UTF-8
# correto. Usado por processar-aulas.ps1 e transcrever-paginas.ps1 --
# extraído pra um arquivo só depois que um bug de encoding teve que ser
# corrigido nos dois lugares ao mesmo tempo (ver git log): duplicar o
# script inteiro por skill duplica também o próximo bug.
#
# Roda em background (Start-Job) com um "batimento" a cada 15s enquanto
# espera -- `claude -p` em stream-json ainda assim buferiza tudo até o
# processo terminar quando a saída passa por um pipe do PowerShell (não é
# um console de verdade), então tentar mostrar progresso "ao vivo"
# analisando o stream evento a evento não é confiável. O batimento existe
# porque, sem ele, minutos de silêncio pareceram trava e já fizeram
# fechar a janela no meio de um processamento real.
#
# --dangerously-skip-permissions: decisao explicita do usuario -- sem
# isso, cada chamada de ferramenta pediria confirmacao que ninguem
# estaria ali pra dar. Cada skill que usa este script precisa ser
# contida por conta própria (nunca aceitar proposta sozinha -- isso fica
# pra revisao humana em /aprovacao, mesmo rodando contra a VPS de
# producao via SERVER_URL no .env).
#
# NAO usa --bare: bare mode nao le OAuth/keychain, e este projeto usa a
# assinatura do Claude Code (login normal), nunca ANTHROPIC_API_KEY.
#
# Sempre --model opus: nunca herda o modelo padrao da sessao (PLANO.md).
#
# Encoding: tudo em UTF-8 explicito -- o padrão do PowerShell 5.1 pra
# redirecionamento é UTF-16/ANSI dependendo do cmdlet, e isso corrompeu
# acento em teste real desta automação (mesma família de bug do "curl
# com argumento inline" já documentada no RUNBOOK.md, só que aqui do
# lado do PowerShell). `$OutputEncoding` precisa ser fixado DE NOVO
# dentro do Start-Job porque ele roda num processo/runspace à parte, que
# não herda o do script de fora.

param(
	[Parameter(Mandatory = $true)][string]$Skill,
	[string]$Alvo = "",
	[Parameter(Mandatory = $true)][string]$LogPrefix,
	[Parameter(Mandatory = $true)][string]$MensagemFinal,
	[string]$TempoTipico = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Carimbo {
	return (Get-Date -Format "HH:mm:ss")
}

# Mesma variavel que worker/config.py ja usa -- ausente/vazio cai no Docker
# local (maquina nova, sem VPS configurada ainda); presente no .env (caso
# de hoje, ja apontando pra producao) usa a VPS. Sem isso o script sempre
# checava 127.0.0.1:8000, entao numa maquina ja configurada pra falar com
# a VPS ele "achava" que o servidor estava fora do ar.
$envPath = Join-Path $PSScriptRoot ".env"
$serverUrl = "http://127.0.0.1:8000"
if (Test-Path $envPath) {
	$linha = Select-String -Path $envPath -Pattern "^SERVER_URL=(.+)$" -Encoding utf8 -ErrorAction SilentlyContinue | Select-Object -First 1
	if ($linha) { $serverUrl = $linha.Matches[0].Groups[1].Value.Trim() }
}

Write-Host "Verificando se o servidor esta no ar ($serverUrl)..."
try {
	$health = Invoke-WebRequest -Uri "$serverUrl/healthz" -UseBasicParsing -TimeoutSec 10
	if ($health.StatusCode -ne 200) { throw "status $($health.StatusCode)" }
} catch {
	Write-Host ""
	Write-Host "O servidor nao esta respondendo em $serverUrl"
	if ($serverUrl -like "*127.0.0.1*") {
		Write-Host 'Rode primeiro o atalho "Servidor de testes (Estudos)" e tente de novo.'
	} else {
		Write-Host 'Confirme que a VPS esta no ar, ou que SERVER_URL no .env aponta pro lugar certo.'
	}
	Read-Host "Pressione Enter para fechar"
	exit 1
}

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $PSScriptRoot "logs\$LogPrefix-$timestamp.log"
$rawLogFile = Join-Path $PSScriptRoot "logs\$LogPrefix-$timestamp.raw.jsonl"
$prompt = "$Skill $Alvo".Trim()

Write-Host "Servidor no ar. Disparando o Claude Code ($Skill)..."
$sufixoTempo = if ($TempoTipico) { " ($TempoTipico)" } else { "" }
Write-Host "(roda sozinho, sem pedir confirmacao -- avisa a cada 15s que continua vivo$sufixoTempo)"
Write-Host "Log: $logFile"
Write-Host ""

$job = Start-Job -ScriptBlock {
	param($ScriptDir, $Prompt, $RawLogFile)
	[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
	$OutputEncoding = [System.Text.Encoding]::UTF8
	Set-Location $ScriptDir
	& claude -p --dangerously-skip-permissions --model opus --output-format stream-json --verbose -- $Prompt 2>&1 |
		Out-File -FilePath $RawLogFile -Encoding utf8
} -ArgumentList $PSScriptRoot, $prompt, $rawLogFile

$elapsed = 0
while ($job.State -eq "Running") {
	Start-Sleep -Seconds 15
	$elapsed += 15
	Write-Host "[$(Carimbo)] ainda processando... ${elapsed}s decorridos$sufixoTempo"
}

Receive-Job -Job $job -ErrorAction SilentlyContinue | Out-Null
Remove-Job -Job $job

# Le o log bruto (agora completo) e monta o resumo legivel.
$linhas = @()
if (Test-Path $rawLogFile) {
	Get-Content -Path $rawLogFile -Encoding utf8 | ForEach-Object {
		if (-not $_.Trim()) { return }
		try {
			$evento = $_ | ConvertFrom-Json -ErrorAction Stop
		} catch {
			return
		}
		switch ($evento.type) {
			"assistant" {
				foreach ($bloco in $evento.message.content) {
					if ($bloco.type -eq "tool_use") {
						$resumo = if ($bloco.input.description) { $bloco.input.description } else { $bloco.name }
						$linhas += "-> $($bloco.name): $resumo"
					} elseif ($bloco.type -eq "text" -and $bloco.text -and $bloco.text.Trim()) {
						$linhas += $bloco.text
					}
				}
			}
			"result" {
				$linhas += ""
				$linhas += "============================================================"
				if ($evento.is_error) {
					$linhas += " Terminou com erro: $($evento.result)"
				} else {
					$linhas += " Concluido em $([math]::Round($evento.duration_ms / 1000))s."
					$linhas += " $MensagemFinal"
				}
				$linhas += "============================================================"
			}
		}
	}
}

if ($linhas.Count -eq 0) {
	$linhas += "Nenhum evento reconhecido no log bruto -- confira $rawLogFile na mao."
}

$linhas | Out-File -FilePath $logFile -Encoding utf8
$linhas | ForEach-Object { Write-Host $_ }

Write-Host ""
Write-Host "Log legivel: $logFile"
Write-Host "Log bruto (JSON completo, um evento por linha): $rawLogFile"
Write-Host ""
Read-Host "Pressione Enter para fechar"

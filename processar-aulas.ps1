# Wrapper fino em cima de disparar-skill.ps1 -- ver esse arquivo para os
# detalhes (por que PowerShell, por que --dangerously-skip-permissions,
# etc). Dispara /processar-aula (achar aulas com transcrição aprovada e
# pendente de processar, gerar aula editada + guia + cards + propostas
# numa leitura só, colar de volta) -- ver
# .claude/skills/processar-aula/SKILL.md e RUNBOOK.md.
#
# Uso: .\processar-aulas.ps1            (modo "pendentes")
#      .\processar-aulas.ps1 -Alvo 5    (só a aula 5)

param(
	[string]$Alvo = ""
)

Set-Location $PSScriptRoot
& "$PSScriptRoot\disparar-skill.ps1" `
	-Skill "/processar-aula" `
	-Alvo $Alvo `
	-LogPrefix "processar-aulas" `
	-MensagemFinal "Proximo passo: revisar as propostas em /aprovacao de cada aula." `
	-TempoTipico "aula de 2h costuma levar uns 15-20min"

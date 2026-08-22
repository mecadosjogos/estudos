# Wrapper fino em cima de disparar-skill.ps1 -- ver esse arquivo para os
# detalhes (por que PowerShell, por que --dangerously-skip-permissions,
# etc). Dispara /transcrever-paginas (achar páginas de livro pendentes,
# ler a foto com o Read tool -- sem API de visão -- e colar a
# transcrição de volta) -- ver
# .claude/skills/transcrever-paginas/SKILL.md e RUNBOOK.md.
#
# Uso: .\transcrever-paginas.ps1            (modo "pendentes")
#      .\transcrever-paginas.ps1 -Alvo 42   (só a página 42)

param(
	[string]$Alvo = ""
)

Set-Location $PSScriptRoot
& "$PSScriptRoot\disparar-skill.ps1" `
	-Skill "/transcrever-paginas" `
	-Alvo $Alvo `
	-LogPrefix "transcrever-paginas" `
	-MensagemFinal "Proximo passo: conferir as paginas em /works/{id}/ler." `
	-TempoTipico "alguns segundos por pagina"

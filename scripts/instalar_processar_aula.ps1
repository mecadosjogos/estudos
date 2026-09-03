# Prepara esta máquina Windows pra processar aula (fase 6) e transcrever
# página de material (fase 9+) por um chat do Claude Code -- RUNBOOK.md --
# contra QUALQUER deploy deste repositório. Rode de dentro do clone que vai
# usar de verdade.
#
# Um dos três processos que a página /admin/backups deixa instalar
# separado (os outros dois: scripts/instalar_transcricao.ps1 -- worker de
# transcrição, precisa de GPU -- e tts-service/instalar.ps1 -- narração do
# guia). Diferente daquele, este script NÃO precisa de GPU nem instala
# PyTorch/faster-whisper -- o trabalho pesado é o chat do Claude Code em
# si, dentro da sua assinatura (nunca a API paga da Anthropic, ver
# RUNBOOK.md). Só confere Git + Claude Code CLI e configura o .env.
#
# Uso: .\scripts\instalar_processar_aula.ps1
#
# Baixado direto de um servidor rodando (GET /admin/instalar-processar-aula.ps1,
# autenticado como admin)? SERVER_URL já vem pronto pra aquele deploy
# específico. ACCESS_TOKEN não entra aqui de propósito -- RUNBOOK.md
# autentica por usuário/senha (BACKUP_ADMIN_USERNAME/PASSWORD), não pela
# credencial de máquina do worker; o servidor só guarda o hash da senha,
# então não tem como vir embutida sozinha.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Write-Step($msg) { Write-Host "`n== $msg ==" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  AVISO: $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  FALHOU: $msg" -ForegroundColor Red }

# --- 1. Pré-requisitos ---
Write-Step "Conferindo pré-requisitos"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Fail "Git não encontrado no PATH."
    exit 1
}
Write-Ok "Git presente"

if (Get-Command claude -ErrorAction SilentlyContinue) {
    Write-Ok "Claude Code CLI encontrado -- os skills em .claude\skills\ já vêm com o clone do repositório"
} else {
    Write-Fail "Claude Code CLI não encontrado no PATH. Instale antes de continuar: https://claude.com/claude-code"
    exit 1
}

# --- 2. .env (SERVER_URL, login do RUNBOOK.md) ---
Write-Step "Configuração (.env)"

$envPath = Join-Path $repoRoot ".env"
if (-not (Test-Path $envPath)) {
    Copy-Item (Join-Path $repoRoot ".env.example") $envPath
    Write-Host "  .env criado a partir de .env.example"
}

function Get-EnvValue($key) {
    # -Encoding utf8 é obrigatório nos dois lados (leitura aqui, escrita em
    # Set-EnvValue abaixo) -- sem isso o PowerShell 5.1 lê o arquivo com a
    # codepage ANSI do sistema, corrompe acento em memória, e a escrita
    # "correta" em UTF-8 grava esse lixo já corrompido de volta no disco.
    $line = Select-String -Path $envPath -Pattern "^$key=(.*)$" -Encoding utf8 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($line) { return $line.Matches[0].Groups[1].Value }
    return ""
}

function Set-EnvValue($key, $value) {
    $content = Get-Content $envPath -Encoding utf8
    $found = $false
    $updated = $content | ForEach-Object {
        if ($_ -match "^$key=") { $found = $true; "$key=$value" } else { $_ }
    }
    if (-not $found) { $updated += "$key=$value" }
    Set-Content -Path $envPath -Value $updated -Encoding utf8
}

function Read-HostSafe($prompt) {
    # Em modo não-interativo (ex.: agendador, automação) Read-Host levanta
    # exceção em vez de devolver vazio -- captura e trata como "Enter",
    # que já é o comportamento normal de manter o valor atual abaixo.
    try { return Read-Host $prompt } catch { return "" }
}

# $env:ESTUDOS_SERVER_URL só existe quando este script foi baixado direto de
# um servidor rodando (GET /admin/instalar-processar-aula.ps1 injeta essa
# linha no topo do arquivo antes de servir).
if ($env:ESTUDOS_SERVER_URL) {
    $serverUrl = $env:ESTUDOS_SERVER_URL
    Write-Ok "SERVER_URL já veio embutido no download: $serverUrl"
} else {
    $currentServerUrl = Get-EnvValue "SERVER_URL"
    $serverUrl = Read-HostSafe "URL do servidor desta instalação [$currentServerUrl]"
    if ([string]::IsNullOrWhiteSpace($serverUrl)) { $serverUrl = $currentServerUrl }
}
Set-EnvValue "SERVER_URL" $serverUrl
Write-Ok "SERVER_URL=$serverUrl"

Write-Host ""
Write-Host "RUNBOOK.md autentica no servidor por usuário/senha (não pela credencial" -ForegroundColor DarkGray
Write-Host "de máquina do worker) -- se ficar em branco, cai no padrão admin/admin" -ForegroundColor DarkGray
Write-Host "(local/dev). Contra uma VPS de verdade, confira se a senha não foi trocada." -ForegroundColor DarkGray

$currentUser = Get-EnvValue "BACKUP_ADMIN_USERNAME"
$loginUser = Read-HostSafe "Usuário admin [$currentUser, Enter mantém]"
if (-not [string]::IsNullOrWhiteSpace($loginUser)) { Set-EnvValue "BACKUP_ADMIN_USERNAME" $loginUser }

$currentPasswordSet = -not [string]::IsNullOrWhiteSpace((Get-EnvValue "BACKUP_ADMIN_PASSWORD"))
$passwordStatus = if ($currentPasswordSet) { "definida" } else { "não definida" }
try {
    $securePassword = Read-Host "Senha do usuário admin [$passwordStatus, Enter mantém]" -AsSecureString
} catch {
    $securePassword = $null
}
if ($securePassword -and $securePassword.Length -gt 0) {
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        $plainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    if (-not [string]::IsNullOrWhiteSpace($plainPassword)) { Set-EnvValue "BACKUP_ADMIN_PASSWORD" $plainPassword }
}

Write-Step "Pronto"
Write-Host "Pra processar aula pendente com IA: .\processar-aulas.ps1  (ou -Alvo <id> pra só uma)"
Write-Host "Pra transcrever página de material da biblioteca: .\transcrever-paginas.ps1"
Write-Host "Os dois abrem um chat do Claude Code sozinho, sem pedir confirmação -- RUNBOOK.md"
Write-Host "tem o passo a passo completo (e a regra de nunca aceitar proposta sozinho)."
try { Read-Host "`nPressione Enter para fechar" | Out-Null } catch {}

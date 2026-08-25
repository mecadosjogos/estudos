# Prepara esta máquina Windows pra rodar o worker (Whisper com GPU) e o
# processamento manual de aula por Claude Code, contra QUALQUER deploy deste
# repositório (a VPS de produção original, ou uma nova pra outro curso) --
# rode de dentro do clone que vai usar de verdade.
#
# Pressupostos que este script NÃO tenta instalar sozinho (arriscado demais
# pra automatizar sem ver a tela, ex.: driver de GPU pode exigir reiniciar):
#   - Driver NVIDIA já instalado (confere com `nvidia-smi`)
#   - Python 3.12+ já instalado
#   - Git já instalado
# O que este script FAZ:
#   - Cria/atualiza o venv em server\.venv com as dependências de server+worker
#   - Garante ffmpeg (instala via winget se faltar -- não é driver, é seguro)
#   - Configura .env (SERVER_URL, ACCESS_TOKEN, WORKER_NAME) pro deploy que
#     esta máquina vai servir
#   - Testa se a GPU responde de verdade (carrega um modelo Whisper pequeno)
#   - Confere se o Claude Code CLI está disponível (só avisa, não instala)
#
# Uso: .\scripts\instalar_maquina_worker.ps1
#
# Baixado direto de um servidor rodando (GET /admin/instalar-worker.ps1,
# autenticado como admin)? SERVER_URL e ACCESS_TOKEN já vêm prontos pra
# aquele deploy específico -- só pergunta o nome do worker.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Write-Step($msg) { Write-Host "`n== $msg ==" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  AVISO: $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  FALHOU: $msg" -ForegroundColor Red }

# --- 1. Pré-requisitos que este script não instala ---
Write-Step "Conferindo pré-requisitos"

# Get-Command em vez de invocar com stderr redirecionado (2>&1) pra checar
# presença: mesmo motivo do teste de GPU mais abaixo -- 2>&1 + $ErrorActionPreference
# "Stop" derruba o script com qualquer linha que o executável mandar pro stderr,
# mesmo numa checagem que só quer saber se o comando existe.
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Fail "Python não encontrado no PATH. Instale Python 3.12+ antes de continuar."
    exit 1
}
Write-Ok (& python --version)

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Fail "Git não encontrado no PATH."
    exit 1
}
Write-Ok "Git presente"

if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    Write-Fail "nvidia-smi não encontrado -- driver NVIDIA não parece instalado. O worker precisa de GPU pra transcrever no tamanho large-v3."
    exit 1
}
Write-Ok "GPU NVIDIA detectada (driver ok)"

# --- 2. venv + dependências ---
Write-Step "Ambiente Python (server\.venv)"

$venvPython = Join-Path $repoRoot "server\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "  Criando venv..."
    & python -m venv (Join-Path $repoRoot "server\.venv")
}
Write-Ok "venv em server\.venv"

Write-Host "  Instalando dependências (server + worker)..."
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r (Join-Path $repoRoot "server\requirements.txt") -r (Join-Path $repoRoot "worker\requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Fail "pip install falhou -- veja o erro acima."
    exit 1
}
Write-Ok "dependências instaladas"

# --- 3. ffmpeg ---
Write-Step "ffmpeg"

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Ok "ffmpeg já está no PATH"
} else {
    Write-Host "  Não encontrado -- instalando via winget..."
    winget install --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements
    Write-Warn "Pode ser necessário abrir um terminal novo pro PATH atualizado valer."
}

# --- 4. .env (SERVER_URL, ACCESS_TOKEN, WORKER_NAME) ---
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

# $env:ESTUDOS_SERVER_URL / $env:ESTUDOS_ACCESS_TOKEN só existem quando este
# script foi baixado direto de um servidor rodando (GET /admin/instalar-worker.ps1
# injeta essas duas linhas no topo do arquivo antes de servir) -- nesse caso já
# sabemos os valores certos pra ESTE deploy e nem faz sentido perguntar.
if ($env:ESTUDOS_SERVER_URL) {
    $serverUrl = $env:ESTUDOS_SERVER_URL
    Write-Ok "SERVER_URL já veio embutido no download: $serverUrl"
} else {
    $currentServerUrl = Get-EnvValue "SERVER_URL"
    $serverUrl = Read-HostSafe "URL do servidor desta instalação [$currentServerUrl]"
    if ([string]::IsNullOrWhiteSpace($serverUrl)) { $serverUrl = $currentServerUrl }
}
Set-EnvValue "SERVER_URL" $serverUrl

if ($env:ESTUDOS_ACCESS_TOKEN) {
    $accessToken = $env:ESTUDOS_ACCESS_TOKEN
    Set-EnvValue "ACCESS_TOKEN" $accessToken
    Write-Ok "ACCESS_TOKEN já veio embutido no download"
} else {
    $currentToken = Get-EnvValue "ACCESS_TOKEN"
    $tokenPrompt = if ($currentToken) { "definido" } else { "não definido" }
    $accessToken = Read-HostSafe "ACCESS_TOKEN (credencial de worker desse servidor) [$tokenPrompt, Enter mantém]"
    if (-not [string]::IsNullOrWhiteSpace($accessToken)) { Set-EnvValue "ACCESS_TOKEN" $accessToken }
}

$currentWorkerName = Get-EnvValue "WORKER_NAME"
$workerName = Read-HostSafe "Nome deste worker (aparece em qual máquina transcreveu) [$currentWorkerName]"
if ([string]::IsNullOrWhiteSpace($workerName)) { $workerName = $currentWorkerName }
Set-EnvValue "WORKER_NAME" $workerName

Write-Ok "SERVER_URL=$serverUrl, WORKER_NAME=$workerName"

# --- 5. Teste real de GPU (modelo pequeno, não baixa o large-v3 inteiro) ---
Write-Step "Testando faster-whisper na GPU (modelo 'tiny', só pra validar CUDA/cuDNN)"

$cublasDir = Join-Path $repoRoot "server\.venv\Lib\site-packages\nvidia\cublas\bin"
$cudnnDir = Join-Path $repoRoot "server\.venv\Lib\site-packages\nvidia\cudnn\bin"
$env:PATH = "$cublasDir;$cudnnDir;$env:PATH"

$testScript = @"
from faster_whisper import WhisperModel
model = WhisperModel("tiny", device="cuda", compute_type="float16")
print("GPU_OK")
"@
$testScriptPath = Join-Path $env:TEMP "estudos-gpu-check.py"
Set-Content -Path $testScriptPath -Value $testScript -Encoding utf8

# Sem 2>&1 de propósito: em PowerShell 5.1, redirecionar stderr de um
# executável nativo embrulha cada linha num ErrorRecord, e com
# $ErrorActionPreference = "Stop" isso vira exceção terminante mesmo com
# saída 0 -- travaria o script inteiro num traceback do Python em vez de
# só reportar "GPU falhou" e seguir pro resto das checagens.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $venvPython $testScriptPath
$gpuOk = $LASTEXITCODE -eq 0
$ErrorActionPreference = $previousPreference
Remove-Item $testScriptPath -ErrorAction SilentlyContinue

if ($gpuOk) {
    Write-Ok "GPU respondeu -- faster-whisper carregou e rodou em CUDA"
} else {
    Write-Fail "Não conseguiu rodar na GPU (traceback do Python acima)."
    Write-Warn "Confira CUDA_PATH/driver -- o resto da instalação já está pronto mesmo assim."
}

# --- 6. Claude Code CLI (só informativo) ---
Write-Step "Claude Code CLI"

if (Get-Command claude -ErrorAction SilentlyContinue) {
    Write-Ok "encontrado no PATH -- os skills em .claude\skills\ já vêm com o clone do repositório"
} else {
    Write-Warn "não encontrado no PATH. Instale separadamente (https://claude.com/claude-code) pra processar aula manualmente (RUNBOOK.md)."
}

Write-Step "Pronto"
Write-Host "Pra transcrever: .\worker\run_local.ps1"
Write-Host "Pra processar aula com IA: abra um chat do Claude Code neste repositório e siga RUNBOOK.md"
try { Read-Host "`nPressione Enter para fechar" | Out-Null } catch {}

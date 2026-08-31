# Instala o serviço de TTS local (Chatterbox Multilingual v3, Resemble AI)
# -- standalone, não depende de nada do resto do repositório Estudos.
# Reusável por qualquer script na máquina via HTTP (ver main.py).
#
# Clonagem de voz: precisa de pelo menos uma pasta em vozes\<nome>\ com
# ref.wav (alguns segundos, voz limpa, sem eco/ruído de fundo -- qualidade
# da gravação importa bastante) antes de /synthesize funcionar -- fora do
# git de propósito, dado biométrico pessoal. GET /speakers lista o que já
# está configurado.
#
# Trocado do F5-TTS pra este depois de comparar os dois com a mesma voz de
# referência: F5-TTS produzia áudio embaralhado em PT-BR mesmo com dois
# checkpoints comunitários diferentes (achado real, ver histórico do
# projeto); Chatterbox tem parâmetro explícito de idioma (`language_id`),
# não depende só do fine-tune/referência pra "adivinhar" o idioma.
#
# Precisa: Python 3.12+, GPU NVIDIA com driver instalado, ffmpeg no PATH --
# mesmos pré-requisitos que scripts\instalar_maquina_worker.ps1 já confere
# pro worker de transcrição; se você já rodou aquele nesta máquina, esses já
# estão ok.

$ErrorActionPreference = "Stop"
$serviceDir = $PSScriptRoot
$venvDir = Join-Path $serviceDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Criando venv em $venvDir..."
    python -m venv $venvDir
}

Write-Host "Instalando PyTorch com suporte a CUDA..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124

Write-Host "Instalando dependências do serviço..."
& $venvPython -m pip install -r (Join-Path $serviceDir "requirements.txt")

Write-Host ""
Write-Host "Instalado. Rode .\tts-service\iniciar.ps1 para subir o serviço."
Write-Host "No primeiro start, os pesos do Chatterbox são baixados automaticamente."

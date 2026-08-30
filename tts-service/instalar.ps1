# Instala o serviço de TTS local (Coqui XTTS v2) -- standalone, não depende
# de nada do resto do repositório Estudos. Reusável por qualquer script na
# máquina via HTTP (ver main.py).
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
Write-Host "No primeiro start, o modelo XTTS v2 (~2GB) é baixado automaticamente."

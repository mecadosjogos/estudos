@echo off
REM Duplo clique nisso (ou num atalho apontando pra cá): instala o serviço
REM de TTS local (narração do guia de aula). Não precisa abrir terminal
REM nem lembrar comando nenhum -- veja instalar.ps1 pro que ele confere e
REM configura.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"

echo.
echo Pressione qualquer tecla para fechar esta janela...
pause >nul

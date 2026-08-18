@echo off
REM Duplo clique nisso (ou num atalho apontando pra cá): verifica a fila,
REM transcreve tudo que estiver pendente nesta máquina, e fecha sozinho
REM quando terminar. Não precisa abrir terminal nem lembrar comando nenhum.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_local.ps1"

echo.
echo Pressione qualquer tecla para fechar esta janela...
pause >nul

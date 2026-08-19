@echo off
REM Duplo clique nisso (ou num atalho apontando pra cá): acha aula com
REM áudio ainda sem transcrição (fora da matéria LIXO), enfileira sozinho,
REM transcreve tudo que estiver pendente nesta máquina, e fecha quando
REM terminar. Não precisa abrir terminal, chat nem lembrar comando nenhum.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_local.ps1"

echo.
echo Pressione qualquer tecla para fechar esta janela...
pause >nul

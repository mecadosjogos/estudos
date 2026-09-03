@echo off
REM Duplo clique nisso (ou num atalho apontando pra cá): prepara esta
REM máquina Windows pra rodar o worker de transcrição e o processamento
REM manual de aula por Claude Code. Não precisa abrir terminal nem
REM lembrar comando nenhum -- veja instalar_maquina_worker.ps1 pro que
REM ele confere e configura.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_maquina_worker.ps1"

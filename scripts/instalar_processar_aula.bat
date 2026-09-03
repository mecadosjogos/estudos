@echo off
REM Duplo clique nisso (ou num atalho apontando pra cá): prepara esta
REM máquina Windows pra processar aula/página com IA por um chat do
REM Claude Code (RUNBOOK.md). Não precisa de GPU. Não precisa abrir
REM terminal nem lembrar comando nenhum -- veja instalar_processar_aula.ps1
REM pro que ele confere e configura.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_processar_aula.ps1"

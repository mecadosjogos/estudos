@echo off
REM Duplo clique nisso (ou num atalho apontando pra cá): prepara esta
REM máquina Windows pra rodar o worker de transcrição (Whisper com GPU).
REM Não precisa abrir terminal nem lembrar comando nenhum -- veja
REM instalar_transcricao.ps1 pro que ele confere e configura.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_transcricao.ps1"

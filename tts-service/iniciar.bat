@echo off
REM Duplo clique nisso (ou num atalho apontando pra cá): sobe o serviço de
REM TTS local em http://127.0.0.1:8100 e deixa a janela aberta -- feche a
REM janela (ou Ctrl+C) pra derrubar o serviço.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar.ps1"

@echo off
REM Duplo clique nisso (ou no atalho da area de trabalho): dispara o
REM Claude Code sozinho, sem ninguem olhando, pra rodar a skill
REM /processar-aula -- ver processar-aulas.ps1 para os detalhes (por que
REM PowerShell, por que --dangerously-skip-permissions, etc).
REM
REM Uso: processar-aulas.bat        (modo "pendentes")
REM      processar-aulas.bat 5      (só a aula 5)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0processar-aulas.ps1" -Alvo "%~1"

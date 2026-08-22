@echo off
REM Duplo clique nisso (ou no atalho da area de trabalho): dispara o
REM Claude Code sozinho, sem ninguem olhando, pra rodar a skill
REM /transcrever-paginas -- ver transcrever-paginas.ps1 para os detalhes
REM (por que PowerShell, por que --dangerously-skip-permissions, etc).
REM
REM Uso: transcrever-paginas.bat        (modo "pendentes")
REM      transcrever-paginas.bat 42     (só a página 42)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0transcrever-paginas.ps1" -Alvo "%~1"

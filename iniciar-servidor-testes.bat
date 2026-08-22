@echo off
REM Duplo clique nisso (ou no atalho da area de trabalho): sobe o ambiente
REM de staging Docker -- o mais parecido com a VPS (Ubuntu 24.04 + Docker)
REM que da pra testar localmente (ver CLAUDE.md, "Ambiente de teste").
REM Reconstroi a imagem com o codigo atual (o Dockerfile faz COPY, entao
REM sem isso o container serve codigo velho), sobe os containers e aplica
REM as migracoes pendentes. Nao precisa terminal nem lembrar comando.

cd /d "%~dp0"

echo Verificando o Docker Desktop...
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready

echo Docker Desktop nao esta rodando -- iniciando...
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"

set /a tentativas=0
:wait_docker
ping -n 6 127.0.0.1 >nul
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready
set /a tentativas+=1
if %tentativas% GEQ 24 goto docker_timeout
echo Aguardando o Docker Desktop iniciar... (%tentativas%/24)
goto wait_docker

:docker_timeout
echo.
echo O Docker Desktop nao respondeu depois de 2 minutos.
echo Abra o Docker Desktop manualmente e tente de novo.
goto fim

:docker_ready
echo Docker pronto.

echo.
echo Reconstruindo a imagem do servidor (rapido se nada mudou)...
docker compose build server
if errorlevel 1 goto erro

echo.
echo Subindo os containers...
docker compose up -d
if errorlevel 1 goto erro

echo.
echo Aplicando migracoes pendentes...
docker compose exec server python -m alembic upgrade head
if errorlevel 1 goto erro

echo.
echo ============================================================
echo  Pronto! Servidor de testes no ar em http://127.0.0.1:8000
echo  Primeira visita: http://127.0.0.1:8000/?k=SEU_TOKEN_DO_ENV
echo  (o token esta em ACCESS_TOKEN no .env da raiz do repo)
echo ============================================================
goto fim

:erro
echo.
echo Algo falhou -- veja a mensagem de erro acima.

:fim
echo.
echo Pressione qualquer tecla para fechar esta janela...
pause >nul

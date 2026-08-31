# Estudos

Sistema pessoal de estudo do curso de Direito: transcreve aulas gravadas, transforma o material em resumo/índice/glossário/cards com IA, e organiza a revisão espaçada. Arquitetura completa, decisões e roadmap estão em [PLANO.md](PLANO.md). Instruções de desenvolvimento (Docker local, fases, runbook de IA manual) estão em [CLAUDE.md](CLAUDE.md) e [RUNBOOK.md](RUNBOOK.md). Para autorizar um dispositivo novo a acessar o app já em produção, veja [docs/dispositivos.md](docs/dispositivos.md).

## Deploy

Este `docker-compose.yml` é feito pra rodar numa VPS que **já tem um Traefik compartilhado** na frente de outros projetos (é o caso da VPS Hostinger em uso) — não sobe Caddy nem qualquer proxy próprio, nem publica as portas 80/443. Em vez disso, o serviço `server` entra na rede `root_default` (a rede do projeto Compose que já roda o Traefik) e carrega labels que dizem ao Traefik qual domínio rotear pra ele — mesmo padrão já usado por outros projetos na mesma VPS (`/docker/meca-interface/docker-compose.yml`).

**Antes de qualquer deploy**: o domínio (`drwyver.mecadosjogos.app.br`, definido nas labels em `docker-compose.yml`) precisa ter um registro DNS tipo A apontando pro IP da VPS — sem isso o Traefik não consegue emitir o certificado HTTPS (desafio TLS-ALPN-01, resolvedor `mytlschallenge`).

### Deploy pelo hPanel (Docker Manager, a partir da URL do repositório)

1. Aponte o campo de repositório pra `https://github.com/<seu-usuario>/estudos.git` e dê um nome ao projeto.
2. **Variáveis de ambiente** — no campo de env vars da tela de deploy, defina:
   - `SESSION_SECRET` — a mais importante de todas: é o que assina o cookie de sessão do login. Sem definir, cai no valor padrão publicado neste próprio repositório (`dev-secret-troque-isto`), o que permite forjar sessão de qualquer usuário. Gere algo aleatório e longo, ex.: `openssl rand -hex 32`.
   - `ACCESS_TOKEN` — não tem mais relação com login de navegador; é a credencial de máquina usada só pelo worker de transcrição e pelo Atalho do iOS (`Authorization: Bearer <TOKEN>`, veja [docs/atalho-ios.md](docs/atalho-ios.md)). Só precisa definir se for usar algum desses dois.
   
   Não precisa de um arquivo `.env` físico — o hPanel injeta essas variáveis direto no container, e `docker-compose.yml` já está preparado pra rodar sem `.env` (`env_file` é opcional).
3. Deploy. Depois do primeiro `up`, rode a migração (ela não roda sozinha no start) — por SSH:
   ```bash
   cd /docker/<nome-do-projeto>
   docker compose exec server python -m alembic upgrade head
   ```
4. Acesse `https://drwyver.mecadosjogos.app.br/login` e entre com `admin`/`admin` (usuário e senha semeados na primeira migração — troque essa senha assim que puder em "Trocar senha" no menu, `/conta/senha`). Autorizar mais gente/dispositivos: veja [docs/dispositivos.md](docs/dispositivos.md).

Se quiser usar outro domínio, edite a linha `Host(...)` nas labels do `server` em [docker-compose.yml](docker-compose.yml) antes do deploy (ou depois, por SSH + redeploy).

### Deploy manual (SSH)

```bash
git clone https://github.com/<seu-usuario>/estudos.git
cd estudos
cp .env.example .env
# edite .env: SESSION_SECRET pelo menos (senão assina cookie com o valor padrão do repositório)
docker compose up -d --build
docker compose exec server python -m alembic upgrade head
```

Funciona só se a VPS já tiver a rede `root_default` com um Traefik ouvindo nela (como na VPS em uso hoje). Numa VPS **dedicada**, sem Traefik nenhum rodando, esse compose não serve de imediato — precisaria de um proxy próprio (Caddy, Nginx) na frente; avise se for esse o caso que a gente resolve.

### Deploy automático a cada push

Todo push em `master` dispara [.github/workflows/docker-publish.yml](.github/workflows/docker-publish.yml): builda a imagem, publica em `ghcr.io/mecadosjogos/estudos:latest`, e roda um Watchtower "one-shot" via SSH na VPS que só atualiza o container `estudos-server-1` (mesmo padrão dos outros projetos na mesma VPS). Não precisa clicar em nada no hPanel depois do primeiro deploy.

Migração de banco continua manual — se o push mudou o schema, entre por SSH e rode `docker compose exec server python -m alembic upgrade head` depois que o Watchtower atualizar o container.

Secrets do repositório usados pelo workflow (`Settings → Secrets and variables → Actions`): `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` — a chave é dedicada a este deploy, sem relação com as credenciais dos outros projetos na mesma VPS.

**Rodar isso manualmente (ex.: sessão de Claude Code aplicando migração após um push).** Acesso local à mesma chave/VPS via `VPS_SSH_HOST`/`VPS_SSH_USER`/`VPS_SSH_KEY_PATH` no `.env` (nunca commitar o valor real — repositório é público; `.env` é gitignorado). Com essas três variáveis:

```bash
# confirma que o container já subiu com a imagem nova antes de migrar
ssh -i "$VPS_SSH_KEY_PATH" "$VPS_SSH_USER@$VPS_SSH_HOST" "docker inspect estudos-server-1 --format '{{.Created}}'"

# roda a migração
ssh -i "$VPS_SSH_KEY_PATH" "$VPS_SSH_USER@$VPS_SSH_HOST" "docker exec estudos-server-1 python -m alembic upgrade head"

# confirma
ssh -i "$VPS_SSH_KEY_PATH" "$VPS_SSH_USER@$VPS_SSH_HOST" "docker exec estudos-server-1 python -m alembic current"
```

Se o passo "Trigger Watchtower one-shot" do Actions falhar (aconteceu por instabilidade de rede pontual), dispara o mesmo Watchtower manualmente antes de migrar:

```bash
ssh -i "$VPS_SSH_KEY_PATH" "$VPS_SSH_USER@$VPS_SSH_HOST" \
  "docker run --rm -v /var/run/docker.sock:/var/run/docker.sock containrrr/watchtower --run-once estudos-server-1"
```

**Cuidado**: essa VPS é compartilhada com outros projetos (`meca-interface-*`, `meca-automacoes-*`, `supabase-*`, `root-n8n-*`, `root-traefik-1`, entre outros rodando ali) — todo comando acima mexe *só* no container `estudos-server-1`, nunca use `docker compose down`/`up` sem escopo explícito nessa máquina.

---

A transcrição de áudio (Whisper `large-v3`, GPU) roda numa máquina local, não no VPS — veja [worker/](worker/) e [docker-compose.worker.yml](docker-compose.worker.yml). O VPS só precisa de CPU para a válvula de emergência "transcrever na VPS agora".

## Máquina de worker (Whisper + processamento manual de IA)

`scripts/instalar_maquina_worker.ps1` prepara uma máquina Windows com GPU pra rodar o worker de transcrição contra **qualquer** deploy deste repositório — a VPS original, ou uma nova pra outro curso.

**Máquina nova, sem nada configurado ainda:** na tela `/admin/backups` de qualquer deploy rodando, botão **"Baixar pacote completo (.zip)"** — vem com `server/`, `worker/`, `shared/`, `.claude/skills/`, docs e o script já com `SERVER_URL`/`ACCESS_TOKEN` **daquele deploy específico** embutidos (não precisa nem digitar, nem ter Git instalado na máquina nova). Baixa, extrai numa pasta de caminho curto (`C:\worker\`, não uma pasta com nome longo — o Windows tem limite de tamanho de caminho, e pacotes Python como numpy têm árvore de arquivo bem aninhada), e dá dois cliques em `scripts\instalar_maquina_worker.bat` (ou roda o `.ps1` direto). Pra deixar um atalho na Área de Trabalho: clique direito no `.bat` → Enviar para → Área de trabalho — não tem automação pra isso, é o mesmo passo manual de sempre neste projeto.

**Já tem o repositório clonado nessa máquina:** roda `scripts\instalar_maquina_worker.ps1` de dentro do clone, ou baixa só `/admin/instalar-worker.ps1` (sem o pacote inteiro) se só quiser atualizar `SERVER_URL`/`ACCESS_TOKEN` pra um deploy diferente.

Pressupõe já instalados (não tenta automatizar sozinho — driver de GPU em especial pode exigir reiniciar, arriscado sem ver a tela): driver NVIDIA, Python 3.12+. A partir daí, cuida do venv (`server\.venv`, dependências de `server/` + `worker/`), ffmpeg (via winget se faltar), `.env` (`SERVER_URL`/`ACCESS_TOKEN`/`WORKER_NAME`), testa a GPU de verdade (carrega um modelo Whisper pequeno em CUDA) e avisa se o Claude Code CLI está no PATH (os skills em `.claude/skills/` já vêm junto, só o CLI em si é instalado à parte).

## Backup versionado no repositório

`scripts/backup_de_producao.ps1` (ou `python scripts/backup_from_vps.py` direto) loga na VPS como admin, baixa um backup fresco do banco — **sem a tabela `user`**, que carrega hash de senha — e o mp3 de cada aula, e grava tudo em `data-backup/` neste repositório. O script **não commita nem dá push sozinho**: só escreve os arquivos e imprime o comando pra você revisar e publicar quando quiser. Credenciais via `BACKUP_ADMIN_USERNAME`/`BACKUP_ADMIN_PASSWORD` no `.env` (ou perguntadas na hora, se ausentes).

## Desenvolvimento local

Sempre via Docker, nunca `uvicorn` direto no host — e sempre com os dois arquivos de compose juntos (`docker-compose.yml` sozinho depende do Traefik da VPS de produção, que não existe localmente):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml build server
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
docker compose exec server python -m alembic upgrade head
```

Acesse em `http://127.0.0.1:8000/login` e entre com `admin`/`admin`. Detalhes em [CLAUDE.md](CLAUDE.md).

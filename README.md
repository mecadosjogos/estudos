# Estudos

Sistema pessoal de estudo do curso de Direito: transcreve aulas gravadas, transforma o material em resumo/índice/glossário/cards com IA, e organiza a revisão espaçada. Arquitetura completa, decisões e roadmap estão em [PLANO.md](PLANO.md). Instruções de desenvolvimento (Docker local, fases, runbook de IA manual) estão em [CLAUDE.md](CLAUDE.md) e [RUNBOOK.md](RUNBOOK.md).

## Deploy

Este `docker-compose.yml` é feito pra rodar numa VPS que **já tem um Traefik compartilhado** na frente de outros projetos (é o caso da VPS Hostinger em uso) — não sobe Caddy nem qualquer proxy próprio, nem publica as portas 80/443. Em vez disso, o serviço `server` entra na rede `root_default` (a rede do projeto Compose que já roda o Traefik) e carrega labels que dizem ao Traefik qual domínio rotear pra ele — mesmo padrão já usado por outros projetos na mesma VPS (`/docker/meca-interface/docker-compose.yml`).

**Antes de qualquer deploy**: o domínio (`drwyver.mecadosjogos.app.br`, definido nas labels em `docker-compose.yml`) precisa ter um registro DNS tipo A apontando pro IP da VPS — sem isso o Traefik não consegue emitir o certificado HTTPS (desafio TLS-ALPN-01, resolvedor `mytlschallenge`).

### Deploy pelo hPanel (Docker Manager, a partir da URL do repositório)

1. Aponte o campo de repositório pra `https://github.com/<seu-usuario>/estudos.git` e dê um nome ao projeto.
2. **Variáveis de ambiente** — no campo de env vars da tela de deploy, defina pelo menos:
   - `ACCESS_TOKEN` — chave de acesso ao app (não tem tela de login, é `?k=<TOKEN>` na primeira visita). Gere algo aleatório e longo, ex.: `openssl rand -hex 32`.
   - `SESSION_SECRET` — outro valor aleatório longo, independente do `ACCESS_TOKEN`.
   
   Não precisa de um arquivo `.env` físico — o hPanel injeta essas variáveis direto no container, e `docker-compose.yml` já está preparado pra rodar sem `.env` (`env_file` é opcional).
3. Deploy. Depois do primeiro `up`, rode a migração (ela não roda sozinha no start) — por SSH:
   ```bash
   cd /docker/<nome-do-projeto>
   docker compose exec server python -m alembic upgrade head
   ```
4. Acesse `https://drwyver.mecadosjogos.app.br/?k=<ACCESS_TOKEN>`.

Se quiser usar outro domínio, edite a linha `Host(...)` nas labels do `server` em [docker-compose.yml](docker-compose.yml) antes do deploy (ou depois, por SSH + redeploy).

### Deploy manual (SSH)

```bash
git clone https://github.com/<seu-usuario>/estudos.git
cd estudos
cp .env.example .env
# edite .env: ACCESS_TOKEN e SESSION_SECRET pelo menos
docker compose up -d --build
docker compose exec server python -m alembic upgrade head
```

Funciona só se a VPS já tiver a rede `root_default` com um Traefik ouvindo nela (como na VPS em uso hoje). Numa VPS **dedicada**, sem Traefik nenhum rodando, esse compose não serve de imediato — precisaria de um proxy próprio (Caddy, Nginx) na frente; avise se for esse o caso que a gente resolve.

### Deploy automático a cada push

Todo push em `master` dispara [.github/workflows/docker-publish.yml](.github/workflows/docker-publish.yml): builda a imagem, publica em `ghcr.io/mecadosjogos/estudos:latest`, e roda um Watchtower "one-shot" via SSH na VPS que só atualiza o container `estudos-server-1` (mesmo padrão dos outros projetos na mesma VPS). Não precisa clicar em nada no hPanel depois do primeiro deploy.

Migração de banco continua manual — se o push mudou o schema, entre por SSH e rode `docker compose exec server python -m alembic upgrade head` depois que o Watchtower atualizar o container.

Secrets do repositório usados pelo workflow (`Settings → Secrets and variables → Actions`): `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` — a chave é dedicada a este deploy, sem relação com as credenciais dos outros projetos na mesma VPS.

---

A transcrição de áudio (Whisper `large-v3`, GPU) roda numa máquina local, não no VPS — veja [worker/](worker/) e [docker-compose.worker.yml](docker-compose.worker.yml). O VPS só precisa de CPU para a válvula de emergência "transcrever na VPS agora".

## Desenvolvimento local

Sempre via Docker, nunca `uvicorn` direto no host — e sempre com os dois arquivos de compose juntos (`docker-compose.yml` sozinho depende do Traefik da VPS de produção, que não existe localmente):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml build server
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
docker compose exec server python -m alembic upgrade head
```

Acesse em `http://127.0.0.1:8000/?k=<ACCESS_TOKEN>` (token no `.env` da raiz). Detalhes em [CLAUDE.md](CLAUDE.md).

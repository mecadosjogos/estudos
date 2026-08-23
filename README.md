# Estudos

Sistema pessoal de estudo do curso de Direito: transcreve aulas gravadas, transforma o material em resumo/índice/glossário/cards com IA, e organiza a revisão espaçada. Arquitetura completa, decisões e roadmap estão em [PLANO.md](PLANO.md). Instruções de desenvolvimento (Docker local, fases, runbook de IA manual) estão em [CLAUDE.md](CLAUDE.md) e [RUNBOOK.md](RUNBOOK.md).

## Deploy num VPS (Hostinger ou qualquer VPS com Docker)

Precisa de um VPS com acesso root e Docker + Docker Compose instalados — **não roda em hospedagem compartilhada** (sem Docker/root, não dá pra rodar FastAPI + Caddy nesse tipo de plano). **DNS**: aponte seu domínio para o IP do VPS antes de começar em qualquer um dos dois caminhos abaixo — o Caddy só emite certificado HTTPS se o domínio já resolver para o servidor.

### Deploy pelo hPanel (Docker a partir da URL do repositório)

O hPanel clona o repositório inteiro no servidor e roda o `docker-compose.yml` de dentro do clone — o build (`context: .`) já funciona sem alteração. Duas coisas não vêm no clone porque são propositalmente ignoradas pelo git (`.env`, e o domínio real no `Caddyfile` é algo só você sabe):

1. Aponte o campo de repositório do hPanel para `https://github.com/<seu-usuario>/estudos.git`.
2. **Variáveis de ambiente**: se a tela do hPanel tiver campos de variável de ambiente por serviço, defina lá pelo menos `ACCESS_TOKEN` e `SESSION_SECRET` (valores aleatórios longos, ex.: `openssl rand -hex 32` cada um) — o `docker-compose.yml` já está preparado para funcionar mesmo sem um arquivo `.env` físico (`env_file` é opcional). Se não houver esse campo, entre por SSH na pasta onde o hPanel clonou o repositório e crie o `.env` na mão (`cp .env.example .env` e preencha, mesmos passos do caminho manual abaixo) antes de deixar o hPanel subir os containers.
3. **Domínio no Caddy**: o `Caddyfile` do repositório aponta pra `drwyver.mecadosjogos.app.br` (o domínio deste projeto original) — edite a linha antes do deploy (ou depois, por SSH, seguido de um `docker compose up -d --build` pra reconstruir a imagem do Caddy) trocando pelo seu domínio. O Caddyfile entra na imagem por `COPY` no build (`caddy/Dockerfile`), não por bind mount — então qualquer edição só tem efeito depois de reconstruir, um `restart` sozinho não pega a mudança.
4. **`docker-compose.override.yml`**: esse arquivo é só para desenvolvimento local (expõe a porta 8000 direto, sem Caddy nem HTTPS) e o Docker Compose o carrega automaticamente se ele existir na pasta. Apague-o na pasta clonada pelo hPanel antes do primeiro deploy — por SSH, `rm docker-compose.override.yml`.
5. Depois do primeiro `up`, rode a migração (ela não roda sozinha no start):
   ```bash
   docker compose exec server python -m alembic upgrade head
   ```
6. Acesse `https://<seu-domínio>/?k=<ACCESS_TOKEN>`.

### Deploy manual (SSH)

1. No VPS:
   ```bash
   git clone https://github.com/<seu-usuario>/estudos.git
   cd estudos
   cp .env.example .env
   ```
2. **Edite `.env`** e preencha pelo menos:
   - `ACCESS_TOKEN` — chave de acesso ao app (não tem tela de login, é `?k=<TOKEN>` na primeira visita).
   - `SESSION_SECRET` — outro valor aleatório longo, independente do `ACCESS_TOKEN`.
   - Demais variáveis (`ANTHROPIC_API_KEY`, Google, etc.) só são necessárias a partir das fases que as usam — veja os comentários do próprio `.env.example`.
3. **Edite o [Caddyfile](Caddyfile)**, trocando `drwyver.mecadosjogos.app.br` pelo seu domínio real (o `DOMAIN` do `.env` é só informativo hoje — quem decide o domínio servido é o Caddyfile). Ele entra na imagem do Caddy por build (`caddy/Dockerfile`), então qualquer edição exige reconstruir (passo 5 abaixo já faz isso com `--build`).
4. **Apague `docker-compose.override.yml`** — existe só para dev local, e o Compose o carrega automaticamente se ficar no clone:
   ```bash
   rm docker-compose.override.yml
   ```
5. **Suba os containers e rode a migração**:
   ```bash
   docker compose up -d --build
   docker compose exec server python -m alembic upgrade head
   ```
6. Acesse `https://<seu-domínio>/?k=<ACCESS_TOKEN>`.

---

A transcrição de áudio (Whisper `large-v3`, GPU) roda numa máquina local, não no VPS — veja [worker/](worker/) e [docker-compose.worker.yml](docker-compose.worker.yml). O VPS só precisa da GPU para a válvula de emergência "transcrever na VPS agora" (CPU, modelo menor).

## Desenvolvimento local

Sempre via Docker, nunca `uvicorn` direto no host — veja [CLAUDE.md](CLAUDE.md).

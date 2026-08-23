# Estudos

Sistema pessoal de estudo do curso de Direito: transcreve aulas gravadas, transforma o material em resumo/índice/glossário/cards com IA, e organiza a revisão espaçada. Arquitetura completa, decisões e roadmap estão em [PLANO.md](PLANO.md). Instruções de desenvolvimento (Docker local, fases, runbook de IA manual) estão em [CLAUDE.md](CLAUDE.md) e [RUNBOOK.md](RUNBOOK.md).

## Deploy num VPS (Hostinger ou qualquer VPS com Docker)

Precisa de um VPS com acesso root e Docker + Docker Compose instalados — **não roda em hospedagem compartilhada** (sem Docker/root, não dá pra rodar FastAPI + Caddy nesse tipo de plano).

1. **DNS**: aponte seu domínio para o IP do VPS antes de começar (o Caddy só emite certificado HTTPS se o domínio já resolver para o servidor).

2. **No VPS**, clone o repositório:
   ```bash
   git clone https://github.com/<seu-usuario>/estudos.git
   cd estudos
   cp .env.example .env
   ```

3. **Edite `.env`** e preencha pelo menos:
   - `ACCESS_TOKEN` — chave de acesso ao app (não tem tela de login, é `?k=<TOKEN>` na primeira visita). Gere algo aleatório e longo, ex.: `openssl rand -hex 32`.
   - `SESSION_SECRET` — outro valor aleatório longo, independente do `ACCESS_TOKEN`.
   - Demais variáveis (`ANTHROPIC_API_KEY`, Google, etc.) só são necessárias a partir das fases que as usam — veja os comentários do próprio `.env.example`.

4. **Edite o [Caddyfile](Caddyfile)**, trocando `drwyver.mecadosjogos.app.br` pelo seu domínio real (o `DOMAIN` do `.env` é só informativo hoje — quem decide o domínio servido é o Caddyfile).

5. **Apague `docker-compose.override.yml` antes de subir em produção.** Esse arquivo existe só para desenvolvimento local — expõe a porta 8000 direto, sem Caddy e sem HTTPS. O Docker Compose carrega qualquer `docker-compose.override.yml` automaticamente quando presente, então em produção ele precisa sair do caminho:
   ```bash
   rm docker-compose.override.yml
   ```

6. **Suba os containers e rode a migração** (não roda sozinha no start):
   ```bash
   docker compose up -d --build
   docker compose exec server python -m alembic upgrade head
   ```

7. Acesse `https://<seu-domínio>/?k=<ACCESS_TOKEN>` — o cookie de sessão é trocado na primeira visita e a URL fica limpa a partir daí.

A transcrição de áudio (Whisper `large-v3`, GPU) roda numa máquina local, não no VPS — veja [worker/](worker/) e [docker-compose.worker.yml](docker-compose.worker.yml). O VPS só precisa da GPU para a válvula de emergência "transcrever na VPS agora" (CPU, modelo menor).

## Desenvolvimento local

Sempre via Docker, nunca `uvicorn` direto no host — veja [CLAUDE.md](CLAUDE.md).

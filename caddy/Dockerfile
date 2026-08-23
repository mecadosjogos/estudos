FROM caddy:2-alpine

# O Caddyfile entra na imagem por COPY, não por bind mount do host --
# alguns painéis de deploy (ex.: hPanel clonando por Git) resolvem caminho
# relativo de bind mount de um jeito que não bate com onde o repositório
# realmente fica no host, e monta um arquivo inexistente como diretório em
# cima do Caddyfile padrão que já vem na imagem (erro "not a directory").
# Buildar resolve isso de vez, com o mesmo padrão que server/Dockerfile já usa.
COPY Caddyfile /etc/caddy/Caddyfile

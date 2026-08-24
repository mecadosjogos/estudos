# Autorizar um dispositivo novo

## Como funciona

O Estudos tem login por usuário e senha, com cadastro público mas uso
bloqueado até um administrador aprovar. Não existe recuperação de senha
por e-mail (não há esse tipo de infraestrutura) — se **esquecer** a
senha (diferente de só querer trocar, veja abaixo), hoje não tem
autoatendimento nenhum, nem pelo admin: precisa de acesso direto ao
banco pra gerar um hash novo.

- **Um único administrador nasce com o banco** (`admin`/`admin`, semeado
  na primeira migração) — troque essa senha o quanto antes depois do
  primeiro deploy, em "Trocar senha" no menu do topo (`/conta/senha`,
  pede a senha atual).
- **Sessão por cookie**, igual antes: depois de logar, o navegador fica
  autenticado por até 1 ano sem precisar digitar senha de novo — mas
  agora cada navegador faz seu próprio login, não existe mais um link
  mágico compartilhável.
- **Sem conta própria por dispositivo** — é conta por *pessoa*. A mesma
  conta pode logar em quantos aparelhos quiser; o administrador não vê
  "dispositivos", só usuários.

## Pedir acesso pela primeira vez

1. Abra `https://drwyver.mecadosjogos.app.br/registrar`.
2. Escolha um usuário e uma senha, confirme a senha, envie.
3. Fica em **"pendente"** até o administrador aprovar — tentar logar antes
   disso mostra "Cadastro aguardando aprovação do administrador."
4. O administrador aprova (veja abaixo) e a partir daí `/login` funciona
   normalmente.

## Logar num dispositivo já aprovado

1. Abra `https://drwyver.mecadosjogos.app.br/login`.
2. Usuário e senha, Entrar.
3. Esse navegador fica autenticado por 1 ano — não precisa repetir a
   cada visita. Repita em cada navegador/dispositivo novo (Firefox e
   Chrome contam como dois; janela anônima não guarda, precisa logar
   toda vez).

Pra sair, botão "Sair" no menu do topo (POST `/logout`, limpa o cookie).

## Como administrador: aprovar, recusar, revogar, dar acesso temporário

Logado como usuário com papel `admin` (só o `admin` semeado tem esse
papel hoje — não há tela pra promover outro usuário), o menu do topo
ganha o link **Segurança** (`/admin/seguranca`):

- **Pedidos de acesso** — lista quem está `pendente`. **Aprovar**
  (com um campo opcional "dias": vazio = acesso permanente, preenchido =
  expira automaticamente depois desse prazo) ou **Recusar**.
- **Usuários** — todo mundo que não está mais pendente. Pra um usuário
  já aprovado: **Conceder temporário** (mesmo botão de aprovar, serve
  pra trocar um acesso permanente por um com prazo, ou vice-versa
  deixando "dias" vazio) e **Revogar** (derruba o acesso na próxima
  requisição dessa pessoa — não precisa esperar a sessão expirar).
  Um usuário recusado/revogado pode ser **readmitido** pela mesma tela.
- O admin não consegue revogar/recusar a própria conta pelo painel — é
  uma proteção contra se trancar pra fora sem querer.

Acesso temporário vencido para de funcionar sozinho no próximo login —
não precisa de nenhuma ação do administrador quando o prazo expira.

## Envio de áudio sem navegador (iPad/iOS, Atalhos, worker de transcrição)

Esse caminho **não muda** — continua usando `ACCESS_TOKEN` (a mesma
variável de ambiente de sempre, configurada no servidor) como cabeçalho
`Authorization: Bearer <ACCESS_TOKEN>`, sem login interativo. É uma
credencial de máquina, separada do login de pessoa acima. Veja
[atalho-ios.md](atalho-ios.md).

## Instalar como app (opcional)

O Estudos é um PWA simples — depois de logado, dá pra "instalar":

- **Android/Chrome desktop**: menu do navegador → *Instalar app* /
  *Adicionar à tela inicial*.
- **iOS/Safari**: botão Compartilhar → *Adicionar à Tela de Início*.

Abre em janela própria, sem barra de endereço. Os ícones ainda não estão
configurados (`server/app/static/manifest.json`), então usa um ícone
genérico por enquanto — cosmético, não afeta o funcionamento.

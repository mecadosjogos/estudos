# Autorizar um dispositivo novo

## Como funciona (leia antes de fazer)

O Estudos **não tem tela de login nem contas de usuário** — é um app pessoal
protegido por um único segredo, o `ACCESS_TOKEN`. Não existe "adicionar
dispositivo" como cadastro individual: existe **visitar o link com o token
uma vez em cada navegador**, o que grava um cookie de sessão que dura 1 ano
nesse navegador. Não tem lista de dispositivos autorizados nem forma de
revogar um só sem revogar todos — trocar o `ACCESS_TOKEN` desautoriza
**todo mundo** de uma vez, inclusive você nos outros aparelhos.

Trate o `ACCESS_TOKEN` como senha: não cole em print, chat, ou lugar
público. Quem tiver o token tem acesso completo aos seus dados de estudo.

## Autorizar este PC agora

1. Pegue o valor do `ACCESS_TOKEN` — é o que você digitou no campo de
   variáveis de ambiente ao fazer o deploy no hPanel (Docker Manager →
   projeto do Estudos → variáveis de ambiente). Se o hPanel não deixar ver
   o valor de novo (alguns painéis mostram só na hora de criar), veja
   "Esqueci o token" abaixo.
2. No navegador deste PC, abra:
   ```
   https://drwyver.mecadosjogos.app.br/?k=SEU_ACCESS_TOKEN
   ```
3. A página redireciona sozinha e o `?k=...` some da barra de endereço —
   é o cookie de sessão sendo gravado (`estudos_session`, HttpOnly,
   assinado, válido por 1 ano). A partir daqui esse navegador não precisa
   mais do token: só acessar `https://drwyver.mecadosjogos.app.br/`.
4. Se aparecer "Sessão inválida" em vez de redirecionar, o token digitado
   está errado — confira se copiou certo, sem espaço extra no fim.

Repita esses 3 passos em **qualquer outro navegador ou dispositivo** que
quiser autorizar — celular, notebook, outro navegador no mesmo PC (Firefox
e Chrome contam como dois, cada um grava seu próprio cookie), janela
anônima (não persiste, precisa repetir toda vez).

## Instalar como app (opcional)

O Estudos é um PWA simples — depois de autorizado, dá pra "instalar":

- **Android/Chrome desktop**: menu do navegador → *Instalar app* / *Adicionar
  à tela inicial*.
- **iOS/Safari**: botão Compartilhar → *Adicionar à Tela de Início*.

Abre em janela própria, sem barra de endereço. Os ícones ainda não estão
configurados (`server/app/static/manifest.json`), então usa um ícone
genérico por enquanto — cosmético, não afeta o funcionamento.

## Envio de áudio sem navegador (iPad/iOS, Atalhos)

Pra subir gravação direto do app de gravação, sem abrir o navegador, veja
[atalho-ios.md](atalho-ios.md) — usa o mesmo `ACCESS_TOKEN`, mas como
cabeçalho `Authorization: Bearer <TOKEN>` em vez do cookie.

## Esqueci o token / quero revogar um dispositivo perdido

Não tem revogação seletiva. Pra trocar o token (e derrubar o acesso de
todo mundo, inclusive um aparelho perdido/roubado):

1. hPanel → Docker Manager → projeto do Estudos → variáveis de ambiente →
   edite `ACCESS_TOKEN` pra um valor novo (ex.: gere com
   `openssl rand -hex 32`).
2. Redeploy pelo hPanel (mudança de variável de ambiente não é pega pelo
   pipeline automático do GitHub Actions — esse só dispara em push de
   código, veja a seção "Deploy automático a cada push" no [README.md](../README.md)).
3. Visite `/?k=<TOKEN_NOVO>` de novo em cada dispositivo que ainda deve
   ter acesso (passo "Autorizar este PC agora" acima).

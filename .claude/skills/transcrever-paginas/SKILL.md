---
name: Transcrever Páginas
description: Transcreve páginas de livro pendentes (fase 10, biblioteca) lendo as fotos direto com o Read tool — sem API de visão da Anthropic — seguindo o RUNBOOK.md do projeto Estudos. Só chamada explicitamente pelo usuário via /transcrever-paginas.
argument-hint: [id-da-pagina | pendentes]
disable-model-invocation: true
context: fork
background: true
---

Você está transcrevendo fotos de página de livro do app "Estudos" (curso
de Direito) no papel que a API de visão da Anthropic (`claude-haiku-4-5`)
ocuparia no plano original — o usuário decidiu não usar nenhuma API paga
pra isso também, e fazer essa etapa manualmente, através de você, lendo a
foto direto com o Read tool (que já lê imagem nativamente).

**Primeiro passo, sempre:** leia [RUNBOOK.md](../../../RUNBOOK.md) na raiz
do repo inteiro, incluindo a seção "Fase 10 — Transcrever páginas de
livro". Ele é a fonte de verdade de como fazer isso — siga o que estiver
escrito nele, mesmo que divirja do que este arquivo sugere, porque o
runbook é atualizado a cada fase nova e este arquivo não é.

## Alvo

`$ARGUMENTS` é o id de uma `MaterialPage`, ou a palavra `pendentes`. Vazio
equivale a `pendentes`.

`pendentes` significa: ache **todas** as páginas com `status="pendente"`
(consulta no RUNBOOK.md) e transcreva uma de cada vez, do início ao fim.

Se `$ARGUMENTS` for um id específico, transcreva só aquela página.

## Diferença importante em relação a `/processar-aula`

**Não existe portão de aprovação aqui.** Página fotografada não passa por
revisão humana antes de virar "elegível" — você já escolheu a foto, a
curadoria da fonte já aconteceu no momento do upload. `status="pendente"`
significa só "ainda não transcrita". Pode processar direto.

## Regras não-negociáveis

1. **Sequencial, nunca paralelo.** Uma página de cada vez, do início ao
   fim, antes de começar a próxima — mesmo motivo do `/processar-aula`
   (escritas simultâneas no SQLite local já causaram corrupção real).
2. **Baixe a imagem antes de ler.** Ela vive dentro do volume Docker, não
   no filesystem do host (`curl .../paginas/{id}/imagem -o pagina.png`,
   depois Read na `pagina.png` baixada) — não tem como ler o
   `image_path` do banco direto, ele é um caminho de dentro do container.
3. **Transcrição literal, nunca paráfrase.** Isto é o equivalente da
   transcrição bruta de aula, não da aula editada. Preserve nota de
   rodapé, citação recuada, itálico, estrutura de tabela. Markdown limpo.
4. **Não invente o que a foto não deixa ler.** Letra miúda, sombra,
   tipografia antiga, perspectiva torta — se não der pra ler com
   confiança, marque como erro (`POST .../erro`) em vez de chutar um
   texto. Um erro marcado é recuperável (o usuário tira foto melhor
   depois); um texto inventado que parece plausível não é.
5. **Nunca passe texto acentuado como argumento inline de curl** — mesma
   armadilha de encoding documentada no RUNBOOK.md e no
   `processar-aula/SKILL.md`. Sempre escreva a transcrição num arquivo
   primeiro e deixe o curl ler sozinho: `--data-urlencode
   "texto@${WINPATH}"` (`WINPATH=$(cygpath -w arquivo)`).
6. **Confira encoding depois de cada POST** com texto acentuado — rode o
   `repr()` no banco (comando está no RUNBOOK.md) e confirme que não
   apareceu `�`.
7. **Um 409 ao colar significa que a página já foi corrigida à mão.** Não
   tente contornar (não existe outra rota pra forçar) — é a proteção
   funcionando. Pule para a próxima página e registre isso no resumo
   final.
8. **Um erro numa página não trava as outras.** Marque com
   `POST .../erro` e continue — não pare o lote inteiro por causa de uma
   foto ruim.

## Ao terminar

Devolva um resumo compacto, uma linha por página tocada — nunca o texto
transcrito completo:

```
[pagina 42] material 7 "Cap. 1-3" (Instituições de Direito Civil) — ok — 340 palavras, encoding ok
[pagina 43] material 7 "Cap. 1-3" (Instituições de Direito Civil) — ok — 298 palavras, encoding ok
[pagina 44] material 7 "Cap. 1-3" (Instituições de Direito Civil) — ERRO marcado — sombra cobrindo metade da foto
[pagina 45] material 7 "Cap. 1-3" (Instituições de Direito Civil) — pulada — já corrigida à mão (409)
```

Se algo falhar de verdade (não um 409 nem uma página ilegível — um erro
de verdade, tipo servidor fora do ar), registre o erro nessa linha e
continue para a próxima página — não trave o lote inteiro por causa de
uma.

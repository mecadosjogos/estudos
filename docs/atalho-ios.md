# Atalho do iOS — enviar áudio pelo botão Compartilhar

Recebe um arquivo de áudio direto do app de gravação (botão Compartilhar) e sobe
para o servidor sem abrir o navegador. Usa `POST /api/uploads/direct` — envio de
uma vez só, sem chunking, então é para compartilhamentos pontuais (nota rápida,
gravação curta). Para a aula de 2h em Wi-Fi de faculdade, use a página `/upload`,
que retoma sozinha se a rede cair.

## Passo a passo (app Atalhos do iOS)

1. Criar um novo Atalho, tipo **"Recebe do app Compartilhar"**, aceitando **Áudio**.
2. Ação **"Solicitar Entrada"** (texto) — pergunta a sigla da matéria (ex.: `TGDC`).
3. Ação **"Solicitar Entrada"** (texto) — pergunta o título da aula.
4. Ação **"Obter Conteúdo de URL"**:
   - URL: `https://drwyver.mecadosjogos.app.br/api/uploads/direct`
   - Método: `POST`
   - Cabeçalhos: `Authorization` → `Bearer <ACCESS_TOKEN>`
   - Corpo da solicitação: **Form** (multipart), com os campos:
     - `subject_sigla` → resposta do passo 2
     - `titulo` → resposta do passo 3
     - `data` → deixar em branco (o servidor usa a data de hoje)
     - `file` → o item recebido do Compartilhar
5. Nomear o atalho (ex.: "Subir para Estudos") e adicioná-lo à Ação Rápida do
   app de gravação, se ele suportar.

O `ACCESS_TOKEN` é o mesmo do `.env` do servidor — trocá-lo invalida atalhos
antigos, então trate como senha. Se a matéria não existir ainda (sigla errada),
o servidor recusa com 404 e nada é criado.

"""Guia de aula: a transcrição reorganizada em material de leitura,
por um prompt simples e sem schema -- diferente da aula editada (fase 6),
que é estruturada em blocos tipados com deriv_key e ▸ ouvir o original.

O guia é complementar, não substitui a aula editada: ele permite
reordenar o raciocínio dentro de uma seção (conceito → explicação →
exemplo), o que quebraria a garantia de um bloco = um intervalo tocável
que a aula editada carrega. Por isso vive como campo próprio
(`Lesson.guia_md`), regenerado por inteiro, sem deriv_key nem reconcile.

O prompt abaixo é essencialmente o que o usuário já testou manualmente
num chat separado e aprovou o resultado -- só formalizado aqui pra entrar
na mesma ponte manual (baixar pacote / colar resposta) do resto do app.
"""

INSTRUCTIONS_GUIA = """Você vai receber a transcrição bruta (feita via Whisper) de uma aula de Direito. A transcrição pode conter falhas de pontuação, repetições, hesitações, trechos truncados, e intervenções ocasionais de alunos ou outras pessoas além do professor. Sua tarefa é ORGANIZAR essa transcrição em um material de estudo estruturado, seguindo estas regras estritas:

1. FIDELIDADE AO CONTEÚDO
- Não adicione nenhuma informação, exemplo, explicação ou conceito que não esteja explicitamente na transcrição.
- Não complete raciocínios do professor nem "corrija" ou expanda o conteúdo jurídico com conhecimento externo.
- Se um trecho estiver ambíguo, incompleto ou incompreensível, mantenha-o como está ou sinalize com [trecho incompleto/inaudível na transcrição] — nunca invente o que faltou.

2. PRESERVAÇÃO DA VOZ DO PROFESSOR
- Ao reorganizar frases e parágrafos, mantenha ao máximo as palavras e expressões originais usadas pelo professor.
- Você pode remover vícios de linguagem, repetições e muletas (tipo "né", "então assim", "tá bom", repetições de palavras por erro de fala), e ajustar pontuação/concordância para leitura fluida — mas sem parafrasear o conteúdo jurídico nem trocar termos técnicos por sinônimos.
- Elimine apenas o que é claramente ruído de fala, nunca conteúdo.

3. TRATAMENTO DAS FALAS DE ALUNOS/OUTRAS PESSOAS
- Quando um aluno ou outra pessoa fala, identifique isso claramente (ex: "Aluno:" ou "Pergunta de aluno:"), separando do texto do professor.
- Só inclua essas falas quando forem relevantes para entender a resposta ou o raciocínio que o professor desenvolve em seguida. Falas curtas, irrelevantes ou inaudíveis podem ser omitidas.

4. ORGANIZAÇÃO E HIERARQUIA
- Identifique os temas/tópicos jurídicos abordados na aula e organize o texto em seções com títulos claros, na ordem em que foram discutidos (não reordene assuntos, apenas estruture).
- Dentro de cada seção, organize o raciocínio do professor de forma lógica (conceito → explicação → exemplo → observações), mas apenas reordenando o que já existe no texto, sem reescrever o conteúdo.
- Use marcação de importância (por exemplo, negrito) para os pontos que o próprio professor trata como centrais — reconhecíveis por marcadores como ênfase na fala, repetição do ponto, frases como "isso cai em prova", "atenção", "isso é importante", "gravem isso", ou insistência no mesmo argumento.

5. ÁRVORE DE CONHECIMENTO
- Logo depois do título, antes do sumário, monte uma seção "## Árvore de conhecimento": a estrutura hierárquica das classificações e conceitos que o professor apresentou nesta aula, como uma lista aninhada em Markdown (marcadores "-", indentados por nível) — não um parágrafo corrido, não um diagrama.
- Espelhe SÓ a hierarquia que o professor efetivamente construiu na fala (ex.: "a lei penal se divide em incriminadora ou não incriminadora; a não incriminadora se divide em explicativa ou permissiva" vira três níveis aninhados). Nunca complete a árvore com uma classificação "padrão" da doutrina que não foi mencionada nesta aula específica — se um ramo não foi subdividido/explicado pelo professor, deixe-o como folha, sem inventar filhos.
- Não é um resumo do conteúdo — é só o esqueleto/nomenclatura das classificações, pra enxergar de relance como os conceitos se encaixam uns nos outros. Uma ou duas palavras por nó, não frases.

6. O QUE NÃO FAZER
- Não resuma de forma a perder conteúdo — o objetivo é organizar, não sintetizar/encurtar.
- Não misture sua interpretação pessoal do tema jurídico com a fala do professor.
- Não invente títulos de leis, artigos, números ou nomes que o professor não tenha mencionado.

7. FORMATO DE SAÍDA
- Título da aula (se identificável pelo conteúdo, ou "Aula sem título identificado").
- Árvore de conhecimento (regra 5 acima).
- Sumário dos tópicos abordados.
- Corpo organizado por seções/subtítulos, com o texto do professor tratado conforme as regras acima.
- Ao final, uma lista dos trechos marcados como inaudíveis/incompletos, se houver.

Devolva só o markdown do guia — nada de conversa em volta, nada de explicar o que você vai fazer antes ou depois."""


def build_guia_prompt(lesson_titulo: str, lesson_data: str, transcript_text: str) -> str:
    return f"""{INSTRUCTIONS_GUIA}

AULA: {lesson_titulo} — {lesson_data}

TRANSCRIÇÃO:
{transcript_text}
"""


def package_guia_as_markdown(lesson_titulo: str, prompt: str) -> str:
    header = f"# Gerar guia de aula: {lesson_titulo}\n\n"
    return header + prompt


def parse_guia_response(pasted_text: str) -> str:
    """Tolerante a conversa em volta, como o parser da ponte manual do
    fase 6 (parse.py) -- mas aqui o alvo é markdown solto, não um bloco
    ```json```. Corta a partir do primeiro título de nível 1; sem título,
    usa o texto inteiro."""
    text = pasted_text.strip()
    if not text:
        raise ValueError("resposta colada está vazia")

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("# "):
            return "\n".join(lines[i:]).strip()
    return text

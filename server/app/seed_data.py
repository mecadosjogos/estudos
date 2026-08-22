"""Dados do seed inicial. Consumido pela migração/seed da fase 1-2, quando os modelos existirem."""

SUBJECTS = [
    {"nome": "Teoria Geral do Direito Civil", "sigla": "TGDC", "diploma_padrao": "CC", "cor": "#2563eb"},
    {"nome": "Ciência Política", "sigla": "CPOL", "diploma_padrao": None, "cor": "#d97706"},
    {"nome": "História do Direito", "sigla": "HIST", "diploma_padrao": None, "cor": "#78716c"},
    {"nome": "Teoria Geral do Crime", "sigla": "TGC", "diploma_padrao": "CP", "cor": "#b91c1c"},
    {"nome": "Direitos Humanos", "sigla": "DH", "diploma_padrao": "CF", "cor": "#15803d"},
]

# Fase 9: vocabulário inicial de MaterialTipo (PLANO.md) -- extensível
# (tabela, não enum), este é só o ponto de partida do semestre.
MATERIAL_TIPOS = [
    {"slug": "slide", "rotulo": "Slide"},
    {"slug": "livro", "rotulo": "Livro"},
    {"slug": "capitulo", "rotulo": "Capítulo"},
    {"slug": "artigo", "rotulo": "Artigo"},
    {"slug": "jurisprudencia", "rotulo": "Jurisprudência"},
    {"slug": "legislacao", "rotulo": "Legislação"},
    {"slug": "prova-antiga", "rotulo": "Prova antiga"},
    {"slug": "resumo", "rotulo": "Resumo"},
    {"slug": "anotacao", "rotulo": "Anotação"},
]

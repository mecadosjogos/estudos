"""Hash de senha (bcrypt) -- módulo-folha, sem import de app.*.

Fica separado de auth.py de propósito: a migração 0019 precisa hashear a
senha do admin semeado no upgrade(), e importar auth.py de dentro de uma
migração arrastaria db.py (que constrói o engine como efeito colateral de
import) -- um caminho nunca exercitado pelas migrações existentes, que só
importam seed_data.py (módulo de dados puro). Este módulo mantém a mesma
propriedade: zero efeito colateral ao importar.
"""

import bcrypt


def hash_password(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(senha: str, hash_: str) -> bool:
    return bcrypt.checkpw(senha.encode("utf-8"), hash_.encode("utf-8"))

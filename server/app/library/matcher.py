"""Vinculação automática doc <-> matéria/aula (PLANO.md: "por pasta, por
data no nome do arquivo, e por proximidade com a data da aula. Sem certeza,
o doc aparece numa caixa 'Não vinculados'"). Puro — sem chamada de rede —
pra testar sem credencial nenhuma.

As duas resoluções são independentes: `match_subject` decide se o material
tem matéria (via pasta — sinal de alta confiança, o usuário escolheu
compartilhar aquela pasta com aquela matéria). `match_lesson` decide, só
dentro das aulas dessa matéria, se dá pra apontar uma aula específica — e
"não dá" é um resultado tão válido quanto qualquer aula: vira material da
matéria, sem data, que é justamente o comportamento descrito no PLANO.md
para resumos/legislação/jurisprudência.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING

from ..models import Lesson, Subject

if TYPE_CHECKING:
    # Só para tipagem -- gdocs.py importa este módulo, então importar
    # DriveFile daqui em tempo de execução criaria um ciclo.
    from .gdocs import DriveFile

_DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})[-_.](?P<m>\d{1,2})[-_.](?P<d>\d{1,2})"),
    re.compile(r"(?P<d>\d{1,2})[-_.](?P<m>\d{1,2})[-_.](?P<y>20\d{2})"),
]

LESSON_DATE_WINDOW_DAYS = 2


def match_subject(drive_file: DriveFile, subjects: list[Subject]) -> Subject | None:
    """Por pasta: o parent direto do arquivo precisa bater com
    `Subject.drive_folder_id`."""
    for subject in subjects:
        if subject.drive_folder_id and subject.drive_folder_id in drive_file.parents:
            return subject
    return None


def _date_from_filename(name: str) -> date | None:
    for pattern in _DATE_PATTERNS:
        m = pattern.search(name)
        if not m:
            continue
        try:
            return date(int(m["y"]), int(m["m"]), int(m["d"]))
        except ValueError:
            continue
    return None


def match_lesson(drive_file: DriveFile, lessons: list[Lesson]) -> Lesson | None:
    """Por data no nome do arquivo (prioridade — é uma escolha explícita de
    quem nomeou o doc), senão por proximidade entre `modified_time` e a
    data da aula. Ambíguo (mais de uma aula bate) não resolve sozinho —
    fica só vinculado à matéria, sem aula específica, em vez de arriscar
    a aula errada."""
    filename_date = _date_from_filename(drive_file.name)
    if filename_date is not None:
        exact = [lesson for lesson in lessons if lesson.data == filename_date]
        if len(exact) == 1:
            return exact[0]
        return None  # data no nome bateu com zero ou mais de uma aula -- não adivinha

    modified_date = drive_file.modified_time.date()
    close = [lesson for lesson in lessons if abs((lesson.data - modified_date).days) <= LESSON_DATE_WINDOW_DAYS]
    if len(close) == 1:
        return close[0]
    return None

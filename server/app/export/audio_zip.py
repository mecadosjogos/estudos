"""Exportação de áudios das aulas (admin): .zip com o mp3 leve de cada aula
(o mesmo que a VPS serve, 32kbps), cortado de volta nas gravações
originais e renomeado "<matéria> - <AAAA-MM-DD> - parte X de Y.mp3".

Na VPS só existe o mp3 da aula inteira -- o worker concatena as gravações
e os originais são apagados depois da transcrição. O ponto de corte vem de
`AudioSegment.duracao_s` (medida antes de o original sumir). Aula anterior
a essa coluna: o corte é estimado pela proporção de `size_bytes` dos
originais sobre a duração do mp3 -- as gravações do celular têm bitrate
praticamente constante, então o erro fica na casa de 1-2 s (conferido
contra os originais arquivados no worker).

As partes são numeradas por matéria + data, não por aula: duas aulas da
mesma matéria no mesmo dia viram partes 1..N da mesma data, sem colidir
nome dentro do zip.
"""

import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..models import Lesson

_PROIBIDO_EM_NOME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _nome_seguro(texto: str) -> str:
    return _PROIBIDO_EM_NOME.sub("-", texto).strip(" .") or "sem nome"


def mp3_da_aula(lesson_id: int) -> Path:
    return config.MEDIA_WEB_DIR / f"lesson-{lesson_id}.mp3"


@dataclass
class AulaExportavel:
    lesson: Lesson
    # (início, fim) em segundos dentro do mp3; fim None = até o final.
    trechos: list[tuple[float, float | None]] = field(default_factory=list)
    corte_exato: bool = True


def planejar(lesson: Lesson) -> AulaExportavel | None:
    """None se a aula não tem mp3 no disco (sem áudio, ainda não
    transcrita, ou mídia perdida numa restauração)."""
    mp3 = mp3_da_aula(lesson.id)
    if not mp3.exists():
        return None
    segs = sorted(lesson.audio_segments, key=lambda s: s.ordem)
    if len(segs) <= 1:
        return AulaExportavel(lesson, [(0.0, None)], True)

    if all(s.duracao_s for s in segs):
        duracoes = [s.duracao_s for s in segs]
        exato = True
    else:
        from shared.audio import probe_duration_s

        total = probe_duration_s(mp3)
        tamanhos = [s.size_bytes or 0 for s in segs]
        soma = sum(tamanhos)
        if soma > 0:
            duracoes = [total * t / soma for t in tamanhos]
        else:
            duracoes = [total / len(segs)] * len(segs)
        exato = False

    trechos: list[tuple[float, float | None]] = []
    inicio = 0.0
    for i, dur in enumerate(duracoes):
        fim = None if i == len(duracoes) - 1 else inicio + dur
        trechos.append((inicio, fim))
        if fim is not None:
            inicio = fim
    return AulaExportavel(lesson, trechos, exato)


def _cortar(origem: Path, inicio: float, fim: float | None, destino: Path) -> None:
    """`-c copy`: sem reencodar, o arquivo continua o mp3 leve da VPS; o
    ffmpeg ajusta o corte pro frame de áudio mais próximo (~26 ms)."""
    if inicio == 0.0 and fim is None:
        shutil.copyfile(origem, destino)
        return
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{inicio:.3f}", "-i", str(origem)]
    if fim is not None:
        cmd += ["-t", f"{fim - inicio:.3f}"]
    cmd += ["-c", "copy", str(destino)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ao cortar {origem.name}: {result.stderr[-2000:]}")


def nomes_dos_arquivos(aulas: list[AulaExportavel], nome_materia: str) -> list[list[str]]:
    """Um nome por trecho, na mesma forma de `aulas[i].trechos`."""
    materia = _nome_seguro(nome_materia)
    total_por_data: dict[str, int] = {}
    for a in aulas:
        d = a.lesson.data.isoformat()
        total_por_data[d] = total_por_data.get(d, 0) + len(a.trechos)
    contador: dict[str, int] = {}
    nomes: list[list[str]] = []
    for a in aulas:
        d = a.lesson.data.isoformat()
        da_aula = []
        for _ in a.trechos:
            contador[d] = contador.get(d, 0) + 1
            da_aula.append(f"{materia} - {d} - parte {contador[d]} de {total_por_data[d]}.mp3")
        nomes.append(da_aula)
    return nomes


def ordenar(lessons: list[Lesson]) -> list[Lesson]:
    return sorted(lessons, key=lambda l: (l.data, l.criada_em, l.id))


def montar_zip(lessons: list[Lesson], nome_materia: str) -> tuple[Path, Path]:
    """Devolve (zip, diretório temporário) -- quem chama apaga o diretório
    depois de enviar. Aulas sem mp3 ficam de fora em silêncio (a tela já
    nem oferece). Lança ValueError se nada sobrar."""
    aulas = [a for a in (planejar(l) for l in ordenar(lessons)) if a is not None]
    if not aulas:
        raise ValueError("nenhuma das aulas escolhidas tem áudio")
    nomes = nomes_dos_arquivos(aulas, nome_materia)
    pasta = _nome_seguro(nome_materia)

    tmp = Path(tempfile.mkdtemp(prefix="export-audios-"))
    try:
        zip_path = tmp / f"{pasta} - audios.zip"
        partes_dir = tmp / "partes"
        partes_dir.mkdir()
        # ZIP_STORED: mp3 não comprime, deflate só gastaria CPU da VPS.
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for aula, nomes_aula in zip(aulas, nomes):
                origem = mp3_da_aula(aula.lesson.id)
                for (inicio, fim), nome in zip(aula.trechos, nomes_aula):
                    destino = partes_dir / nome
                    _cortar(origem, inicio, fim, destino)
                    zf.write(destino, f"{pasta}/{nome}")
                    destino.unlink()
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return zip_path, tmp

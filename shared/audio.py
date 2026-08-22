"""Concatenação e compressão de áudio via ffmpeg.

Usado tanto pelo worker (fase 4, na GPU local) quanto pelo caminho de
emergência "transcrever na VPS agora" (CPU da própria VPS) — mesmo código,
dois lugares onde roda.
"""

import subprocess
from pathlib import Path


def concat_audio_files(paths: list[Path], output_path: Path) -> None:
    """Concatena um ou mais arquivos de áudio, na ordem dada, num WAV mono 16kHz.

    Usa o filtro `concat` (não o demuxer) porque os arquivos de origem podem vir
    de apps diferentes com codecs diferentes — o filtro decodifica cada um antes
    de juntar, o demuxer exige que já sejam idênticos.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if len(paths) == 1:
        cmd = ["ffmpeg", "-y", "-i", str(paths[0]), "-ar", "16000", "-ac", "1", str(output_path)]
    else:
        inputs = []
        for p in paths:
            inputs += ["-i", str(p)]
        filter_inputs = "".join(f"[{i}:a]" for i in range(len(paths)))
        filter_complex = f"{filter_inputs}concat=n={len(paths)}:v=0:a=1[out]"
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", filter_complex,
            "-map", "[out]", "-ar", "16000", "-ac", "1",
            str(output_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ao concatenar: {result.stderr[-2000:]}")


def compress_to_mp3(input_path: Path, output_path: Path, bitrate: str = "32k") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-ac", "1", "-b:a", bitrate, str(output_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ao comprimir: {result.stderr[-2000:]}")


def probe_duration_s(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe falhou: {result.stderr[-2000:]}")
    return float(result.stdout.strip())


def cut_clip(source_path: Path, start_s: float, end_s: float, output_path: Path) -> None:
    """Corta um trecho do mp3 já comprimido (fase 15, destaques em áudio) --
    `-c copy` (sem reencodar) porque é audição casual num trecho de
    segundos, não edição de precisão; o ffmpeg já ajusta o corte pro
    keyframe/frame de áudio mais próximo sozinho."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-ss", str(max(start_s, 0.0)), "-to", str(end_s),
        "-i", str(source_path), "-c", "copy", str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ao cortar clipe: {result.stderr[-2000:]}")

"""Lock de GPU entre processos da mesma máquina (PLANO.md, fase 13b).

Numa GPU de 6 GB (o notebook), o Whisper large-v3, o TTS e o modelo de IA
local não cabem juntos -- rodar dois ao mesmo tempo estoura a VRAM ou
empurra tudo pra CPU. Então quem vai usar a GPU pega este lock antes:

- o worker de transcrição/narração (worker/main.py) pega pelo tempo de um
  job e, ANTES de esperar, deixa um "pedido" (arquivo) avisando que quer a
  GPU;
- o ouvinte da IA local (worker/ia_local.py) pega enquanto o llama-server
  estiver de pé, e entre um job e outro olha se há pedido: se houver,
  derruba o llama-server e solta o lock.

A transcrição tem prioridade porque é a fila longa e noturna; a IA local
espera ("máquina ocupada transcrevendo") e retoma sozinha depois.

O arquivo fica FORA do repositório (que está no OneDrive e sincroniza com
o desktop -- um lock sincronizado entre máquinas seria errado e ainda
brigaria com o OneDrive): em %LOCALAPPDATA%\\Estudos no Windows.
"""

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path


def pasta_local() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    pasta = base / "Estudos"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _arquivo_lock() -> Path:
    return pasta_local() / "gpu.lock"


def _arquivo_pedido() -> Path:
    return pasta_local() / "gpu_pedido"


class LockGPU:
    """Lock exclusivo por arquivo (msvcrt no Windows, fcntl no resto). Solto
    automaticamente se o processo morrer -- o SO fecha o arquivo."""

    def __init__(self, quem: str):
        self.quem = quem
        self._fh = None

    @property
    def pego(self) -> bool:
        return self._fh is not None

    def tentar(self) -> bool:
        if self._fh is not None:
            return True
        fh = open(_arquivo_lock(), "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def soltar(self) -> None:
        if self._fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self._fh.close()
        self._fh = None


def pedido_pendente() -> bool:
    return _arquivo_pedido().exists()


def pedir_gpu(quem: str) -> None:
    _arquivo_pedido().write_text(f"{quem} {time.time()}", encoding="utf-8")


def retirar_pedido() -> None:
    try:
        _arquivo_pedido().unlink()
    except FileNotFoundError:
        pass


@contextmanager
def usar_gpu(quem: str, *, ao_esperar=None, intervalo_s: float = 2.0):
    """Pra quem tem prioridade (transcrição/narração): deixa o pedido, espera
    o lock (chamando `ao_esperar()` a cada volta, pra logar), usa, solta."""
    lock = LockGPU(quem)
    pedir_gpu(quem)
    try:
        while not lock.tentar():
            if ao_esperar is not None:
                ao_esperar()
            time.sleep(intervalo_s)
        yield lock
    finally:
        lock.soltar()
        retirar_pedido()

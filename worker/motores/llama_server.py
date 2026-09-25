"""Motor local: llama-server (llama.cpp) via repositório irmão LlamaCppLocal.

Este módulo é DONO do processo do llama-server: sobe sob demanda quando
chega um job (via `LlamaCppLocal\\iniciar.ps1 -Modelo <id>`, o contrato
daquele repositório), mantém de pé enquanto chegam jobs, e derruba quando
fica ocioso ou quando a transcrição pede a GPU. Num MoE com experts na RAM
isso importa: o processo vivo segura ~9 GB de RAM de uma máquina de 16 GB.

Cada chamada vai em streaming (pra contar palavras e mandar progresso) com
`response_format: json_schema` -- o llama.cpp transforma o schema em
gramática e o modelo não consegue sair do formato -- e `cache_prompt`: as
chamadas de julgamento de um job compartilham o mesmo prefixo, e o
servidor reaproveita o KV cache dele (um slot só, `-np 1` no iniciar.ps1).
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

from . import ChamadaAbortada, RespostaInvalida, extrair_json

CODIGO_FALTA_RAM = 3  # mesmo valor de LlamaCppLocal\iniciar.ps1
TEMPO_MAXIMO_SUBIDA_S = 240


class FaltaMemoria(Exception):
    """iniciar.ps1 recusou subir: RAM disponível abaixo do necessário."""


class LlamaServer:
    def __init__(self, dir_llamacpp: Path, porta: int, pasta_logs: Path, log=print):
        self.dir = dir_llamacpp
        self.porta = porta
        self.pasta_logs = pasta_logs
        self.log = log
        self.modelo_ativo: str | None = None
        self._proc: subprocess.Popen | None = None
        self._log_fh = None
        self.ultimo_uso = 0.0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.porta}"

    @property
    def de_pe(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _saudavel(self) -> bool:
        try:
            return httpx.get(f"{self.base_url}/health", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def garantir(self, modelo: str, ao_esperar=None) -> None:
        """Deixa o llama-server de pé com `modelo`. Se outro modelo estiver
        carregado, troca. Levanta FaltaMemoria se o iniciar.ps1 recusar."""
        if self.de_pe and self.modelo_ativo == modelo:
            return
        self.parar()
        self.pasta_logs.mkdir(parents=True, exist_ok=True)
        self._log_fh = open(self.pasta_logs / f"llama-server-{modelo}.log", "w", encoding="utf-8", errors="replace")
        script = self.dir / "iniciar.ps1"
        comando = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-Modelo", modelo, "-Porta", str(self.porta),
        ]
        self.log(f"subindo o llama-server com {modelo}...")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        self._proc = subprocess.Popen(comando, stdout=self._log_fh, stderr=subprocess.STDOUT, creationflags=flags)
        self.modelo_ativo = modelo

        inicio = time.monotonic()
        while time.monotonic() - inicio < TEMPO_MAXIMO_SUBIDA_S:
            codigo = self._proc.poll()
            if codigo is not None:
                self._proc = None
                self.modelo_ativo = None
                if codigo == CODIGO_FALTA_RAM:
                    raise FaltaMemoria(f"sem RAM livre para subir {modelo}")
                raise RuntimeError(f"o llama-server saiu com código {codigo} ao subir {modelo} (ver {self._log_fh.name})")
            if self._saudavel():
                self.log(f"llama-server pronto com {modelo} em {time.monotonic() - inicio:.0f} s")
                self.ultimo_uso = time.monotonic()
                return
            if ao_esperar is not None:
                ao_esperar()
            time.sleep(2)
        self.parar()
        raise RuntimeError(f"o llama-server não ficou pronto em {TEMPO_MAXIMO_SUBIDA_S} s com {modelo}")

    def parar(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self.log(f"derrubando o llama-server ({self.modelo_ativo}) pra devolver VRAM e RAM")
            if sys.platform == "win32":
                # O processo é o powershell do iniciar.ps1; o llama-server é
                # filho dele. /T mata a árvore inteira.
                subprocess.run(["taskkill", "/PID", str(self._proc.pid), "/T", "/F"], capture_output=True)
            else:
                self._proc.kill()
            try:
                self._proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
        self._proc = None
        self.modelo_ativo = None
        if self._log_fh is not None:
            self._log_fh.close()
            self._log_fh = None

    def executar(self, chamada: dict, ao_progredir, abortado) -> tuple[dict, dict]:
        """Roda uma chamada. `ao_progredir(palavras)` é chamado durante o
        streaming; `abortado()` devolve True quando o servidor avisou que o
        job não é mais nosso. Devolve (json, métricas). Se a resposta vier
        truncada (bateu no max_tokens), tenta de novo uma vez com o dobro."""
        max_tokens = chamada.get("max_tokens") or 1024
        for tentativa in range(2):
            texto, metricas = self._stream(chamada, max_tokens, ao_progredir, abortado)
            try:
                return extrair_json(texto), metricas
            except RespostaInvalida:
                if tentativa == 1 or metricas.get("finish_reason") != "length":
                    raise
                max_tokens *= 2
        raise RespostaInvalida("sem resposta")

    def _stream(self, chamada: dict, max_tokens: int, ao_progredir, abortado) -> tuple[str, dict]:
        corpo = {
            "messages": [
                {"role": "system", "content": chamada["sistema"]},
                {"role": "user", "content": chamada["prompt"]},
            ],
            "temperature": chamada.get("temperatura", 0.2),
            "max_tokens": max_tokens,
            "stream": True,
            "cache_prompt": True,
            "response_format": {"type": "json_schema", "json_schema": {"name": "saida", "schema": chamada["schema"]}},
        }
        partes: list[str] = []
        metricas: dict = {}
        ultimo_aviso = 0.0
        with httpx.stream("POST", f"{self.base_url}/v1/chat/completions", json=corpo, timeout=httpx.Timeout(900, connect=10)) as resp:
            if resp.status_code != 200:
                resp.read()
                raise RuntimeError(f"llama-server respondeu {resp.status_code}: {resp.text[:500]}")
            for linha in resp.iter_lines():
                if abortado():
                    raise ChamadaAbortada()
                if not linha.startswith("data: "):
                    continue
                dado = linha[6:].strip()
                if dado == "[DONE]":
                    break
                evento = json.loads(dado)
                if "timings" in evento:
                    metricas["tokens_por_s"] = evento["timings"].get("predicted_per_second")
                    metricas["tokens"] = evento["timings"].get("predicted_n")
                escolhas = evento.get("choices") or []
                if not escolhas:
                    continue
                if escolhas[0].get("finish_reason"):
                    metricas["finish_reason"] = escolhas[0]["finish_reason"]
                pedaco = (escolhas[0].get("delta") or {}).get("content")
                if pedaco:
                    partes.append(pedaco)
                    agora = time.monotonic()
                    if agora - ultimo_aviso > 1.5:
                        ultimo_aviso = agora
                        ao_progredir(len("".join(partes).split()))
        self.ultimo_uso = time.monotonic()
        return "".join(partes), metricas

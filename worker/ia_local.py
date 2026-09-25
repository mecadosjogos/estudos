"""Ouvinte da IA local (PLANO.md, fase 13b) -- roda na máquina com GPU e
fica ligado, puxando da VPS o trabalho das dissertativas (gerar questão,
julgar cada ponto, redigir o feedback) e devolvendo a resposta.

A VPS nunca abre conexão com esta máquina: o ouvinte faz long-poll em
`/api/ia-local/next` (o servidor segura até 25 s e responde no instante em
que houver um job), executa as chamadas do job em ordem e devolve. Cada
long-poll também conta como "estou ligado" -- é isso que a página mostra.

Motores:
- local (padrão): llama-server via repositório irmão LlamaCppLocal (ver
  worker/motores/llama_server.py). Sobe sob demanda, cai depois de 10 min
  sem job, e cai também quando a transcrição pede a GPU (shared/gpu_lock.py).
- Claude CLI: só quando alguém AUTORIZA nesta máquina, por um tempo
  (`autorizar-claude --horas N`, padrão 24 h). Passado o prazo, volta ao
  local sozinho. Se o Claude falhar num job, o job é refeito no local.

O que é desta máquina (modelo escolhido, autorização do Claude) mora em
%LOCALAPPDATA%\\Estudos\\ia_local.json -- NÃO no .env, que está no OneDrive e
sincroniza com o desktop.

Uso:
    worker\\ia_local.ps1                                  (fica ouvindo)
    worker\\ia_local.ps1 -Modelo gemma4-26b-a4b          (só nesta execução)
    worker\\ia_local.ps1 -Servidor local                 (Docker dev em 127.0.0.1:8000)
    python -m worker.ia_local usar-modelo gpt-oss-20b    (grava o padrão desta máquina)
    python -m worker.ia_local autorizar-claude --horas 3
    python -m worker.ia_local revogar-claude
    python -m worker.ia_local status
"""

import argparse
import json
import socket
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import gpu_lock  # noqa: E402
from worker import config  # noqa: E402
from worker.motores import ChamadaAbortada, claude_cli  # noqa: E402
from worker.motores.llama_server import FaltaMemoria, LlamaServer  # noqa: E402

WAIT_S = 25
INTERVALO_PROGRESSO_S = 4
HORAS_PADRAO_CLAUDE = 24
SERVIDOR_LOCAL = "http://127.0.0.1:8000"


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --- configuração desta máquina ----------------------------------------------------


def _arquivo_local() -> Path:
    return gpu_lock.pasta_local() / "ia_local.json"


def ler_local() -> dict:
    try:
        return json.loads(_arquivo_local().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def gravar_local(dados: dict) -> None:
    _arquivo_local().write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def claude_autorizado_ate(agora: datetime | None = None) -> datetime | None:
    """Prazo da autorização do Claude, se ainda valendo."""
    agora = agora or datetime.now(timezone.utc)
    valor = ler_local().get("claude_autorizado_ate")
    if not valor:
        return None
    ate = datetime.fromisoformat(valor)
    return ate if ate > agora else None


def autorizar_claude(horas: float | None = None, agora: datetime | None = None) -> datetime:
    agora = agora or datetime.now(timezone.utc)
    ate = agora + timedelta(hours=horas if horas else HORAS_PADRAO_CLAUDE)
    dados = ler_local()
    dados["claude_autorizado_ate"] = ate.isoformat()
    gravar_local(dados)
    return ate


def revogar_claude() -> None:
    dados = ler_local()
    dados.pop("claude_autorizado_ate", None)
    gravar_local(dados)


def modelo_padrao() -> str:
    return ler_local().get("modelo") or config.IA_LOCAL_MODELO


def escolher_motor(agora: datetime | None = None) -> tuple[str, datetime | None]:
    ate = claude_autorizado_ate(agora)
    return ("claude_cli", ate) if ate is not None else ("local", None)


# --- conversa com o servidor ---------------------------------------------------------


class Servidor:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {config.ACCESS_TOKEN}"}

    def proximo(self, nome: str, presenca: dict) -> dict | None:
        params = {"worker_name": nome, "wait": WAIT_S, **{k: v for k, v in presenca.items() if v is not None}}
        resp = httpx.get(f"{self.url}/api/ia-local/next", params=params, headers=self.headers, timeout=WAIT_S + 20)
        resp.raise_for_status()
        return resp.json()["job"]

    def progresso(self, job_id: int, claim_token: str, etapa: str | None, palavras: int | None) -> bool:
        """False = o job não é mais nosso (409)."""
        resp = httpx.post(
            f"{self.url}/api/ia-local/{job_id}/progresso",
            json={"claim_token": claim_token, "etapa": etapa, "palavras": palavras},
            headers=self.headers, timeout=15,
        )
        if resp.status_code == 409:
            return False
        resp.raise_for_status()
        return True

    def resultado(self, job_id: int, corpo: dict) -> None:
        for tentativa in range(5):
            try:
                resp = httpx.post(f"{self.url}/api/ia-local/{job_id}/resultado", json=corpo, headers=self.headers, timeout=60)
                if resp.status_code == 409:
                    _log(f"job {job_id}: o servidor recusou o resultado (409) -- o job já não era nosso")
                    return
                resp.raise_for_status()
                return
            except httpx.HTTPError as exc:
                espera = min(30, 2 ** tentativa)
                _log(f"falha ao enviar resultado do job {job_id} ({exc}); de novo em {espera} s")
                time.sleep(espera)
        raise RuntimeError(f"não consegui enviar o resultado do job {job_id}")

    def falha(self, job_id: int, claim_token: str, erro: str) -> None:
        try:
            httpx.post(
                f"{self.url}/api/ia-local/{job_id}/falha",
                json={"claim_token": claim_token, "erro": erro[:2000]}, headers=self.headers, timeout=15,
            )
        except httpx.HTTPError as exc:
            _log(f"não consegui nem reportar a falha do job {job_id}: {exc}")


class Batimento(threading.Thread):
    """Manda a etapa atual a cada poucos segundos -- é o heartbeat do job e o
    que a página mostra. Se o servidor responder 409, marca `abortado`."""

    def __init__(self, servidor: Servidor, job: dict):
        super().__init__(daemon=True)
        self.servidor = servidor
        self.job = job
        self.etapa: str | None = "a máquina recebeu"
        self.palavras: int | None = 0
        self.abortado = False
        self._parar = threading.Event()

    def atualizar(self, etapa: str | None = None, palavras: int | None = None, agora: bool = False) -> None:
        if etapa is not None:
            self.etapa = etapa
        if palavras is not None:
            self.palavras = palavras
        if agora:
            self._enviar()

    def _enviar(self) -> None:
        try:
            if not self.servidor.progresso(self.job["id"], self.job["claim_token"], self.etapa, self.palavras):
                self.abortado = True
        except httpx.HTTPError as exc:
            _log(f"progresso falhou (seguindo): {exc}")

    def run(self):
        while not self._parar.wait(INTERVALO_PROGRESSO_S):
            self._enviar()

    def parar(self):
        self._parar.set()


# --- o ouvinte ---------------------------------------------------------------------------


class Ouvinte:
    def __init__(self, servidor: Servidor, modelo: str, nome: str):
        self.servidor = servidor
        self.modelo = modelo
        self.nome = nome
        self.llama = LlamaServer(config.LLAMACPP_LOCAL_DIR, config.IA_LOCAL_PORTA, config.TMP_DIR / "ia_local", log=_log)
        self.lock = gpu_lock.LockGPU("ia_local")

    def _liberar_gpu(self, motivo: str) -> None:
        if self.llama.de_pe:
            _log(motivo)
            self.llama.parar()
        self.lock.soltar()

    def _presenca(self) -> dict:
        motor, ate = escolher_motor()
        ocupado = "transcrevendo — a IA local espera a GPU" if gpu_lock.pedido_pendente() else None
        return {
            "motor": motor,
            "modelo": "opus" if motor == "claude_cli" else (self.llama.modelo_ativo or self.modelo),
            "claude_autorizado_ate": ate.isoformat() if ate else None,
            "ocupado_etapa": ocupado,
        }

    def rodar(self, uma_vez: bool = False) -> None:
        if not config.ACCESS_TOKEN:
            _log("ACCESS_TOKEN não configurado no .env -- o servidor vai recusar tudo")
        _log(f'ouvinte "{self.nome}" -- servidor {self.servidor.url} -- modelo local {self.modelo}')
        espera_rede = 5
        try:
            while True:
                if gpu_lock.pedido_pendente():
                    self._liberar_gpu("a transcrição pediu a GPU -- derrubando o llama-server até ela terminar")
                elif self.llama.de_pe and time.monotonic() - self.llama.ultimo_uso > config.IA_LOCAL_OCIOSO_S:
                    self._liberar_gpu(f"{config.IA_LOCAL_OCIOSO_S / 60:.0f} min sem job -- derrubando o llama-server pra devolver a RAM")

                try:
                    job = self.servidor.proximo(self.nome, self._presenca())
                    espera_rede = 5
                except httpx.HTTPError as exc:
                    _log(f"servidor inacessível ({exc}); de novo em {espera_rede} s")
                    time.sleep(espera_rede)
                    espera_rede = min(60, espera_rede * 2)
                    continue
                if job is None:
                    continue
                self.processar(job)
                if uma_vez:
                    return
        finally:
            self._liberar_gpu("encerrando o ouvinte")

    def processar(self, job: dict) -> None:
        _log(f"job {job['id']} ({job['tipo']}, {len(job['chamadas'])} chamada(s))")
        batimento = Batimento(self.servidor, job)
        batimento.start()
        inicio = time.monotonic()
        try:
            motor, _ = escolher_motor()
            respostas, metricas, modelo = None, [], None
            if motor == "claude_cli":
                try:
                    respostas, metricas = self._com_claude(job, batimento)
                    modelo = "opus"
                except ChamadaAbortada:
                    raise
                except Exception as exc:  # noqa: BLE001 -- qualquer falha do Claude cai no local
                    _log(f"Claude falhou ({exc}); refazendo o job no modelo local")
                    motor = "local"
            if respostas is None:
                respostas, metricas, modelo = self._com_local(job, batimento)

            velocidades = [m["tokens_por_s"] for m in metricas if m.get("tokens_por_s")]
            corpo = {
                "claim_token": job["claim_token"],
                "respostas": [{"id": k, "conteudo": v} for k, v in respostas.items()],
                "motor": motor,
                "modelo": modelo,
                "segundos_total": round(time.monotonic() - inicio, 1),
                "tokens_por_s": round(sum(velocidades) / len(velocidades), 1) if velocidades else None,
                "reparos": 0,
            }
            batimento.atualizar(etapa="enviando o resultado", agora=True)
            self.servidor.resultado(job["id"], corpo)
            _log(f"job {job['id']} pronto em {corpo['segundos_total']:.0f} s ({modelo})")
        except ChamadaAbortada:
            _log(f"job {job['id']}: o servidor cancelou ou devolveu pra fila -- abandonando")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.servidor.falha(job["id"], job["claim_token"], f"{type(exc).__name__}: {exc}")
        finally:
            batimento.parar()

    def _com_claude(self, job: dict, batimento: Batimento) -> tuple[dict, list]:
        respostas, metricas = {}, []
        for chamada in job["chamadas"]:
            if batimento.abortado:
                raise ChamadaAbortada()
            batimento.atualizar(etapa=f"{chamada.get('rotulo') or chamada['id']} (Claude)", palavras=0, agora=True)
            respostas[chamada["id"]], m = claude_cli.executar(chamada, config.CLAUDE_BIN)
            metricas.append(m)
        return respostas, metricas

    def _com_local(self, job: dict, batimento: Batimento) -> tuple[dict, list, str]:
        # A transcrição tem prioridade na GPU: espera ela terminar.
        while not self.lock.tentar():
            batimento.atualizar(etapa="aguardando a GPU — a máquina está transcrevendo")
            if batimento.abortado:
                raise ChamadaAbortada()
            time.sleep(2)

        modelo = self.modelo
        try:
            batimento.atualizar(etapa="carregando o modelo", agora=True)
            self.llama.garantir(modelo, ao_esperar=lambda: None)
        except FaltaMemoria:
            modelo = config.IA_LOCAL_MODELO_RESERVA
            if modelo == self.modelo:
                raise
            _log(f"sem RAM para {self.modelo}; usando o modelo de reserva {modelo}")
            batimento.atualizar(etapa="pouca memória livre — usando o modelo rápido", agora=True)
            self.llama.garantir(modelo)

        respostas, metricas = {}, []
        for chamada in job["chamadas"]:
            batimento.atualizar(etapa=chamada.get("rotulo") or chamada["id"], palavras=0, agora=True)
            respostas[chamada["id"]], m = self.llama.executar(
                chamada,
                ao_progredir=lambda n: batimento.atualizar(palavras=n),
                abortado=lambda: batimento.abortado,
            )
            metricas.append(m)
        return respostas, metricas, modelo


# --- linha de comando ---------------------------------------------------------------------


def _status() -> None:
    dados = ler_local()
    ate = claude_autorizado_ate()
    print(f"modelo local padrão desta máquina: {modelo_padrao()}")
    print(f"modelo de reserva (pouca RAM): {config.IA_LOCAL_MODELO_RESERVA}")
    if ate:
        print(f"Claude AUTORIZADO até {ate.astimezone().strftime('%d/%m/%Y %H:%M')}")
    elif dados.get("claude_autorizado_ate"):
        print("Claude: autorização vencida -- usando o modelo local")
    else:
        print("Claude: não autorizado -- usando o modelo local")
    print(f"configuração local: {_arquivo_local()}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ouvinte da IA local das dissertativas")
    sub = parser.add_subparsers(dest="comando")
    p_aut = sub.add_parser("autorizar-claude", help="usa o Claude CLI por um tempo (padrão 24 h)")
    p_aut.add_argument("--horas", type=float, default=None)
    sub.add_parser("revogar-claude", help="volta a usar só o modelo local")
    p_mod = sub.add_parser("usar-modelo", help="grava o modelo local padrão desta máquina")
    p_mod.add_argument("modelo")
    sub.add_parser("status", help="mostra motor, modelo e autorização")
    parser.add_argument("--modelo", default=None, help="modelo local só nesta execução (id do LlamaCppLocal\\modelos.json)")
    parser.add_argument("--servidor", choices=["vps", "local"], default=None,
                        help="vps = SERVER_URL do .env; local = Docker dev em 127.0.0.1:8000")
    parser.add_argument("--uma-vez", action="store_true", help="processa um job e sai (teste)")
    args = parser.parse_args(argv)

    if args.comando == "autorizar-claude":
        ate = autorizar_claude(args.horas)
        print(f"Claude autorizado até {ate.astimezone().strftime('%d/%m/%Y %H:%M')} -- depois disso volta ao modelo local.")
        return
    if args.comando == "revogar-claude":
        revogar_claude()
        print("Autorização do Claude revogada -- usando só o modelo local.")
        return
    if args.comando == "usar-modelo":
        dados = ler_local()
        dados["modelo"] = args.modelo
        gravar_local(dados)
        print(f"Modelo local padrão desta máquina: {args.modelo}")
        return
    if args.comando == "status":
        _status()
        return

    url = SERVIDOR_LOCAL if args.servidor == "local" else config.SERVER_URL
    nome = f"ia-local-{socket.gethostname().lower()}"
    Ouvinte(Servidor(url), args.modelo or modelo_padrao(), nome).rodar(uma_vez=args.uma_vez)


if __name__ == "__main__":
    main()

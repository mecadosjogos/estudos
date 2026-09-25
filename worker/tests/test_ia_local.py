"""Ouvinte da IA local (PLANO.md, fase 13b): a escolha do motor pela
autorização do Claude (com prazo), o fallback do Claude pro local, a troca
pro modelo de reserva quando falta RAM, e o lock de GPU."""

from datetime import datetime, timedelta, timezone

import pytest

import worker.ia_local as ia
from shared import gpu_lock
from worker.motores import extrair_json
from worker.motores.llama_server import FaltaMemoria


@pytest.fixture(autouse=True)
def pasta_local_isolada(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu_lock, "pasta_local", lambda: tmp_path)
    return tmp_path


def test_sem_autorizacao_usa_local():
    assert ia.escolher_motor() == ("local", None)


def test_autorizacao_padrao_vale_24h():
    agora = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    ate = ia.autorizar_claude(agora=agora)
    assert ate == agora + timedelta(hours=24)
    assert ia.escolher_motor(agora + timedelta(hours=23)) == ("claude_cli", ate)
    assert ia.escolher_motor(agora + timedelta(hours=25)) == ("local", None)


def test_autorizacao_com_horas_e_revogacao():
    agora = datetime.now(timezone.utc)
    ia.autorizar_claude(2, agora=agora)
    assert ia.escolher_motor(agora + timedelta(hours=1))[0] == "claude_cli"
    ia.revogar_claude()
    assert ia.escolher_motor(agora + timedelta(minutes=1)) == ("local", None)


def test_modelo_padrao_desta_maquina_vem_do_arquivo_local(monkeypatch):
    monkeypatch.setattr(ia.config, "IA_LOCAL_MODELO", "qwen3.5-4b")
    assert ia.modelo_padrao() == "qwen3.5-4b"
    ia.main(["usar-modelo", "gemma4-26b-a4b"])
    assert ia.modelo_padrao() == "gemma4-26b-a4b"


class _ServidorFalso:
    url = "http://falso"

    def __init__(self):
        self.resultados, self.falhas = [], []

    def progresso(self, *a, **k):
        return True

    def resultado(self, job_id, corpo):
        self.resultados.append(corpo)

    def falha(self, job_id, token, erro):
        self.falhas.append(erro)


class _LlamaFalso:
    def __init__(self, sem_ram_para=()):
        self.sem_ram_para = set(sem_ram_para)
        self.modelo_ativo = None
        self.de_pe = False
        self.ultimo_uso = 0.0

    def garantir(self, modelo, ao_esperar=None):
        if modelo in self.sem_ram_para:
            raise FaltaMemoria(modelo)
        self.modelo_ativo = modelo
        self.de_pe = True

    def parar(self):
        self.de_pe = False

    def executar(self, chamada, ao_progredir, abortado):
        return {"ok": chamada["id"]}, {"tokens_por_s": 10.0}


JOB = {"id": 1, "claim_token": "t", "tipo": "dissertativa_julgar",
       "chamadas": [{"id": "ponto-0", "rotulo": "julgando", "sistema": "s", "prompt": "p", "schema": {}}]}


def _ouvinte(llama):
    ouvinte = ia.Ouvinte(_ServidorFalso(), "gemma4-26b-a4b", "teste")
    ouvinte.llama = llama
    return ouvinte


def test_falta_de_ram_cai_no_modelo_de_reserva(monkeypatch):
    monkeypatch.setattr(ia.config, "IA_LOCAL_MODELO_RESERVA", "qwen3.5-4b")
    ouvinte = _ouvinte(_LlamaFalso(sem_ram_para={"gemma4-26b-a4b"}))
    ouvinte.processar(JOB)
    corpo = ouvinte.servidor.resultados[0]
    assert corpo["modelo"] == "qwen3.5-4b"
    assert corpo["motor"] == "local"
    assert corpo["respostas"] == [{"id": "ponto-0", "conteudo": {"ok": "ponto-0"}}]


def test_claude_autorizado_que_falha_refaz_no_local(monkeypatch):
    ia.autorizar_claude(1)

    def claude_quebrado(chamada, claude_bin):
        raise RuntimeError("sem internet")

    monkeypatch.setattr(ia.claude_cli, "executar", claude_quebrado)
    ouvinte = _ouvinte(_LlamaFalso())
    ouvinte.processar(JOB)
    corpo = ouvinte.servidor.resultados[0]
    assert corpo["motor"] == "local"
    assert corpo["modelo"] == "gemma4-26b-a4b"


def test_claude_autorizado_responde(monkeypatch):
    ia.autorizar_claude(1)
    monkeypatch.setattr(ia.claude_cli, "executar", lambda chamada, claude_bin: ({"de": "claude"}, {}))
    ouvinte = _ouvinte(_LlamaFalso())
    ouvinte.processar(JOB)
    corpo = ouvinte.servidor.resultados[0]
    assert corpo["motor"] == "claude_cli" and corpo["modelo"] == "opus"
    assert ouvinte.llama.de_pe is False  # Claude não precisa da GPU


def test_lock_de_gpu_e_exclusivo():
    a, b = gpu_lock.LockGPU("a"), gpu_lock.LockGPU("b")
    assert a.tentar()
    assert not b.tentar()
    a.soltar()
    assert b.tentar()
    b.soltar()


def test_pedido_de_gpu_aparece_e_some():
    assert not gpu_lock.pedido_pendente()
    with gpu_lock.usar_gpu("transcricao"):
        assert gpu_lock.pedido_pendente()
    assert not gpu_lock.pedido_pendente()


def test_extrair_json_de_texto_com_conversa():
    assert extrair_json('Claro!\n```json\n{"a": 1}\n```\nAbraço') == {"a": 1}
    assert extrair_json('{"a": 2}') == {"a": 2}
    assert extrair_json('lixo antes {"a": 3} lixo depois') == {"a": 3}

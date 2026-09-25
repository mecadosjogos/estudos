"""Motor Claude: `claude -p` (Claude Code CLI, assinatura do usuário -- nunca
a API paga) nesta máquina. Só é usado quando alguém AUTORIZA aqui, por um
tempo (`python -m worker.ia_local autorizar-claude --horas N`, padrão 24 h);
fora disso o ouvinte usa sempre o modelo local. Ver worker/ia_local.py.

Sem ferramentas (`--tools ""`) e sem `--dangerously-skip-permissions`: a
tarefa é só ler o prompt e devolver JSON, então não há nada a permitir.
`--json-schema` pede saída estruturada; se a versão do CLI não devolver o
campo estruturado, cai no texto do resultado e extrai o JSON dele.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

from . import RespostaInvalida, extrair_json

TIMEOUT_S = 300


def resolver_executavel(claude_bin: str) -> str:
    """No Windows, o `claude` do npm é um .cmd que chama um claude.exe
    nativo. Passar o JSON Schema como argumento por um .cmd atravessa as
    regras de aspas do cmd.exe (que não são as do resto do Windows) -- então
    usa o .exe direto quando ele existe."""
    caminho = shutil.which(claude_bin)
    if caminho is None:
        raise RuntimeError(f"'{claude_bin}' não está no PATH -- instale o Claude Code ou ajuste CLAUDE_BIN no .env")
    if caminho.lower().endswith(".cmd"):
        exe = Path(caminho).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if exe.exists():
            return str(exe)
    return caminho


def executar(chamada: dict, claude_bin: str = "claude") -> tuple[dict, dict]:
    prompt = (
        f"{chamada['sistema']}\n\n{chamada['prompt']}\n\n"
        "Responda APENAS com um objeto JSON que siga exatamente este JSON Schema:\n"
        f"{json.dumps(chamada['schema'], ensure_ascii=False)}"
    )
    comando = [
        resolver_executavel(claude_bin), "-p",
        "--model", "opus",
        "--output-format", "json",
        "--tools", "",
        "--json-schema", json.dumps(chamada["schema"], ensure_ascii=False),
    ]
    inicio = time.monotonic()
    proc = subprocess.run(
        comando, input=prompt, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p saiu com {proc.returncode}: {(proc.stderr or proc.stdout)[:500]}")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RespostaInvalida(f"saída do claude -p não é JSON: {exc}") from exc
    if envelope.get("is_error"):
        raise RuntimeError(f"claude -p devolveu erro: {str(envelope.get('result'))[:500]}")

    estruturado = envelope.get("structured_output")
    conteudo = estruturado if isinstance(estruturado, dict) else extrair_json(str(envelope.get("result", "")))
    segundos = time.monotonic() - inicio
    uso = envelope.get("usage") or {}
    tokens = uso.get("output_tokens")
    return conteudo, {"tokens": tokens, "tokens_por_s": (tokens / segundos) if tokens and segundos else None}

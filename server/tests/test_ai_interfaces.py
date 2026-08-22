"""Confirma que os clientes injetáveis (Integridade, Limites operacionais do
PLANO.md) funcionam sem chamada real — é o que permite os testes futuros de
reprocessamento e recorte de contexto rodar offline."""


def test_fake_ai_client_records_calls():
    from app.ai.client import AIResponse, FakeAIClient

    client = FakeAIClient(AIResponse(content='{"ok": true}', input_tokens=10, output_tokens=5))
    result = client.structured_call(prompt="teste", schema={})

    assert result.content == '{"ok": true}'
    assert client.calls == ["teste"]


def test_fake_asr_client_records_calls():
    from app.media.asr import FakeASRClient, TranscriptionResult

    client = FakeASRClient(TranscriptionResult(text="ola", words=[]))
    result = client.transcribe("aula.mp3")

    assert result.text == "ola"
    assert client.calls == ["aula.mp3"]
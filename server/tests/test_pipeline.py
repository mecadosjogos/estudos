"""Testa o pipeline de processamento de aula (fase 6) de ponta a ponta,
usando FakeAIClient — sem chamada real, sem custo, sem esperar minutos.
Cobre especificamente as regras de Integridade do PLANO.md: deriv_key
estável entre reprocessamentos, diff (substitui/preserva/insere/órfão) e
teto de custo verificado antes da chamada.
"""

import json
from datetime import date, datetime, timezone

import pytest

# app.ai.pipeline importa app.ai.budget, que lê app.config no topo do
# módulo — se isso for importado aqui (tempo de coleta do pytest, antes do
# fixture app_env recriar os módulos), monkeypatch.setattr(config, ...)
# em algum teste modifica uma instância de config diferente da que o
# pipeline enxerga. Por isso os imports de app.* ficam dentro de cada
# função de teste, depois que app_env já rodou — mesmo padrão do resto
# da suíte.
from app.ai.client import AIResponse, FakeAIClient


def _make_lesson_with_transcript(session, texts_with_times, titulo="Aula") -> int:
    from sqlalchemy import select

    from app.models import Lesson, Subject, Transcript, TranscriptSegment

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()

    transcript = Transcript(
        lesson_id=lesson.id, engine="faster-whisper-large-v3", worker_name="desktop-4070",
        full_text=" ".join(t for _, _, t in texts_with_times), duration_s=texts_with_times[-1][1],
    )
    session.add(transcript)
    session.flush()

    for i, (start_s, end_s, text) in enumerate(texts_with_times):
        words = [
            {"text": w, "start_s": start_s, "end_s": end_s, "probability": 0.95}
            for w in text.split()
        ]
        session.add(
            TranscriptSegment(
                transcript_id=transcript.id, idx=i, start_s=start_s, end_s=end_s, text=text,
                words_json=json.dumps(words),
            )
        )
    session.commit()
    return lesson.id


def _default_lesson_id(session, titulo="Aula") -> int:
    return _make_lesson_with_transcript(
        session,
        [
            (0.0, 5.0, "a posse exige corpus e animus"),
            (5.0, 10.0, "segue explicação complementar sobre o tema"),
        ],
        titulo=titulo,
    )


def _fake_response(overrides=None):
    payload = {
        "resumo": "Resumo da aula sobre posse e propriedade.",
        "aula_editada": [
            {"tipo": "destaque-prova", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0},
            {"tipo": "normal", "texto": "Segue explicação complementar.", "start_s": 5.0, "end_s": 10.0},
        ],
        "indice": [{"titulo": "Posse", "start_s": 0.0, "end_s": 10.0}],
        "guia_titulo": "Posse",
        "guia_arvore": [],
        "guia_secoes": [{"titulo": "Posse", "corpo": "Guia de teste."}],
        "guia_topicos": [{"titulo": "Posse"}],
        "guia_trechos_incompletos": [],
        "artigos": [{"texto_citado": "art. 1.196 CC", "start_s": 1.0}],
        "datas_anunciadas": [{"texto": "prova dia 12 de abril", "data_anunciada": "2026-04-12", "start_s": 8.0}],
        "cards": [{"frente": "O que é posse?", "verso": "Exercício de fato de poderes de propriedade.", "start_s": 0.0, "end_s": 5.0}],
        "termos": [],
        "pares_confundiveis": [],
        "mapa_mermaid": None,
        "assuntos": ["Posse"],
    }
    if overrides:
        payload.update(overrides)
    return AIResponse(content=json.dumps(payload), input_tokens=27000, output_tokens=12000, cache_read_input_tokens=0)


def test_process_lesson_automatically_persists_everything(app_env):
    from app.db import holder
    from app.ai.pipeline import ProcessingError, ingest_manual_response, process_lesson_automatically
    from app.models import AiCall, ArticleMention, CardProposal, EditedBlock, Lesson, OutlineItem, AnnouncementProposal

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        ai_call = process_lesson_automatically(session, lesson, FakeAIClient(_fake_response()))

        assert ai_call.via == "automatico"
        assert ai_call.custo_usd > 0
        persisted = session.get(Lesson, lesson_id)
        assert persisted.resumo.startswith("Resumo")
        # Guia de aula (fase 6 revisada): sai da MESMA chamada, sem
        # segunda leitura da transcrição -- ver ai/schemas.py, guia_md.
        assert persisted.guia_md.startswith("# Posse")
        assert persisted.guia_gerado_em is not None
        assert session.query(EditedBlock).filter_by(lesson_id=lesson_id).count() == 2
        assert session.query(OutlineItem).filter_by(lesson_id=lesson_id).count() == 1
        assert session.query(ArticleMention).filter_by(lesson_id=lesson_id).count() == 1
        assert session.query(AnnouncementProposal).filter_by(lesson_id=lesson_id).count() == 1
        assert session.query(CardProposal).filter_by(lesson_id=lesson_id).count() == 1

        announcement = session.query(AnnouncementProposal).filter_by(lesson_id=lesson_id).first()
        assert announcement.data_anunciada == date(2026, 4, 12)

        stored_calls = session.query(AiCall).all()
        assert len(stored_calls) == 1
        assert json.loads(stored_calls[0].raw_response_json)["assuntos"] == ["Posse"]


def test_process_lesson_persists_termos_as_pending_definitions(app_env):
    """Fase 11: `termos` vira `Definition` pendente, com `term_id` ainda
    nulo -- só a aceitação (routes/glossary.py) resolve/cria o `Term`
    global, pra grafia errada da IA não poluir o glossário antes de você
    poder corrigir (PLANO.md)."""
    from app.db import holder
    from app.ai.pipeline import process_lesson_automatically
    from app.models import Definition, Lesson

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        response = _fake_response(
            {
                "termos": [
                    {
                        "termo": "Posse",
                        "definicao": "Exercício de fato de poderes de propriedade.",
                        "citacao_literal": "a gente chama isso de posse",
                        "start_s": 0.0,
                        "variantes": ["posse direta", "posse indireta"],
                    }
                ]
            }
        )
        process_lesson_automatically(session, lesson, FakeAIClient(response))

        definitions = session.query(Definition).filter_by(lesson_id=lesson_id).all()
        assert len(definitions) == 1
        d = definitions[0]
        assert d.term_id is None
        assert d.termo_proposto == "Posse"
        assert d.definicao_md == "Exercício de fato de poderes de propriedade."
        assert d.citacao_literal == "a gente chama isso de posse"
        assert json.loads(d.variantes_propostas_json) == ["posse direta", "posse indireta"]
        assert d.status == "proposto"
        assert d.origem == "ia"
        assert d.subject_id == lesson.subject_id


def test_reprocessing_preserves_edited_card_and_flags_new_version(app_env):
    from app.db import holder
    from app.ai.pipeline import ProcessingError, ingest_manual_response, process_lesson_automatically
    from app.models import CardProposal, Lesson

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        process_lesson_automatically(session, lesson, FakeAIClient(_fake_response()))

        card = session.query(CardProposal).filter_by(lesson_id=lesson_id).one()
        card.verso = "Resposta que eu mesmo corrigi."
        card.editado_em = datetime.now(timezone.utc)
        session.commit()
        edited_card_id = card.id

    with holder.SessionLocal() as session:
        lesson = session.get(Lesson, lesson_id)
        client2 = FakeAIClient(_fake_response({
            "cards": [{"frente": "O que é posse?", "verso": "Nova redação da IA.", "start_s": 0.0, "end_s": 5.0}],
        }))
        process_lesson_automatically(session, lesson, client2)

    with holder.SessionLocal() as session:
        cards = session.query(CardProposal).filter_by(lesson_id=lesson_id).all()
        assert len(cards) == 1, "mesmo deriv_key (mesmo trecho fonte) não deve duplicar"
        preserved = cards[0]
        assert preserved.id == edited_card_id
        assert preserved.verso == "Resposta que eu mesmo corrigi.", "edição do usuário precisa sobreviver"
        assert preserved.versao_nova_json is not None
        assert json.loads(preserved.versao_nova_json)["verso"] == "Nova redação da IA."


def test_reprocessing_replaces_untouched_card(app_env):
    from app.db import holder
    from app.ai.pipeline import ProcessingError, ingest_manual_response, process_lesson_automatically
    from app.models import CardProposal, Lesson

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        process_lesson_automatically(session, lesson, FakeAIClient(_fake_response()))

    with holder.SessionLocal() as session:
        lesson = session.get(Lesson, lesson_id)
        client2 = FakeAIClient(_fake_response({
            "cards": [{"frente": "O que é posse?", "verso": "Verso atualizado sem edição prévia.", "start_s": 0.0, "end_s": 5.0}],
        }))
        process_lesson_automatically(session, lesson, client2)

    with holder.SessionLocal() as session:
        cards = session.query(CardProposal).filter_by(lesson_id=lesson_id).all()
        assert len(cards) == 1
        assert cards[0].verso == "Verso atualizado sem edição prévia."


def test_reprocessing_marks_vanished_block_as_orphan_not_deleted(app_env):
    from app.db import holder
    from app.ai.pipeline import ProcessingError, ingest_manual_response, process_lesson_automatically
    from app.models import EditedBlock, Lesson

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        process_lesson_automatically(session, lesson, FakeAIClient(_fake_response()))

    with holder.SessionLocal() as session:
        lesson = session.get(Lesson, lesson_id)
        # segunda passada só devolve um dos dois blocos originais
        client2 = FakeAIClient(_fake_response({
            "aula_editada": [
                {"tipo": "destaque-prova", "texto": "A posse exige corpus e animus (reformulado).", "start_s": 0.0, "end_s": 5.0},
            ],
        }))
        process_lesson_automatically(session, lesson, client2)

    with holder.SessionLocal() as session:
        blocks = session.query(EditedBlock).filter_by(lesson_id=lesson_id).all()
        assert len(blocks) == 2, "órfão nunca é apagado"
        orphaned = [b for b in blocks if b.orfao_em is not None]
        assert len(orphaned) == 1
        assert orphaned[0].texto == "Segue explicação complementar."


def test_new_deriv_key_inserts_as_new_proposal(app_env):
    from app.db import holder
    from app.ai.pipeline import ProcessingError, ingest_manual_response, process_lesson_automatically
    from app.models import EditedBlock, Lesson

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        process_lesson_automatically(session, lesson, FakeAIClient(_fake_response()))

    with holder.SessionLocal() as session:
        lesson = session.get(Lesson, lesson_id)
        client2 = FakeAIClient(_fake_response({
            "aula_editada": [
                {"tipo": "destaque-prova", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0},
                {"tipo": "normal", "texto": "Segue explicação complementar.", "start_s": 5.0, "end_s": 10.0},
                {"tipo": "conceito", "texto": "Bloco novo que não existia antes.", "start_s": 20.0, "end_s": 25.0},
            ],
        }))
        process_lesson_automatically(session, lesson, client2)

    with holder.SessionLocal() as session:
        blocks = session.query(EditedBlock).filter_by(lesson_id=lesson_id).all()
        assert len(blocks) == 3
        non_orphan_texts = {b.texto for b in blocks if b.orfao_em is None}
        assert "Bloco novo que não existia antes." in non_orphan_texts


def test_two_cards_from_same_interval_do_not_collide(app_env):
    from app.db import holder
    from app.ai.pipeline import ProcessingError, ingest_manual_response, process_lesson_automatically
    from app.models import CardProposal, Lesson

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        client = FakeAIClient(_fake_response({
            "cards": [
                {"frente": "Pergunta 1", "verso": "Resposta 1", "start_s": 0.0, "end_s": 5.0},
                {"frente": "Pergunta 2", "verso": "Resposta 2", "start_s": 0.0, "end_s": 5.0},
            ],
        }))
        process_lesson_automatically(session, lesson, client)

    with holder.SessionLocal() as session:
        cards = session.query(CardProposal).filter_by(lesson_id=lesson_id).all()
        assert len(cards) == 2
        assert {c.frente for c in cards} == {"Pergunta 1", "Pergunta 2"}


def test_low_confidence_flagged_from_whisper_word_probability(app_env):
    from sqlalchemy import select

    from app.db import holder
    from app.ai.pipeline import ProcessingError, ingest_manual_response, process_lesson_automatically
    from app.models import ArticleMention, Lesson, Subject, Transcript, TranscriptSegment

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Aula baixa confiança", data=date(2026, 3, 12))
        session.add(lesson)
        session.flush()

        transcript = Transcript(
            lesson_id=lesson.id, engine="e", worker_name="w",
            full_text="art mil duzentos e trinta e oito", duration_s=5.0,
        )
        session.add(transcript)
        session.flush()
        low_prob_words = [{"text": w, "start_s": 0.0, "end_s": 1.0, "probability": 0.2} for w in ["art", "1238"]]
        session.add(TranscriptSegment(
            transcript_id=transcript.id, idx=0, start_s=0.0, end_s=2.0,
            text="art. 1.238", words_json=json.dumps(low_prob_words),
        ))
        session.commit()
        lesson_id = lesson.id

        client = FakeAIClient(_fake_response({
            "artigos": [{"texto_citado": "art. 1.238 CC", "start_s": 0.0}],
        }))
        process_lesson_automatically(session, session.get(Lesson, lesson_id), client)

    with holder.SessionLocal() as session:
        mention = session.query(ArticleMention).filter_by(lesson_id=lesson_id).one()
        assert mention.baixa_confianca is True


def test_budget_exceeded_blocks_call_before_it_happens(app_env, monkeypatch):
    """O teto não sabe o custo antes de chamar (isso só se sabe depois) —
    então ele bloqueia a PRÓXIMA chamada quando o gasto acumulado já
    estourou, não a primeira que estourou sozinha."""
    from app import config
    from app.db import holder
    from app.ai.pipeline import ProcessingError, ingest_manual_response, process_lesson_automatically
    from app.models import Lesson

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        process_lesson_automatically(session, lesson, FakeAIClient(_fake_response()))

    monkeypatch.setattr(config, "AI_MONTHLY_BUDGET_USD", 0.0001)

    with holder.SessionLocal() as session:
        lesson = session.get(Lesson, lesson_id)
        client = FakeAIClient(_fake_response())

        with pytest.raises(Exception) as exc_info:
            process_lesson_automatically(session, lesson, client)

        assert "teto" in str(exc_info.value).lower()
        assert client.calls == [], "a chamada não pode nem ter sido tentada"


def test_ingest_manual_response_parses_pasted_text(app_env):
    from app.db import holder
    from app.ai.pipeline import ProcessingError, ingest_manual_response, process_lesson_automatically
    from app.models import Lesson

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        pasted = "Aqui está a resposta:\n\n```json\n" + _fake_response().content + "\n```\n\nEspero que ajude!"

        ai_call = ingest_manual_response(session, lesson, pasted)

        assert ai_call.via == "manual"
        assert ai_call.custo_usd == 0.0
        assert session.get(Lesson, lesson_id).resumo is not None


def test_ingest_manual_response_rejects_garbage(app_env):
    from app.db import holder
    from app.ai.pipeline import ProcessingError, ingest_manual_response, process_lesson_automatically
    from app.models import Lesson

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        with pytest.raises(Exception):
            ingest_manual_response(session, lesson, "isso não é json nenhum")


def test_pares_confundiveis_become_discrimination_cards(app_env):
    from app.db import holder
    from app.ai.pipeline import process_lesson_automatically
    from app.models import CardProposal, Lesson

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        client = FakeAIClient(_fake_response({
            "pares_confundiveis": [
                {
                    "termo_a": "dolo eventual",
                    "termo_b": "culpa consciente",
                    "eixo_distincao": "assumir o risco x confiar que não ocorrerá",
                    "start_s_a": 12.0,
                    "end_s_a": 20.0,
                    "start_s_b": 40.0,
                    "end_s_b": 48.0,
                },
            ],
        }))
        process_lesson_automatically(session, lesson, client)

    with holder.SessionLocal() as session:
        pairs = session.query(CardProposal).filter_by(lesson_id=lesson_id, tipo="discriminacao").all()
        assert len(pairs) == 1
        pair = pairs[0]
        assert pair.termo_a == "culpa consciente"  # canonizado em ordem alfabética
        assert pair.termo_b == "dolo eventual"
        assert pair.start_s_a == 40.0
        assert pair.start_s_b == 12.0
        assert pair.eixo_distincao == "assumir o risco x confiar que não ocorrerá"
        assert pair.status == "pendente"
        # cards normais continuam intactos, na mesma tabela
        flashcards = session.query(CardProposal).filter_by(lesson_id=lesson_id, tipo="flashcard").all()
        assert len(flashcards) == 1


def test_pares_confundiveis_without_timestamps_are_tolerated(app_env):
    from app.db import holder
    from app.ai.pipeline import process_lesson_automatically
    from app.models import CardProposal, Lesson

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        client = FakeAIClient(_fake_response({
            "pares_confundiveis": [
                {"termo_a": "nulidade", "termo_b": "anulabilidade", "eixo_distincao": "interesse público x privado"},
            ],
        }))
        process_lesson_automatically(session, lesson, client)

    with holder.SessionLocal() as session:
        pair = session.query(CardProposal).filter_by(lesson_id=lesson_id, tipo="discriminacao").one()
        assert pair.start_s_a is None
        assert pair.start_s_b is None
        assert pair.start_s == 0.0  # placeholder, nunca lido pra este tipo


def test_pares_confundiveis_reconcile_preserves_edit_across_reprocessing(app_env):
    from app.db import holder
    from app.ai.pipeline import process_lesson_automatically
    from app.models import CardProposal, Lesson

    pares = [
        {
            "termo_a": "prescrição",
            "termo_b": "decadência",
            "eixo_distincao": "extingue a pretensão x extingue o direito",
            "start_s_a": 5.0, "end_s_a": 9.0, "start_s_b": 15.0, "end_s_b": 19.0,
        },
    ]

    with holder.SessionLocal() as session:
        lesson_id = _default_lesson_id(session)
        lesson = session.get(Lesson, lesson_id)
        process_lesson_automatically(session, lesson, FakeAIClient(_fake_response({"pares_confundiveis": pares})))

        pair = session.query(CardProposal).filter_by(lesson_id=lesson_id, tipo="discriminacao").one()
        pair.verso = "Minha própria explicação do eixo."
        pair.editado_em = datetime.now(timezone.utc)
        session.commit()
        edited_id = pair.id

    with holder.SessionLocal() as session:
        lesson = session.get(Lesson, lesson_id)
        # mesma dupla de termos (ordem trocada), eixo reformulado -- deve
        # cair na MESMA linha por identidade de termos, não duplicar
        client2 = FakeAIClient(_fake_response({
            "pares_confundiveis": [
                {**pares[0], "termo_a": "decadência", "termo_b": "prescrição", "eixo_distincao": "reformulado pela IA"},
            ],
        }))
        process_lesson_automatically(session, lesson, client2)

    with holder.SessionLocal() as session:
        pairs = session.query(CardProposal).filter_by(lesson_id=lesson_id, tipo="discriminacao").all()
        assert len(pairs) == 1, "mesma dupla de termos não deve duplicar"
        preserved = pairs[0]
        assert preserved.id == edited_id
        assert preserved.verso == "Minha própria explicação do eixo.", "edição do usuário precisa sobreviver"


def test_process_without_transcript_raises_clear_error(app_env):
    from sqlalchemy import select

    from app.db import holder
    from app.ai.pipeline import ProcessingError, ingest_manual_response, process_lesson_automatically
    from app.models import Lesson, Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Sem transcrição", data=date(2026, 3, 12))
        session.add(lesson)
        session.commit()

        with pytest.raises(ProcessingError):
            process_lesson_automatically(session, lesson, FakeAIClient(_fake_response()))

from sqlalchemy import select

from app.glossary.mermaid import link_mermaid_nodes_to_glossary


def _make_term(session, rotulo):
    from app.glossary.merge import find_or_create_term

    term = find_or_create_term(session, rotulo)
    session.commit()
    return term


def test_links_matched_node_labels_to_glossary(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        term = _make_term(session, "Posse")
        mermaid_src = "graph TD\n  A[Posse] --> B[Propriedade]\n"
        result = link_mermaid_nodes_to_glossary(mermaid_src, session)
        assert f'click A "/termos/{term.id}" "_self"' in result
        assert "click B" not in result


def test_matches_accent_and_case_insensitively(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        term = _make_term(session, "Usucapião")
        mermaid_src = "graph TD\n  X[usucapiao extraordinaria]\n"
        # rotulo exato "Usucapião" nao bate com "usucapiao extraordinaria" -- sem match
        result = link_mermaid_nodes_to_glossary(mermaid_src, session)
        assert "click X" not in result

        mermaid_src2 = "graph TD\n  X[USUCAPIAO]\n"
        result2 = link_mermaid_nodes_to_glossary(mermaid_src2, session)
        assert f'click X "/termos/{term.id}" "_self"' in result2


def test_recognizes_different_node_shapes(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        term = _make_term(session, "Dolo")
        for src in ["A[Dolo]", "A(Dolo)", "A{Dolo}", "A([Dolo])", "A[[Dolo]]"]:
            mermaid_src = f"graph TD\n  {src}\n"
            result = link_mermaid_nodes_to_glossary(mermaid_src, session)
            assert f'click A "/termos/{term.id}" "_self"' in result, f"failed for shape {src!r}"


def test_no_matches_returns_source_unchanged(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        mermaid_src = "graph TD\n  A[Nada aqui] --> B[Tampouco]\n"
        result = link_mermaid_nodes_to_glossary(mermaid_src, session)
        assert result == mermaid_src


def test_empty_glossary_returns_source_unchanged(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        mermaid_src = "graph TD\n  A[Posse]\n"
        result = link_mermaid_nodes_to_glossary(mermaid_src, session)
        assert result == mermaid_src


def test_empty_mermaid_source(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        assert link_mermaid_nodes_to_glossary("", session) == ""
        assert link_mermaid_nodes_to_glossary(None, session) is None

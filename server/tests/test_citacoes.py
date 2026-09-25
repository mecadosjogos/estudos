from app.ai.citacoes import trecho_existe

RESPOSTA = "A posse de João se caracteriza pelo corpus, que é o contato físico com o relógio. Ele usa todo dia."


def test_trecho_literal_existe():
    assert trecho_existe("pelo corpus, que é o contato físico", RESPOSTA)


def test_tolera_caixa_acento_e_pontuacao():
    assert trecho_existe("CORPUS que e o contato fisico com o relogio", RESPOSTA)


def test_tolera_uma_palavra_trocada_em_trecho_longo():
    assert trecho_existe("se caracteriza pelo corpus que é um contato físico com o relógio", RESPOSTA)


def test_frase_inventada_nao_existe():
    assert not trecho_existe("João tinha a intenção de ser dono do relógio", RESPOSTA)


def test_trecho_curto_so_vale_exato():
    assert trecho_existe("usa todo dia", RESPOSTA)
    assert not trecho_existe("usa toda hora", RESPOSTA)


def test_vazio_nao_existe():
    assert not trecho_existe("", RESPOSTA)
    assert not trecho_existe("   ", RESPOSTA)


def test_entrega_o_ponto():
    from app.ai.citacoes import entrega_o_ponto

    ponto = "O caso envolve o poder econômico, pois João cedeu em troca de dinheiro para a subsistência."
    assert entrega_o_ponto("Escreva que o caso envolve o poder econômico: João cedeu por dinheiro e subsistência.", ponto)
    assert not entrega_o_ponto("Releia a seção 1 e identifique qual forma de poder explica a conduta.", ponto)

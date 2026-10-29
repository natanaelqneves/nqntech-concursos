from datetime import date
from decimal import Decimal

import pytest

from coletor.texto import (
    contem_termo,
    data_por_extenso,
    escolaridade_por_texto,
    limitar,
    normalizar,
    titulo_portugues,
    todas_as_datas,
    uf_por_nome,
    valores_monetarios,
)


def test_normalizar_remove_acento_caixa_e_travessao():
    assert normalizar("  TI – Segurança   da Informação ") == "ti - seguranca da informacao"


@pytest.mark.parametrize(
    ("texto", "termo", "esperado"),
    [
        ("analista - area de ti", "ti", True),
        ("agente de transito", "ti", False),
        ("ativo imobilizado", "ti", False),
        ("analista ti - banco de dados", "banco de dados", True),
        ("tecnico em informatica", "informática", True),
    ],
)
def test_contem_termo_por_palavra_inteira(texto, termo, esperado):
    assert contem_termo(texto, termo) is esperado


def test_datas_por_extenso_e_numericas_em_ordem_de_aparicao():
    trecho = "das 16h do dia 20 de outubro de 2026 até às 16h do dia 18 de novembro de 2026; prova em 24/01/2027"
    assert todas_as_datas(trecho) == [date(2026, 10, 20), date(2026, 11, 18), date(2027, 1, 24)]
    assert data_por_extenso("realizadas no dia 1º de março de 2027") == date(2027, 3, 1)


def test_data_invalida_e_ignorada():
    assert data_por_extenso("31 de fevereiro de 2026") is None


def test_valores_monetarios():
    assert valores_monetarios("R$ 7.526,14 e r$ 120,00") == [Decimal("7526.14"), Decimal("120.00")]


@pytest.mark.parametrize(
    ("texto", "uf"),
    [
        ("Tribunal de Justiça do Estado da Paraíba", "PB"),
        ("Polícia Civil do Paraná", "PR"),
        ("Tribunal de Contas do Estado de Mato Grosso do Sul", "MS"),
        ("Tribunal de Justiça do Estado de Mato Grosso", "MT"),
        ("Concurso Público para Prefeitura de Macaé", None),
    ],
)
def test_uf_por_nome(texto, uf):
    assert uf_por_nome(texto) == uf


def test_limitar_remove_nul_e_corta():
    assert limitar("ab\x00cdef", 4) == "abcd"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("TRIBUNAL DE JUSTIÇA DO ESTADO DA PARAÍBA", "Tribunal de Justiça do Estado da Paraíba"),
        ("CONSELHO REGIONAL DA 22ª REGIÃO – CREF22/ES", "Conselho Regional da 22ª Região – CREF22/ES"),
        ("SECRETARIA DE EDUCAÇÃO DE CHAPADÃO DO SUL/MS", "Secretaria de Educação de Chapadão do Sul/MS"),
        ("ANALISTA DE TI", "Analista de TI"),
        ("ANALISTA FISC. MUN.-TI", "Analista Fisc. Mun.-TI"),
        ("AUXILIAR - ADMINISTRATIVO", "Auxiliar - Administrativo"),
        ("Já Em Caixa Mista", "Já Em Caixa Mista"),
    ],
)
def test_titulo_portugues(texto, esperado):
    assert titulo_portugues(texto) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Escolaridade: MÉDIO na modalidade MAGISTÉRIO", "MEDIO"),
        ("NIVEL FUNDAMENTAL", "FUNDAMENTAL"),
        ("MÉDIO/TECNICO", "TECNICO"),
        ("Ensino Superior", "SUPERIOR"),
        ("Alfabetizado", "FUNDAMENTAL"),
        (None, None),
    ],
)
def test_escolaridade_por_texto(texto, esperado):
    assert escolaridade_por_texto(texto) == esperado

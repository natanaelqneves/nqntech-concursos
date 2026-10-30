"""Isenção, calendário, disciplinas e prova discursiva com editais reais da FGV (fixtures, sem internet)."""

from datetime import date

import pytest

from coletor.extratores.base import CargoExtraido
from coletor.extratores.fgv import ExtratorFGV
from coletor.extratores.secoes import (
    QuadroDisciplinas,
    atribuir_disciplinas,
    datas_com_ano_inferido,
    extrair_isencoes,
    redacao_por_cargo,
)


def _edital(fixture_texto, nome: str):
    return ExtratorFGV().extrair(fixture_texto(f"fgv/{nome}.txt"))


def test_tjpb_2026_isencoes_prazo_e_calendario(fixture_texto):
    edital = _edital(fixture_texto, "edital_tjpb26_1")

    assert {i.codigo for i in edital.isencoes} == {
        "CADUNICO",
        "DOADOR_SANGUE",
        "DOADOR_MEDULA",
        "JURADO",
        "VITIMA_VIOLENCIA_DOMESTICA",
        "DOADOR_PLASMA",
        "OUTRA",
    }
    outra = next(i for i in edital.isencoes if i.codigo == "OUTRA")
    assert outra.observacao == "Doadores de leite humano"
    # Edital consolidado com a 1ª retificação: o pedido de isenção vai só até 27/10 (antes, 18/11).
    assert (edital.isencao_inicio, edital.isencao_fim) == (date(2026, 10, 20), date(2026, 10, 27))

    assert [(e.evento, e.inicio, e.fim) for e in edital.eventos] == [
        ("Pedido de isenção da taxa", date(2026, 10, 20), date(2026, 10, 27)),
        ("Inscrições", date(2026, 10, 20), date(2026, 11, 18)),
        ("Prova objetiva", date(2027, 1, 24), date(2027, 1, 24)),
    ]
    assert edital.avisos == ()


def test_tjpb_2026_disciplinas_e_discursiva_por_cargo(fixture_texto):
    cargos = {c.especialidade: c for c in _edital(fixture_texto, "edital_tjpb26_1").cargos}

    assert cargos["Judiciária"].disciplinas == (
        "Língua Portuguesa",
        "Ética e Gestão no Serviço Público",
        "Noções de Informática e Proteção de Dados",  # nome quebrado em volta do número no PDF
        "Conhecimentos Específicos - Especialidade",
    )
    assert "Raciocínio Lógico e Matemático" in cargos["Contabilidade"].disciplinas
    ia = cargos["TI – Inteligência Artificial"]
    assert ia.disciplinas[:2] == ("Língua Portuguesa", "Raciocinio lógico-matemático")
    assert all(c.tem_redacao is True for c in cargos.values())


def test_retificacao_sem_secao_de_isencao_avisa(fixture_texto):
    edital = _edital(fixture_texto, "edital_tjpb26_0")
    assert edital.isencoes == ()
    assert "isenção citada, mas a seção não foi identificada: confira o edital" in edital.avisos


@pytest.mark.parametrize(
    ("edital", "tipos", "periodo"),
    [
        ("edital_dataprev26_0", {"CADUNICO", "DOADOR_MEDULA"}, (date(2026, 7, 6), date(2026, 7, 8))),
        (
            "edital_pcpr26_0",
            {"CADUNICO", "DOADOR_SANGUE", "DOADOR_MEDULA", "MESARIO_ELEITORAL", "OUTRA"},
            (date(2026, 7, 14), date(2026, 7, 16)),
        ),
        ("edital_pms2026_0", {"CADUNICO"}, (date(2026, 7, 9), date(2026, 7, 10))),
        (
            "edital_seducpa26_0",
            {"CADUNICO", "PESSOA_COM_DEFICIENCIA", "VITIMA_VIOLENCIA_DOMESTICA"},
            (date(2026, 8, 31), date(2026, 9, 3)),
        ),
        (
            "edital_sesto26_0",
            {
                "CADUNICO",
                "MESARIO_ELEITORAL",
                "PESSOA_COM_DEFICIENCIA",
                "JURADO",
                "DOADOR_SANGUE",
                "DOADOR_MEDULA",
                "VITIMA_VIOLENCIA_DOMESTICA",
                "OUTRA",
            },
            (date(2026, 8, 10), date(2026, 8, 14)),
        ),
    ],
)
def test_isencoes_de_outros_editais_fgv(fixture_texto, edital, tipos, periodo):
    resultado = extrair_isencoes(fixture_texto(f"fgv/{edital}.txt"))
    assert {i.codigo for i in resultado.tipos} == tipos
    assert (resultado.inicio, resultado.fim) == periodo


def test_cronograma_do_anexo_com_faixa_quebrada_e_sem_publicacoes(fixture_texto):
    edital = _edital(fixture_texto, "edital_pms2026_0")
    eventos = {e.evento: (e.inicio, e.fim) for e in edital.eventos}

    assert eventos["Inscrições"] == (date(2026, 7, 9), date(2026, 8, 7))  # "09/07/2026 a" + "07/08/2026"
    # O cronograma só traz a publicação do resultado dos pedidos; vale o período do item "DA ISENÇÃO".
    assert eventos["Pedido de isenção da taxa"] == (date(2026, 7, 9), date(2026, 7, 10))
    assert eventos["Prova objetiva e discursiva"] == (date(2026, 9, 27), date(2026, 9, 27))
    assert eventos["Gabarito preliminar"] == (date(2026, 9, 28), date(2026, 9, 28))
    assert edital.data_prova == date(2026, 9, 27)  # veio do cronograma
    assert "data da prova não encontrada" not in edital.avisos
    assert [e.inicio for e in edital.eventos] == sorted(e.inicio for e in edital.eventos)


def test_cronograma_completo_seducpa(fixture_texto):
    eventos = {e.evento: (e.inicio, e.fim) for e in _edital(fixture_texto, "edital_seducpa26_0").eventos}
    assert eventos["Inscrições"] == (date(2026, 8, 31), date(2026, 10, 7))
    assert eventos["Prova prática"] == (date(2027, 3, 31), date(2027, 4, 1))
    assert "Resultado final" in eventos


def test_discursiva_exclusiva_de_um_cargo(fixture_texto):
    cargos = {c.nome: c.tem_redacao for c in _edital(fixture_texto, "edital_pcpr26_0").cargos}
    assert cargos == {
        "Delegado de Polícia": True,
        "Agente de Polícia Judiciária": False,
        "Papiloscopista Policial": False,
    }


def test_discursiva_com_excecao_fica_incerta(fixture_texto):
    edital = _edital(fixture_texto, "edital_seducpa26_0")
    assert all(c.tem_redacao is None for c in edital.cargos)
    assert "prova discursiva/redação por cargo não identificada: confira o edital" in edital.avisos


def test_sem_discursiva_e_sem_redacao_oficial_do_conteudo(fixture_texto):
    # O conteúdo programático cita "Redação Oficial": não é prova de redação.
    assert all(c.tem_redacao is False for c in _edital(fixture_texto, "edital_dataprev26_0").cargos)


def test_um_quadro_vale_para_todos_os_cargos(fixture_texto):
    edital = _edital(fixture_texto, "edital_dataprev26_0")
    assert all("Língua Inglesa" in c.disciplinas for c in edital.cargos)


def test_quadros_por_nivel_sem_escolaridade_avisam():
    cargos = [CargoExtraido("Enfermeiro"), CargoExtraido("Técnico em Enfermagem")]
    quadros = [
        QuadroDisciplinas("para os cargos de Nível Médio:", ("Língua Portuguesa", "Informática")),
        QuadroDisciplinas("para os cargos de Nível Superior:", ("Língua Portuguesa", "Legislação do SUS")),
    ]
    resultado, faltou = atribuir_disciplinas(cargos, quadros)
    assert faltou and all(c.disciplinas == () for c in resultado)

    com_nivel = [CargoExtraido("Enfermeiro", escolaridade="SUPERIOR")]
    resultado, faltou = atribuir_disciplinas(com_nivel, quadros)
    assert not faltou and resultado[0].disciplinas == ("Língua Portuguesa", "Legislação do SUS")


def test_redacao_sem_cargos_nao_quebra():
    assert redacao_por_cargo("Prova Discursiva para todos os cargos", []) == ([], False)


@pytest.mark.parametrize(
    ("trecho", "esperado"),
    [
        ("do dia 20 de outubro e 16h do dia 18 de novembro de 2026", [date(2026, 10, 20), date(2026, 11, 18)]),
        ("de 20 de dezembro a 5 de janeiro de 2027", [date(2026, 12, 20), date(2027, 1, 5)]),
        ("entre 01/09/2026 e 03/09/2026", [date(2026, 9, 1), date(2026, 9, 3)]),
        ("31 de fevereiro de 2026 e 2 de março de 2026", [date(2026, 3, 2)]),
    ],
)
def test_datas_com_ano_inferido(trecho, esperado):
    assert datas_com_ano_inferido(trecho) == esperado


def test_texto_sem_isencao():
    assert extrair_isencoes("Edital sem nenhuma menção ao assunto.").tipos == ()

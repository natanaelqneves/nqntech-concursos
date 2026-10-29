from datetime import date
from decimal import Decimal

import pytest

from coletor.fontes.base import DadosEstruturados
from coletor.fontes.ibam import _periodo_inscricao, parse_listagem
from coletor.http_cliente import ErroHttp


@pytest.fixture(scope="module")
def sinais(request):
    from conftest import ler_fixture

    return {s.titulo: s for s in parse_listagem(ler_fixture("ibam/andamento.html"))}


def test_le_todos_os_concursos_da_pagina(sinais):
    assert len(sinais) == 43
    assert all(
        s.url.startswith("https://www.ibam-concursos.org.br/default.asp?status=2#cargos-") for s in sinais.values()
    )


def test_concurso_com_inscricoes_abertas_e_quadro_de_cargos(sinais):
    lages = sinais["Prefeitura de Lages/SC - Ed. 03/2026 - PS"].estruturado

    assert (lages.orgao, lages.uf, lages.municipio, lages.esfera) == ("Prefeitura de Lages", "SC", "Lages", "MUNICIPAL")
    assert (lages.numero_edital, lages.ano, lages.situacao) == ("03/2026", 2026, "INSCRICOES_ABERTAS")
    assert (lages.inscricao_inicio, lages.inscricao_fim, lages.data_prova) == (
        date(2026, 10, 21),
        date(2026, 11, 16),
        date(2026, 12, 6),
    )
    assert (lages.taxa_min, lages.taxa_max) == (Decimal("90.00"), Decimal("120.00"))
    assert len(lages.cargos) == 14
    tecnico = next(c for c in lages.cargos if c.nome == "Tecnico Enfermagem Socorrista")
    assert (tecnico.escolaridade, tecnico.vagas, tecnico.cadastro_reserva) == ("MEDIO", 4, False)
    motorista = next(c for c in lages.cargos if c.nome.startswith("Motorista"))
    assert (motorista.escolaridade, motorista.vagas, motorista.cadastro_reserva) == ("FUNDAMENTAL", None, True)


def test_documentos_viram_arquivos_pdf(sinais):
    arquivos = sinais["Prefeitura de Lages/SC - Ed. 03/2026 - PS"].payload["arquivos"]
    edital = next(a for a in arquivos if a["titulo"] == "Edital de Abertura")
    assert edital == {
        "titulo": "Edital de Abertura",
        "url": "https://www.ibam-concursos.org.br/documento/edit.2spslag.pdf",
        "data": None,
        "pdf": True,
    }


@pytest.mark.parametrize(
    ("titulo", "situacao"),
    [
        ("Município de Lages/SC - PS 02/2026", "ENCERRADO"),  # concurso suspenso
        ("Prefeitura de Caruaru/PE - Ed. 02/2024 - CP", "ENCERRADO"),  # resultado final
        ("Câmara de Concordia/SC - Ed. 01/2026 - CP", "EM_ANDAMENTO"),  # divulgação de gabarito
    ],
)
def test_situacao_pela_pagina(sinais, titulo, situacao):
    assert sinais[titulo].estruturado.situacao == situacao


def test_dados_estruturados_sobrevivem_ao_json(sinais):
    original = sinais["Prefeitura de Lages/SC - Ed. 03/2026 - PS"].estruturado
    assert DadosEstruturados.de_payload(original.para_payload()) == original


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Inscrições: das 06h do dia 21/10 às 18h do dia 16/11/2026.", (date(2026, 10, 21), date(2026, 11, 16))),
        ("Inscrições: das 06h do dia 02 às 18h do dia 30 de outubro de 2026.", (date(2026, 10, 2), date(2026, 10, 30))),
        ("Inscrições: das 8h do dia 20/12 às 18h do dia 15/01/2027.", (date(2026, 12, 20), date(2027, 1, 15))),
        ("Provas: 22 de novembro de 2026", (None, None)),
    ],
)
def test_periodo_de_inscricao(texto, esperado):
    assert _periodo_inscricao(texto) == esperado


def test_pagina_sem_concursos_falha_alto():
    with pytest.raises(ErroHttp, match="layout"):
        parse_listagem("<html><body>manutenção</body></html>")

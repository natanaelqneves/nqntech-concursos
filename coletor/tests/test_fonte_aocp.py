"""Fonte AOCP com a resposta real da API (amostra capturada em 04/11/2026 pelo workflow captura-sondagem)."""

import json
from datetime import date

import httpx

from coletor.fontes.aocp import FonteAOCP, orgao, parse_concurso
from coletor.http_cliente import ClienteHttp


def _lista(fixture_texto):
    return json.loads(fixture_texto("aocp/api_concursos.json"))


def test_so_inscricoes_abertas_viram_sinal(fixture_texto):
    lista = _lista(fixture_texto)
    sinais = [s for s in (parse_concurso(i) for i in lista) if s]
    assert {i["status"] for i in lista} >= {"SUBSCRIBE", "FINISHED", "IN_PROGRESS"}
    assert len(sinais) == sum(i["status"] == "SUBSCRIBE" for i in lista)
    assert all(s.estruturado.situacao == "INSCRICOES_ABERTAS" for s in sinais)


def test_concurso_da_pmpe(fixture_texto):
    pmpe = next(i for i in _lista(fixture_texto) if i["edital"] == "pmpe2026")
    sinal = parse_concurso(pmpe)
    assert sinal.url == "https://www.institutoaocp.org.br/concursos/714"
    assert sinal.estruturado.orgao == "Polícia Militar de Pernambuco"
    assert (sinal.estruturado.inscricao_inicio, sinal.estruturado.inscricao_fim) == (
        date(2026, 10, 5),
        date(2026, 11, 23),
    )
    assert sinal.payload["arquivos"] == []


def test_cargo_na_chamada_dos_processos_seletivos(fixture_texto):
    contador = parse_concurso(next(i for i in _lista(fixture_texto) if i["edital"] == "contad26"))
    assert [c.nome for c in contador.estruturado.cargos] == ["Contador"]
    assert contador.titulo == "Prefeitura Municipal de Curitiba – Contador"


def test_periodo_incoerente_da_api_vira_aviso(fixture_texto):
    saeb = parse_concurso(next(i for i in _lista(fixture_texto) if i["edital"] == "cbmpm26"))
    assert saeb.estruturado.inscricao_fim is None
    assert any("incoerente" in a for a in saeb.estruturado.avisos)


def test_item_sem_data_de_fim_e_id_textual(fixture_texto):
    item = {"id": "proseleta-3", "nome": "PMSC - POLÍCIA MILITAR DE SANTA CATARINA", "status": "SUBSCRIBE",
            "chamada": "Edital 002/CCP/2026", "dataInicioInscricao": "26/10/2026 09:00:00"}  # fmt: skip
    sinal = parse_concurso(item)
    assert sinal.estruturado.inscricao_fim is None and sinal.estruturado.orgao == "Polícia Militar de Santa Catarina"
    assert parse_concurso({**item, "id": "../x"}) is None


def test_orgao_sem_sigla():
    assert orgao("Irmandade Santa Casa de Misericórdia de Maringá") == (
        "Irmandade Santa Casa de Misericórdia de Maringá",
        None,
    )


def test_descobrir(fixture_texto):
    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/api/concursos":
            return httpx.Response(200, text=fixture_texto("aocp/api_concursos.json"),
                                  headers={"Content-Type": "application/json"})  # fmt: skip
        return httpx.Response(404)

    http = ClienteHttp(
        FonteAOCP.dominios, "t", intervalo_s=0, max_tentativas=1, transport=httpx.MockTransport(responder)
    )
    resultado = FonteAOCP().descobrir(http, pular=frozenset({"https://www.institutoaocp.org.br/concursos/714"}))
    urls = {s.url for s in resultado.sinais}
    assert "https://www.institutoaocp.org.br/concursos/715" in urls
    assert "https://www.institutoaocp.org.br/concursos/714" not in urls

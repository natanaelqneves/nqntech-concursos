"""Fonte Cebraspe com respostas reais da API (capturadas em 04/11/2026 pelo workflow captura-cebraspe)."""

import json
from datetime import date

import httpx

from coletor.fontes.cebraspe import (
    FonteCebraspe,
    cargos,
    edital_de_abertura,
    identificadores,
    link_arquivo,
    parse_evento,
)
from coletor.http_cliente import ClienteHttp
from coletor.pipeline.vinculacao import classificar_tipo_documento


def _evento(fixture_texto, ident):
    return json.loads(fixture_texto(f"cebraspe/evento_{ident}.json"))


def test_lista_por_fase(fixture_texto):
    abertas = json.loads(fixture_texto("cebraspe/fase_inscricoes-abertas.json"))
    assert identificadores(abertas) == ["CD_26_ANALISTA", "CGU_26_AFFC", "PC_PE_26"]
    assert identificadores([{"eventos": [{"eventoURL": "../x"}, {"eventoURL": "OK_1"}]}]) == ["OK_1"]
    assert identificadores({"inesperado": True}) == []


def test_so_o_edital_de_abertura_consolidado_vai_para_download(fixture_texto):
    evento = _evento(fixture_texto, "CD_26_ANALISTA")
    abertura = edital_de_abertura(evento["arquivosEdital"])
    assert abertura["descricaoArquivo"] == "Edital nº 1 - Abertura – Atualizado conforme retificações"
    url = link_arquivo("CD_26_ANALISTA", abertura)
    assert url.startswith("https://cdn.cebraspe.org.br/concursos/CD_26_ANALISTA/arquivos/") and url.endswith(".pdf")
    assert link_arquivo("X", {"nomeArquivo": "abc.pdf", "isGuid": True}) == "https://cdn.cebraspe.org.br/abc.pdf"


def test_evento_aberto_vira_sinal_com_periodo_e_cargos(fixture_texto):
    sinal = parse_evento(_evento(fixture_texto, "CD_26_ANALISTA"), "inscricoes-abertas")
    assert sinal.url == "https://www.cebraspe.org.br/concursos/CD_26_ANALISTA"
    assert sinal.estruturado.situacao == "INSCRICOES_ABERTAS"
    assert (sinal.estruturado.inscricao_inicio, sinal.estruturado.inscricao_fim) == (
        date(2026, 10, 15),
        date(2026, 11, 17),
    )
    assert len(sinal.estruturado.cargos) == 11
    primeiro = sinal.estruturado.cargos[0]
    assert primeiro.nome == "Analista Legislativo"
    assert "Comunicação Social" in primeiro.especialidade
    [arquivo] = sinal.payload["arquivos"]
    assert arquivo["tipo"] == "EDITAL" and arquivo["pdf"] and arquivo["data"] == "2026-10-02"
    assert sinal.payload["link_inscricao"] == "https://areadocandidato.cebraspe.org.br/"


def test_suspenso_nao_e_oportunidade(fixture_texto):
    assert parse_evento(_evento(fixture_texto, "TJ_CE_25_NOTARIOS"), "novos") is None


def test_itens_que_nao_sao_cargos_ficam_de_fora():
    assert cargos(
        {"eventoCargos": [{"area": "Provimento"}, {"area": "CARGO 01: AUDITOR FEDERAL DE FINANÇAS E CONTROLE"}]}
    )[0].nome.startswith("Auditor")
    assert len(cargos({"eventoCargos": [{"area": "Provimento"}]})) == 0


def test_titulos_da_cebraspe_confundem_o_classificador_generico():
    # Por isso a fonte informa o tipo: o genérico chamaria uma retificação de "EDITAL".
    assert classificar_tipo_documento("Edital nº 6 - Retificação dos subitens 2.5.4 e 11.8") == "EDITAL"


def test_descobrir_pede_so_novos_e_abertos(fixture_texto):
    pedidos: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request.url.path)
        caminho = request.url.path
        if caminho == "/robots.txt":
            return httpx.Response(404)
        if caminho.endswith("/fase/inscricoes-abertas"):
            return httpx.Response(200, text=fixture_texto("cebraspe/fase_inscricoes-abertas.json"))
        if caminho.endswith("/fase/novos"):
            return httpx.Response(200, text=fixture_texto("cebraspe/fase_novos.json"))
        ident = caminho.rsplit("/", 1)[-1]
        if ident in {"CD_26_ANALISTA", "CGU_26_AFFC", "TJ_CE_25_NOTARIOS"}:
            return httpx.Response(200, text=fixture_texto(f"cebraspe/evento_{ident}.json"))
        return httpx.Response(500)

    http = ClienteHttp(FonteCebraspe.dominios, "t", intervalo_s=0, max_tentativas=1,
                       transport=httpx.MockTransport(responder))  # fmt: skip
    resultado = FonteCebraspe().descobrir(http, pular=frozenset({"https://www.cebraspe.org.br/concursos/CGU_26_AFFC"}))

    assert [s.url.rsplit("/", 1)[-1] for s in resultado.sinais] == ["CD_26_ANALISTA"]  # TJ CE suspenso; CGU pulado
    assert len(resultado.falhas) == 1  # PC PE respondeu 500
    assert not any("encerrado" in p or "em-andamento" in p for p in pedidos)

"""Fonte DOE-SP com respostas reais da API (capturadas em 04/11/2026 pelo workflow captura-diarios)."""

import json
from datetime import date
from urllib.parse import parse_qs

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from coletor.fontes.doe_sp import FonteDOESP, html_para_texto, interessa, parse_publicacao
from coletor.http_cliente import ClienteHttp


def _json(fixture_texto, nome):
    return json.loads(fixture_texto(f"doe_sp/{nome}.json"))


def test_listagem_separa_aberturas_de_contratos_e_homologacoes(fixture_texto):
    itens = _json(fixture_texto, "sp_concurso")["items"]
    titulos = {i["title"][:40] for i in itens if interessa(i)}
    assert any("Nº 145/2026STGP" in t for t in titulos)
    assert not any("TERMOS DE CONTRATOS" in t or "HOMOLOGAÇÃO" in t or "RETIFICAÇÃO" in t for t in titulos)


def test_publicacao_vira_sinal_com_texto(fixture_texto):
    sinal = parse_publicacao(_json(fixture_texto, "sp_api_slug"))
    assert sinal.titulo == "Universidade Estadual Paulista"
    assert sinal.url.startswith("https://doe.sp.gov.br/executivo/universidade-estadual-paulista/")
    [arquivo] = sinal.payload["arquivos"]
    assert arquivo["tipo"] == "EDITAL" and "Acham-se abertas" in arquivo["texto"] and "&ordm;" not in arquivo["texto"]
    assert sinal.data_publicacao == date(2026, 10, 28)


def test_publicacao_sem_abertura_nao_entra():
    assert (
        parse_publicacao({"slug": "executivo/x/aviso-de-licitacao-0001", "content": "<p>Aviso de licitação</p>"})
        is None
    )
    assert html_para_texto("<p>A&ordm;</p><br>B") == "Aº\nB"


def test_descobrir_pagina_a_busca_e_le_cada_edital(fixture_texto):
    pedidos = []

    def responder(request: httpx.Request) -> httpx.Response:
        caminho = request.url.path
        pedidos.append(caminho)
        if caminho == "/robots.txt":
            return httpx.Response(404)
        if caminho.endswith("/advanced-search/publications"):
            q = parse_qs(request.url.query.decode())
            assert q["FromDate"] == ["2026-10-28"] and q["ToDate"] == ["2026-11-04"]
            return httpx.Response(200, text=fixture_texto("doe_sp/sp_concurso.json"))
        return httpx.Response(200, text=fixture_texto("doe_sp/sp_api_slug.json"))

    http = ClienteHttp(FonteDOESP.dominios, "t", intervalo_s=0, max_tentativas=1,
                       transport=httpx.MockTransport(responder))  # fmt: skip
    resultado = FonteDOESP(dias=7, hoje=lambda: date(2026, 11, 4)).descobrir(http)
    assert resultado.sinais and not resultado.falhas
    # 3 termos × até 5 páginas (a resposta simulada diz que há 13); a mesma publicação é lida uma vez só
    assert sum(p.endswith("/advanced-search/publications") for p in pedidos) == 15
    assert len({s.url for s in resultado.sinais}) == len(resultado.sinais)


@pytest.mark.db
def test_texto_do_diario_vai_direto_ao_documento(parametros_coletor, conn_admin, fixture_texto):
    from coletor.db import Repositorio
    from coletor.pipeline.vinculacao import executar_vinculacao

    sinal = parse_publicacao(_json(fixture_texto, "sp_api_slug"))
    conn_admin.execute("DELETE FROM concursos.sinal_descoberta WHERE url = %s", (sinal.url,))
    conn_admin.execute("DELETE FROM concursos.concurso WHERE link_oficial = %s", (sinal.url,))
    conn = psycopg.connect(**parametros_coletor, row_factory=dict_row)
    conn.execute("SET search_path = concursos")
    repo = Repositorio(conn)
    try:
        fonte = conn.execute("SELECT id FROM fonte WHERE nome = 'doe-sp'").fetchone()["id"]
        with repo.transacao():
            repo.gravar_sinal(fonte, sinal)
        executar_vinculacao(repo)
        doc = conn_admin.execute(
            """SELECT d.status_extracao, length(d.texto_extraido) > 500, c.banca_id IS NULL
               FROM concursos.documento d JOIN concursos.concurso c ON c.id = d.concurso_id
               WHERE c.link_oficial = %s""",
            (sinal.url,),
        ).fetchone()
        assert doc == ("OK", True, True)
        payload = conn_admin.execute(
            "SELECT payload FROM concursos.sinal_descoberta WHERE url = %s", (sinal.url,)
        ).fetchone()[0]
        assert "texto" not in payload["arquivos"][0]
    finally:
        conn.close()
        conn_admin.execute("DELETE FROM concursos.sinal_descoberta WHERE url = %s", (sinal.url,))
        conn_admin.execute("DELETE FROM concursos.concurso WHERE link_oficial = %s", (sinal.url,))

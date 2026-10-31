"""Testes unitários para a fonte Consulpam."""

from __future__ import annotations

import httpx

from coletor.fontes.consulpam import FonteConsulpam, parse_concurso, parse_listagem
from coletor.http_cliente import ClienteHttp

URL_LISTAGEM = "https://consulpam.com.br/index.php?menu=concursos"
URL_DETALHE = "https://consulpam.com.br/index.php?menu=concursos&acao=ver&id=888"


def test_listagem_consulpam(fixture_texto):
    pagina = parse_listagem(fixture_texto("consulpam/listagem.html"))

    assert len(pagina.itens) > 0
    urls = [i.url for i in pagina.itens]
    assert URL_DETALHE in urls


def test_pagina_do_concurso_consulpam(fixture_texto):
    html_exemplo = """
    <html>
        <body>
            <h1>PREFEITURA MUNICIPAL DE SÃO JOÃO DO PIAUÍ-PI</h1>
            <div id="centro">
                <p>Edital 003/2026 de Processo Seletivo.</p>
                <a href="arquivos/edital_003.pdf">Baixar Edital PDF</a>
            </div>
        </body>
    </html>
    """
    dados = parse_concurso(html_exemplo, URL_DETALHE, encerrado=False, situacao_site="Inscrições Abertas")

    assert dados["titulo"] == "PREFEITURA MUNICIPAL DE SÃO JOÃO DO PIAUÍ-PI"
    assert dados["situacao_site"] == "Inscrições Abertas"
    assert dados["encerrado"] is False
    assert len(dados["arquivos"]) == 1
    assert dados["arquivos"][0]["titulo"] == "Baixar Edital PDF"
    assert "arquivos/edital_003.pdf" in dados["arquivos"][0]["url"]


def test_descobrir_consulpam_mock(fixture_texto):
    paginas = {
        "/index.php?menu=concursos": fixture_texto("consulpam/listagem.html"),
    }

    def responder(request: httpx.Request) -> httpx.Response:
        path = request.url.path + (f"?{request.url.query.decode()}" if request.url.query else "")
        if path in paginas:
            return httpx.Response(200, text=paginas[path], headers={"Content-Type": "text/html; charset=utf-8"})
        return httpx.Response(
            200,
            text="<html><body><h1>Detalhe Concurso</h1><a href='edital.pdf'>Edital</a></body></html>",
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    http = ClienteHttp(
        frozenset({"consulpam.com.br", "selecao.net.br"}),
        "teste",
        intervalo_s=0,
        transport=httpx.MockTransport(responder),
        dormir=lambda _: None,
    )
    resultado = FonteConsulpam().descobrir(http)

    assert len(resultado.sinais) > 0
    assert not resultado.falhas

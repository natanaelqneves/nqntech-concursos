import httpx
import pytest

from coletor.fontes.cesgranrio import FonteCESGRANRIO, parse_concurso, parse_listagem
from coletor.http_cliente import ClienteHttp, ErroHttp

URL_EXEMPLO = "https://www.cesgranrio.org.br/concurso/concurso-eppgg-bahia-2026/"


def test_listagem_cesgranrio_extrai_itens_e_situacao(fixture_texto):
    html_listagem = """
    <div class="isotope-wrapper">
        <div class="tmb grid-cat-27">
            <h3 class="t-entry-title">
                <a href="/concurso/concurso-eppgg-bahia-2026/">Concurso EPPGG – Bahia 2026</a>
            </h3>
        </div>
        <div class="tmb grid-cat-25">
            <h3 class="t-entry-title">
                <a href="/concurso/policia-civil-amapa-2026/">Concurso Polícia Civil do Amapá 2026</a>
            </h3>
        </div>
    </div>
    <ul class="pagination">
        <li><a class="page-numbers" href="https://www.cesgranrio.org.br/concursos/page/2">2</a></li>
    </ul>
    """
    itens, ultima_pagina = parse_listagem(html_listagem)

    assert len(itens) == 2
    assert ultima_pagina == 2
    assert itens[0].titulo == "Concurso EPPGG – Bahia 2026"
    assert itens[0].situacao == "INSCRICOES_ABERTAS"
    assert itens[1].situacao == "EM_ANDAMENTO"


def test_listagem_sem_cards_falha_alto():
    with pytest.raises(ErroHttp, match="Listagem da Cesgranrio sem cards"):
        parse_listagem("<html><body><p>manutenção</p></body></html>")


def test_pagina_do_concurso_cesgranrio(fixture_texto):
    html_detalhe = """
    <html>
        <body>
            <h1>Concurso EPPGG – Bahia 2026</h1>
            <div class="post-content">O Governo da Bahia publicou o edital...</div>
            <a href="https://concursos.cesgranrio.org.br/portal/login">Portal do Candidato</a>
            <a href="/pdf/edital-eppgg.pdf">Edital de Abertura</a>
        </body>
    </html>
    """
    dados = parse_concurso(html_detalhe, URL_EXEMPLO, "INSCRICOES_ABERTAS")

    assert dados["titulo"] == "Concurso EPPGG – Bahia 2026"
    assert dados["situacao_site"] == "INSCRICOES_ABERTAS"
    assert "Governo da Bahia" in dados["descricao"]
    assert dados["link_inscricao"] == "https://concursos.cesgranrio.org.br/portal/login"
    assert len(dados["arquivos"]) == 1
    assert dados["arquivos"][0]["titulo"] == "Edital de Abertura"
    assert dados["arquivos"][0]["url"] == "https://www.cesgranrio.org.br/pdf/edital-eppgg.pdf"
    assert dados["arquivos"][0]["pdf"] is True


def test_descobrir_percorre_paginas_cesgranrio(fixture_texto):
    paginas = {
        "/concursos/": (
            '<div class="tmb grid-cat-25"><h3 class="t-entry-title">'
            '<a href="/concurso/c1/">C1</a></h3></div>'
            '<ul class="pagination"><li><a href="/concursos/page/2">2</a></li></ul>'
        ),
            "/concursos/page/2/": (
                '<div class="tmb grid-cat-25"><h3 class="t-entry-title">'
                '<a href="/concurso/c2/">C2</a></h3></div>'
        ),

        "/concurso/c1/": "<h1>C1</h1>",
        "/concurso/c2/": "<h1>C2</h1>",
    }

    def responder(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in paginas:
            return httpx.Response(200, text=paginas[path], headers={"Content-Type": "text/html; charset=utf-8"})
        return httpx.Response(404)

    http = ClienteHttp(
        frozenset({"cesgranrio.org.br", "www.cesgranrio.org.br"}),
        "teste",
        intervalo_s=0,
        transport=httpx.MockTransport(responder),
        dormir=lambda _: None,
    )
    resultado = FonteCESGRANRIO(max_paginas=2).descobrir(http)
    urls = {s.url for s in resultado.sinais}
    assert "https://www.cesgranrio.org.br/concurso/c1/" in urls
    assert "https://www.cesgranrio.org.br/concurso/c2/" in urls
    assert len(resultado.sinais) == 2

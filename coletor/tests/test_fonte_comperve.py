"""Fonte COMPERVE com páginas reais (capturadas em 04/11/2026 pelo workflow captura-tls)."""

import ssl
from datetime import date

import httpx

from coletor.fontes.comperve import (
    FonteComperve,
    edital_de_abertura,
    itens_da_listagem,
    montar_sinal,
    orgao,
    periodo_inscricao,
)
from coletor.http_cliente import ClienteHttp, contexto_tls

DOCS = "https://www.comperve.ufrn.br/conteudo/concursos/mossoro_202601/documentos.php"


def _f(fixture_texto, nome):
    return fixture_texto(f"comperve/{nome}.html")


def test_listagem_so_novos_e_abertos(fixture_texto):
    assert itens_da_listagem(_f(fixture_texto, "concursos")) == [
        ("cref_202601", "CONCURSO PÚBLICO PARA O CONSELHO REGIONAL DE EDUCAÇÃO FÍSICA 16ª REGIÃO/RN - 01/2026",
         "PREVISTO"),
        ("mossoro_202601", "CONCURSO DA CÂMARA MUNICIPAL DE MOSSORÓ - 01/2026", "INSCRICOES_ABERTAS"),
    ]  # fmt: skip


def test_itens_comentados_sao_ignorados():
    html = """<div class="categoria">NOVOS</div><!-- <a href="concursos/velho_2019/informacoes.php"><li>X</li></a> -->
    <a class="conteudo_V10" href="concursos/novo_202602/informacoes.php"><li>Y</li></a>"""
    assert [s for s, *_ in itens_da_listagem(html)] == ["novo_202602"]


def test_edital_consolidado_e_nao_retificacao(fixture_texto):
    arquivo = edital_de_abertura(_f(fixture_texto, "mossoro_202601_documentos"), DOCS)
    assert arquivo["titulo"] == "Edital Nº 01/2026 (retificado em 29 de outubro de 2026)"
    assert arquivo["url"].startswith("https://www.comperve.ufrn.br/conteudo/concursos/mossoro_202601/documentos/")
    assert arquivo["url"].endswith(".pdf") and arquivo["data"] == "2026-10-29" and arquivo["tipo"] == "EDITAL"


def test_edital_original_quando_nao_ha_consolidado(fixture_texto):
    arquivo = edital_de_abertura(_f(fixture_texto, "cref_202601_documentos"), DOCS.replace("mossoro", "cref"))
    assert arquivo["titulo"].startswith("Edital Nº 01/2026 (divulgado em 26")
    assert edital_de_abertura("<p>nada</p>", DOCS) is None


def test_orgao_e_periodo(fixture_texto):
    assert orgao(_f(fixture_texto, "mossoro_202601_informacoes")) == "Câmara Municipal de Mossoró"
    assert periodo_inscricao(_f(fixture_texto, "mossoro_202601_inscricoes")) == (date(2026, 10, 13), date(2026, 11, 12))
    assert periodo_inscricao("<p>em breve</p>") == (None, None)


def test_sinal_completo(fixture_texto):
    sinal = montar_sinal(
        "mossoro_202601",
        "CONCURSO DA CÂMARA MUNICIPAL DE MOSSORÓ - 01/2026",
        "INSCRICOES_ABERTAS",
        _f(fixture_texto, "mossoro_202601_informacoes"),
        _f(fixture_texto, "mossoro_202601_documentos"),
        _f(fixture_texto, "mossoro_202601_inscricoes"),
    )
    assert sinal.estruturado.numero_edital == "01/2026"
    assert sinal.estruturado.inscricao_fim == date(2026, 11, 12)
    assert len(sinal.payload["arquivos"]) == 1 and not sinal.estruturado.avisos


def test_descobrir_tolera_paginas_secundarias_ausentes(fixture_texto):
    def responder(request: httpx.Request) -> httpx.Response:
        caminho = request.url.path
        if caminho == "/robots.txt":
            return httpx.Response(404)
        if caminho == "/conteudo/concursos.php":
            return httpx.Response(200, text=_f(fixture_texto, "concursos"))
        slug, pagina = caminho.split("/")[-2:]
        nome = f"{slug}_{pagina.removesuffix('.php')}"
        if nome == "cref_202601_inscricoes":
            return httpx.Response(404)
        return httpx.Response(200, text=_f(fixture_texto, nome))

    http = ClienteHttp(FonteComperve.dominios, "t", intervalo_s=0, max_tentativas=1,
                       transport=httpx.MockTransport(responder))  # fmt: skip
    resultado = FonteComperve().descobrir(http)
    cref, mossoro = resultado.sinais
    assert cref.estruturado.situacao == "PREVISTO" and cref.estruturado.inscricao_inicio is None
    assert cref.payload["arquivos"] and mossoro.estruturado.orgao == "Câmara Municipal de Mossoró"
    assert not resultado.falhas


def test_contexto_tls_verifica_e_inclui_intermediario():
    contexto = contexto_tls()
    assert contexto.verify_mode == ssl.CERT_REQUIRED and contexto.check_hostname
    assert not contexto.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN
    assert any("GlobalSign RSA OV SSL CA 2018" in str(c.get("subject")) for c in contexto.get_ca_certs())

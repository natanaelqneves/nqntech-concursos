"""Testes do site gerado num navegador de verdade (Chromium), em tamanhos de celular, tablet e computador.

Rodam na CI contra o site gerado a partir dos seeds e servido localmente (SITE_TESTE_URL). Nada sai para a
internet: pedidos a outros domínios (anúncios) são bloqueados.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, ConsoleMessage, Page, Playwright, Route, sync_playwright

BASE = os.environ.get("SITE_TESTE_URL", "http://127.0.0.1:8099").rstrip("/")

TELAS = {
    "celular-pequeno": (320, 640),
    "celular": (390, 844),
    "tablet": (768, 1024),
    "tablet-deitado": (1024, 768),
    "notebook": (1280, 800),
    "monitor": (1920, 1080),
}

PAGINAS_FIXAS = ["/", "/inscricoes-abertas/", "/isencao-em-prazo/", "/isencoes/", "/brasil/", "/sobre/",
                 "/privacidade/", "/404.html"]

MENU = ["Início", "Inscrições abertas", "Isenção em prazo", "Tipos de isenção", "Por região", "Sobre"]


@pytest.fixture(scope="session")
def playwright() -> Iterator[Playwright]:
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def navegador(playwright: Playwright) -> Iterator[Browser]:
    # PW_CANAL=chrome usa o Chrome instalado (útil fora da CI, onde o Chromium do Playwright pode não existir).
    canal = os.environ.get("PW_CANAL")
    browser = playwright.chromium.launch(channel=canal) if canal else playwright.chromium.launch()
    yield browser
    browser.close()


def _so_o_site(route: Route) -> None:
    if urlparse(route.request.url).netloc == urlparse(BASE).netloc:
        route.continue_()
    else:
        route.abort()


@pytest.fixture(params=list(TELAS), ids=list(TELAS))
def pagina(request: pytest.FixtureRequest, navegador: Browser) -> Iterator[Page]:
    largura, altura = TELAS[request.param]
    contexto = navegador.new_context(viewport={"width": largura, "height": altura}, locale="pt-BR",
                                     has_touch=largura < 1000, is_mobile=largura < 800)
    contexto.route("**/*", _so_o_site)
    page = contexto.new_page()
    erros: list[str] = []

    def no_console(msg: ConsoleMessage) -> None:
        # Pedidos bloqueados a outros domínios geram erro de rede no console: só interessam erros do próprio site.
        if msg.type == "error" and urlparse(BASE).netloc in (msg.location.get("url") or "") \
                and "ERR_FAILED" not in msg.text:
            erros.append(msg.text)

    page.on("console", no_console)
    page.on("pageerror", lambda e: erros.append(str(e)))
    yield page
    contexto.close()
    assert not erros, f"erros de JavaScript: {erros}"


def _abrir(page: Page, caminho: str) -> None:
    resposta = page.goto(BASE + caminho, wait_until="networkidle")
    assert resposta is not None and resposta.status in (200, 404), f"{caminho}: {resposta and resposta.status}"


def _primeiro_link(page: Page, prefixo: str) -> str:
    # Exclui o próprio prefixo (o menu tem /isencoes/, por exemplo): queremos uma página filha.
    href = page.locator(f"main a[href^='{prefixo}']:not([href='{prefixo}'])").first.get_attribute("href")
    assert href, f"nenhum link {prefixo} na página"
    return href


def _paginas(page: Page) -> list[str]:
    _abrir(page, "/")
    concurso = _primeiro_link(page, "/concurso/")
    _abrir(page, "/brasil/")
    estado = _primeiro_link(page, "/estado/")
    _abrir(page, "/isencoes/")
    isencao = _primeiro_link(page, "/isencoes/")
    return [*PAGINAS_FIXAS, concurso, estado, isencao]


def test_nenhuma_pagina_rola_para_os_lados_e_o_estilo_carrega(pagina: Page) -> None:
    for caminho in _paginas(pagina):
        _abrir(pagina, caminho)
        estado = pagina.evaluate("""() => ({
            sobra: document.documentElement.scrollWidth - window.innerWidth,
            fonte: getComputedStyle(document.body).fontFamily,
            marcadores: getComputedStyle(document.querySelector('.topo__menu')).listStyleType,
            css: [...document.styleSheets].some(s => (s.href || '').includes('/assets/site.css?v=')),
        })""")
        assert estado["css"], f"{caminho}: site.css versionado não carregou"
        assert "Atkinson" in estado["fonte"], f"{caminho}: fonte do site não aplicada"
        assert estado["marcadores"] == "none", f"{caminho}: menu sem estilo"
        assert estado["sobra"] <= 0, f"{caminho}: rolagem horizontal de {estado['sobra']}px"


def test_menu_completo_visivel_com_alvos_de_toque(pagina: Page) -> None:
    _abrir(pagina, "/")
    largura = pagina.viewport_size["width"]
    for nome in MENU:
        link = pagina.locator("#menu-principal").get_by_role("link", name=nome, exact=True)
        assert link.is_visible(), f"menu sem '{nome}'"
        caixa = link.bounding_box()
        assert caixa is not None
        assert caixa["x"] >= 0 and caixa["x"] + caixa["width"] <= largura, f"'{nome}' sai da tela"
        assert caixa["height"] >= 44, f"'{nome}' com alvo de {caixa['height']}px (mínimo 44)"
    atual = pagina.locator("#menu-principal a[aria-current='page']")
    assert atual.count() == 1 and atual.inner_text() == "Início"


def test_menu_leva_as_paginas(pagina: Page) -> None:
    _abrir(pagina, "/")
    for nome in MENU[1:]:
        pagina.locator("#menu-principal").get_by_role("link", name=nome, exact=True).click()
        pagina.wait_for_load_state("networkidle")
        assert pagina.locator("h1").first.is_visible(), f"'{nome}' abriu página sem título"
        assert pagina.locator("#menu-principal a[aria-current='page']").inner_text() == nome


def test_tema_escuro_alterna_e_fica_lembrado(pagina: Page) -> None:
    _abrir(pagina, "/")
    html = pagina.locator("html")
    fundo_claro = pagina.evaluate("getComputedStyle(document.body).backgroundColor")
    botao = pagina.locator("#alternar-tema")
    assert botao.get_attribute("aria-pressed") == "false"
    caixa = botao.bounding_box()
    assert caixa is not None and caixa["width"] >= 44 and caixa["height"] >= 44

    botao.click()
    assert html.get_attribute("data-bs-theme") == "dark"
    assert botao.get_attribute("aria-pressed") == "true"
    assert pagina.evaluate("getComputedStyle(document.body).backgroundColor") != fundo_claro

    pagina.reload(wait_until="networkidle")
    assert html.get_attribute("data-bs-theme") == "dark", "escolha do tema não foi lembrada"
    pagina.locator("#alternar-tema").click()
    assert html.get_attribute("data-bs-theme") is None
    assert pagina.evaluate("getComputedStyle(document.body).backgroundColor") == fundo_claro


def test_grade_de_cartoes_se_adapta_a_largura(pagina: Page) -> None:
    _abrir(pagina, "/inscricoes-abertas/")
    cartoes = pagina.locator("article.cartao")
    if cartoes.count() < 3:
        pytest.skip("seeds com menos de 3 concursos abertos")
    lefts = {round(cartoes.nth(i).bounding_box()["x"]) for i in range(3)}
    largura = pagina.viewport_size["width"]
    esperado = 1 if largura < 768 else 2 if largura < 1200 else 3
    assert len(lefts) == esperado, f"{largura}px: {len(lefts)} colunas, esperado {esperado}"
    canhoto = cartoes.first.locator(".cartao__canhoto")
    assert canhoto.is_visible() and re.search(r"\d|a definir", canhoto.inner_text())


def test_cartoes_do_mesmo_tamanho(pagina: Page) -> None:
    _abrir(pagina, "/inscricoes-abertas/")
    alturas = pagina.evaluate(
        "[...document.querySelectorAll('.grade-cartoes article.cartao')].map(c => Math.round(c.getBoundingClientRect().height))")
    if len(alturas) < 2:
        pytest.skip("seeds com menos de 2 concursos abertos")
    assert max(alturas) - min(alturas) <= 1, f"cartões com alturas diferentes: {alturas}"
    # Os dados ficam no pé do cartão: a distância do fim dos dados ao fim do cartão é igual em todos.
    pes = pagina.evaluate("""[...document.querySelectorAll('.grade-cartoes article.cartao')].map(c =>
        Math.round(c.getBoundingClientRect().bottom - c.querySelector('.cartao__dados').getBoundingClientRect().bottom))""")
    assert max(pes) - min(pes) <= 1, f"dados fora do pé do cartão: {pes}"


def test_pronto_para_o_adsense(pagina: Page) -> None:
    _abrir(pagina, "/")
    conta = pagina.locator("meta[name='google-adsense-account']").get_attribute("content")
    assert conta and conta.startswith("ca-pub-")
    assert pagina.locator("script[src*='adsbygoogle.js']").count() == 1
    ads = pagina.request.get(BASE + "/ads.txt")
    assert ads.ok and f"google.com, {conta.removeprefix('ca-')}, DIRECT" in ads.text()
    _abrir(pagina, "/privacidade/")
    assert "AdSense" in pagina.locator("main").inner_text()


def test_cartao_inteiro_abre_o_concurso(pagina: Page) -> None:
    _abrir(pagina, "/")
    cartao = pagina.locator("article.cartao").first
    destino = cartao.locator("a.stretched-link").get_attribute("href")
    cartao.scroll_into_view_if_needed()
    caixa = cartao.bounding_box()
    assert caixa is not None
    # Clique perto do canto de baixo, na área de dados (longe do título): o link esticado cobre o cartão todo.
    with pagina.expect_navigation(wait_until="networkidle"):
        pagina.mouse.click(caixa["x"] + caixa["width"] - 12, caixa["y"] + caixa["height"] - 12)
    assert pagina.url.endswith(destino)


def test_pagina_do_concurso_ficha_e_tabela(pagina: Page) -> None:
    _abrir(pagina, "/")
    _abrir(pagina, _primeiro_link(pagina, "/concurso/"))
    ficha = pagina.locator(".ficha").bounding_box()
    resumo = pagina.locator("#titulo-resumo").bounding_box()
    assert ficha is not None and resumo is not None
    if pagina.viewport_size["width"] >= 992:
        assert ficha["x"] > resumo["x"], "no computador a ficha fica à direita do resumo"
    else:
        assert ficha["y"] < resumo["y"], "no celular a ficha vem antes do resumo"
    tabela = pagina.locator(".tabela-rolagem")
    if tabela.count():
        # A tabela pode rolar dentro da própria caixa, nunca a página.
        caixa = tabela.bounding_box()
        assert caixa is not None and caixa["x"] + caixa["width"] <= pagina.viewport_size["width"] + 1


def test_prazos_calculados_no_navegador(pagina: Page) -> None:
    _abrir(pagina, "/isencoes/")
    prazos = pagina.locator("[data-prazo]")
    for i in range(prazos.count()):
        assert re.match(r"(isenção|prazo de isenção)", prazos.nth(i).inner_text()), prazos.nth(i).inner_text()


def test_link_pular_para_o_conteudo(pagina: Page) -> None:
    _abrir(pagina, "/")
    pagina.keyboard.press("Tab")
    focado = pagina.evaluate("document.activeElement.textContent.trim()")
    assert focado == "Pular para o conteúdo"
    assert pagina.locator(".pular").is_visible()

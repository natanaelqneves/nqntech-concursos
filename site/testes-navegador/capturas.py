"""Tira capturas de tela das páginas principais do site de teste em celular, tablet e computador.

Uso na CI (artefato "capturas-site"), para revisar o visual sem publicar: python capturas.py PASTA_SAIDA
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Route, sync_playwright

BASE = os.environ.get("SITE_TESTE_URL", "http://127.0.0.1:8099").rstrip("/")
TELAS = {"celular": (390, 844), "tablet": (768, 1024), "computador": (1366, 900)}


def _so_o_site(route: Route) -> None:
    if urlparse(route.request.url).netloc == urlparse(BASE).netloc:
        route.continue_()
    else:
        route.abort()


def main(saida: Path) -> None:
    saida.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        for nome, (largura, altura) in TELAS.items():
            for tema in ("claro", "escuro"):
                contexto = navegador.new_context(viewport={"width": largura, "height": altura},
                                                 color_scheme="dark" if tema == "escuro" else "light")
                contexto.route("**/*", _so_o_site)
                if tema == "escuro":
                    contexto.add_init_script("try { localStorage.setItem('tema', 'dark') } catch (e) {}")
                pagina = contexto.new_page()
                pagina.goto(BASE + "/", wait_until="networkidle")
                concurso = pagina.locator("main a[href^='/concurso/']").first.get_attribute("href")
                for rotulo, caminho in (("inicio", "/"), ("concurso", concurso), ("isencoes", "/isencoes/"),
                                        ("brasil", "/brasil/")):
                    if tema == "escuro" and rotulo != "inicio":
                        continue
                    pagina.goto(BASE + caminho, wait_until="networkidle")
                    pagina.screenshot(path=saida / f"{rotulo}-{nome}-{tema}.png", full_page=True)
                contexto.close()
        navegador.close()


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "capturas"))

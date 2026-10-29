"""Captura páginas reais da FGV para servirem de fixtures dos testes (roda no GitHub Actions).

Respeita robots.txt e espera 3 s entre requisições. Salva HTML, robots.txt, um relatório e o texto
extraído do edital de cada concurso-alvo (os PDFs não são versionados). Fixtures que já existem não são
sobrescritas: os testes dependem do conteúdo capturado da primeira vez.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup

BASE = "https://conhecimento.fgv.br"
LISTAGEM = f"{BASE}/concursos"
UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
DESTINO = Path("coletor/tests/fixtures/fgv")
# Concursos de áreas diferentes (fase 2): policial, saúde, educação, TI, municipal e o CNU (só a página).
ALVOS = {
    "/concursos/pcpr26": True,
    "/concursos/sesto26": True,
    "/concursos/seducpa26": True,
    "/concursos/dataprev26": True,
    "/concursos/pms2026": True,
    "/cpnu2": False,
}
PAGINAS_LISTAGEM = (0, 1, 2)
INTERVALO_S = 3.0

sessao = requests.Session()
sessao.headers["User-Agent"] = UA
relatorio: dict = {"requisicoes": []}
ultimo = 0.0


def obter(
    url: str, robots: urllib.robotparser.RobotFileParser | None
) -> requests.Response | None:
    global ultimo
    if robots is not None and not robots.can_fetch(UA, url):
        relatorio["requisicoes"].append({"url": url, "bloqueado_robots": True})
        return None
    espera = INTERVALO_S - (time.monotonic() - ultimo)
    if espera > 0:
        time.sleep(espera)
    try:
        resp = sessao.get(url, timeout=30)
    except requests.RequestException as erro:
        relatorio["requisicoes"].append({"url": url, "erro": str(erro)})
        return None
    finally:
        ultimo = time.monotonic()
    relatorio["requisicoes"].append(
        {
            "url": url,
            "status": resp.status_code,
            "tipo": resp.headers.get("Content-Type"),
            "bytes": len(resp.content),
        }
    )
    return resp


def salvar(nome: str, conteudo: str | bytes, sobrescrever: bool = False) -> None:
    caminho = DESTINO / nome
    if caminho.exists() and not sobrescrever:
        relatorio.setdefault("mantidos", []).append(nome)
        return
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(conteudo, bytes):
        caminho.write_bytes(conteudo)
    else:
        caminho.write_text(conteudo, encoding="utf-8")


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    r = obter(f"{BASE}/robots.txt", None)
    robots = urllib.robotparser.RobotFileParser()
    if r is not None and r.ok:
        salvar("robots.txt", r.text)
        robots.parse(r.text.splitlines())
    else:
        robots.parse([])

    for pagina in PAGINAS_LISTAGEM:
        url = LISTAGEM if pagina == 0 else f"{LISTAGEM}?page={pagina}"
        resp = obter(url, robots)
        if resp is not None and resp.ok:
            salvar(f"listagem_p{pagina}.html", resp.text)

    for caminho, com_edital in ALVOS.items():
        url = f"{BASE}{caminho}"
        resp = obter(url, robots)
        if resp is None or not resp.ok:
            continue
        slug = caminho.rstrip("/").rsplit("/", 1)[-1]
        salvar(f"concurso_{slug}.html", resp.text)
        if not com_edital:
            continue
        soup = BeautifulSoup(resp.text, "lxml")
        edital = None
        for a in soup.select(".field--name-field-concurso-arquivos a[href]"):
            titulo = a.get_text(" ", strip=True).lower()
            href = urljoin(url, a["href"])
            if (
                titulo.startswith("edital")
                and not re.search(
                    r"comunicado|resultado|convoca|homologa|extrato", titulo
                )
                and href.lower().split("?")[0].endswith(".pdf")
            ):
                edital = href
                break
        relatorio.setdefault("editais_escolhidos", {})[slug] = edital
        if edital is None:
            continue
        pdf = obter(edital, robots)
        if pdf is None or not pdf.ok:
            continue
        tmp = Path("/tmp") / f"edital_{slug}.pdf"
        tmp.write_bytes(pdf.content)
        with pdfplumber.open(tmp) as doc:
            textos = [pg.extract_text() or "" for pg in doc.pages[:400]]
        salvar(f"edital_{slug}_0.txt", "\n\f\n".join(textos))
        relatorio.setdefault("editais", []).append(
            {"url": edital, "paginas": len(textos)}
        )

    salvar(
        "_relatorio.json",
        json.dumps(relatorio, ensure_ascii=False, indent=2),
        sobrescrever=True,
    )
    print(json.dumps(relatorio, ensure_ascii=False)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Captura páginas reais da FGV para servirem de fixtures dos testes (roda no GitHub Actions).

Respeita robots.txt e espera 3 s entre requisições. Salva HTML, robots.txt, um relatório e o texto
extraído dos editais do concurso-alvo (os PDFs não são versionados).
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pdfplumber
import requests
from bs4 import BeautifulSoup

BASE = "https://conhecimento.fgv.br"
LISTAGEM = f"{BASE}/concursos"
UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
DESTINO = Path("coletor/tests/fixtures/fgv")
ALVO = re.compile(r"tjpb", re.I)
INTERVALO_S = 3.0

sessao = requests.Session()
sessao.headers["User-Agent"] = UA
relatorio: dict = {"requisicoes": []}
ultimo = 0.0


def obter(url: str, robots: urllib.robotparser.RobotFileParser | None) -> requests.Response | None:
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
        {"url": url, "status": resp.status_code, "tipo": resp.headers.get("Content-Type"), "bytes": len(resp.content)}
    )
    return resp


def salvar(nome: str, conteudo: str | bytes) -> None:
    caminho = DESTINO / nome
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

    paginas: list[str] = []
    for pagina in (0, 1):
        url = LISTAGEM if pagina == 0 else f"{LISTAGEM}?page={pagina}"
        resp = obter(url, robots)
        if resp is None or not resp.ok:
            continue
        salvar(f"listagem_p{pagina}.html", resp.text)
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.select("a[href]"):
            href = urljoin(BASE, a["href"])
            caminho = urlparse(href).path.rstrip("/")
            if href.startswith(BASE) and re.fullmatch(r"/concursos/[^/]+", caminho) and href not in paginas:
                paginas.append(href.split("?")[0].split("#")[0])
    relatorio["links_concurso"] = paginas

    alvos = [p for p in paginas if ALVO.search(p)]
    escolhidas = (alvos[:1] + [p for p in paginas if p not in alvos][:3])
    relatorio["escolhidas"] = escolhidas
    for url in escolhidas:
        resp = obter(url, robots)
        if resp is None or not resp.ok:
            continue
        slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        salvar(f"concurso_{slug}.html", resp.text)
        if not ALVO.search(url):
            continue
        soup = BeautifulSoup(resp.text, "lxml")
        pdfs = [urljoin(url, a["href"]) for a in soup.select("a[href]") if a["href"].lower().split("?")[0].endswith(".pdf")]
        relatorio["pdfs_alvo"] = pdfs
        editais = [p for p in pdfs if re.search(r"edital", p, re.I) and not re.search(r"retifica", p, re.I)] or pdfs
        for i, pdf_url in enumerate(editais[:2]):
            pdf = obter(pdf_url, robots)
            if pdf is None or not pdf.ok:
                continue
            tmp = Path("/tmp") / f"edital_{i}.pdf"
            tmp.write_bytes(pdf.content)
            with pdfplumber.open(tmp) as doc:
                textos = [pg.extract_text() or "" for pg in doc.pages]
                tabelas = []
                for n, pg in enumerate(doc.pages[:40]):
                    for t in pg.extract_tables():
                        tabelas.append({"pagina": n + 1, "linhas": t})
            salvar(f"edital_{slug}_{i}.txt", "\n\f\n".join(textos))
            salvar(f"edital_{slug}_{i}_tabelas.json", json.dumps(tabelas, ensure_ascii=False, indent=1))
            relatorio.setdefault("editais", []).append({"url": pdf_url, "paginas": len(textos)})

    salvar("_relatorio.json", json.dumps(relatorio, ensure_ascii=False, indent=2))
    print(json.dumps(relatorio, ensure_ascii=False)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

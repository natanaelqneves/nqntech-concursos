"""Captura uma lista de URLs (respeitando robots.txt, 3 s por domínio) em coletor/tests/fixtures/<pasta>/.
Também segue até N links por página que casem com um padrão, para pegar páginas de detalhe."""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
ALVOS = {
    "idecan": (
        ["https://concurso.idecan.org.br/editais"],
        r"^https://concurso\.idecan\.org\.br/editais/\d+$",
        4,
    ),
    "aocp": (
        [
            "https://www.institutoaocp.org.br/concursos/status/inscricoes-abertas",
            "https://www.institutoaocp.org.br/concursos/status/novos",
            "https://www.institutoaocp.org.br/concursos/status/em-andamento",
        ],
        r"^https://www\.institutoaocp\.org\.br/concursos/\d+[^/]*$",
        3,
    ),
    "ibam": (
        [
            "https://www.ibam-concursos.org.br/default.asp?status=1",
            "https://www.ibam-concursos.org.br/default.asp?status=2",
        ],
        r"$^",
        0,
    ),
    "ibade": (
        ["https://portal.ibade.selecao.site/edital"],
        r"^https://portal\.ibade\.selecao\.site/edital/[^?#]+$",
        3,
    ),
}
sessao = requests.Session()
sessao.headers["User-Agent"] = UA
ultimo: dict[str, float] = {}
robots: dict[str, urllib.robotparser.RobotFileParser] = {}
relatorio: dict = {}


def permitido(url: str) -> bool:
    host = urlsplit(url).netloc
    if host not in robots:
        p = urllib.robotparser.RobotFileParser()
        try:
            r = obter(f"https://{host}/robots.txt")
            relatorio.setdefault("_robots", {})[host] = [
                r.status_code,
                r.text[:1500] if r.ok else "",
            ]
            p.parse(r.text.splitlines() if r.ok else [])
            if r.status_code in (401, 403) or r.status_code >= 500:
                p.disallow_all = True
        except requests.RequestException as e:
            relatorio.setdefault("_robots", {})[host] = ["erro", str(e)[:200]]
            p.disallow_all = True
        robots[host] = p
    return robots[host].can_fetch(UA, url)


def obter(url: str) -> requests.Response:
    host = urlsplit(url).netloc
    espera = 3.0 - (time.monotonic() - ultimo.get(host, 0))
    if espera > 0:
        time.sleep(espera)
    try:
        return sessao.get(url, timeout=30)
    finally:
        ultimo[host] = time.monotonic()


def salvar(pasta: Path, nome: str, url: str) -> str | None:
    if not permitido(url):
        relatorio[pasta.name].append({"url": url, "bloqueado_robots": True})
        return None
    try:
        r = obter(url)
    except requests.RequestException as e:
        relatorio[pasta.name].append({"url": url, "erro": str(e)[:200]})
        return None
    relatorio[pasta.name].append(
        {
            "url": url,
            "status": r.status_code,
            "final": r.url,
            "bytes": len(r.content),
            "tipo": r.headers.get("Content-Type"),
        }
    )
    (pasta / nome).write_text(r.text, encoding="utf-8")
    return r.text


def main() -> int:
    for nome, (inicios, padrao, max_detalhes) in ALVOS.items():
        pasta = Path("coletor/tests/fixtures") / nome
        pasta.mkdir(parents=True, exist_ok=True)
        relatorio[nome] = []
        detalhes: list[str] = []
        for i, url in enumerate(inicios):
            html = salvar(pasta, f"lista_{i}.html", url)
            if html:
                for a in BeautifulSoup(html, "lxml").select("a[href]"):
                    href = urljoin(url, a["href"]).split("#")[0]
                    if re.match(padrao, href) and href not in detalhes:
                        detalhes.append(href)
        relatorio[nome + "_detalhes"] = detalhes[:40]
        for j, url in enumerate(detalhes[:max_detalhes]):
            salvar(pasta, f"detalhe_{j}.html", url)
    Path("coletor/tests/fixtures/_captura_urls.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=1)
    )
    print(json.dumps(relatorio, ensure_ascii=False)[:5000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

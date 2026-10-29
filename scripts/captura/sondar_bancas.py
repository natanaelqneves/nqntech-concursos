"""Sondagem de viabilidade (roda no GitHub Actions): para cada banca, robots.txt e a página de concursos,
a partir dos IPs de onde o coletor roda. Não segue nada que o robots.txt proíba."""

from __future__ import annotations

import json
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
BANCAS = {
    "cebraspe": "https://www.cebraspe.org.br/concursos/",
    "aocp": "https://www.institutoaocp.org.br/concursos",
    "quadrix": "https://site.quadrix.org.br/",
    "consulplan": "https://www.institutoconsulplan.org.br/",
    "fundatec": "https://www.fundatec.org.br/portal/concursos/",
    "ibade": "https://www.ibade.org.br/",
    "idecan": "https://www.idecan.org.br/",
    "ibfc": "https://www.ibfc.org.br/",
    "cesgranrio": "https://www.cesgranrio.org.br/concursos/",
    "fcc": "https://www.concursosfcc.com.br/",
    "access": "https://www.institutoaccess.org.br/",
    "fadesp": "https://www.fadesp.org.br/",
    "cetrede": "https://www.cetrede.com.br/",
    "ibam": "https://www.ibam-concursos.org.br/",
    "selecon_concursos": "https://selecon.org.br/concursos/",
    "selecon_anexos": "https://anexos-r2.selecao.net.br/uploads/746/concursos/73/anexos/1146677a-b45b-4e06-a36f-feba23ce6b50.pdf",
}


def main() -> int:
    destino = Path("coletor/tests/fixtures/sondagem")
    destino.mkdir(parents=True, exist_ok=True)
    sessao = requests.Session()
    sessao.headers["User-Agent"] = UA
    resultado = {}
    for nome, url in BANCAS.items():
        host = urlsplit(url).netloc
        item: dict = {"url": url}
        try:
            r = sessao.get(f"https://{host}/robots.txt", timeout=20)
            item["robots_status"] = r.status_code
            item["robots"] = r.text[:1500] if r.ok else ""
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(r.text.splitlines() if r.ok else [])
            if r.status_code in (401, 403) or r.status_code >= 500:
                parser.disallow_all = True
            item["permitido"] = parser.can_fetch(UA, url)
        except requests.RequestException as erro:
            item["robots_erro"] = str(erro)[:200]
            item["permitido"] = False
        time.sleep(2)
        if item.get("permitido"):
            try:
                p = sessao.get(url, timeout=25)
                item.update(status=p.status_code, final=p.url, tipo=p.headers.get("Content-Type"), bytes=len(p.content))
                if "html" in (p.headers.get("Content-Type") or ""):
                    soup = BeautifulSoup(p.text, "lxml")
                    for t in soup(["script", "style", "noscript", "svg"]):
                        t.decompose()
                    item["texto"] = " ".join(soup.get_text(" ").split())[:1200]
                    item["links"] = len(soup.select("a[href]"))
                    item["scripts_next"] = "__NEXT_DATA__" in p.text or "/_next/" in p.text
                    (destino / f"{nome}.html").write_text(p.text, encoding="utf-8")
            except requests.RequestException as erro:
                item["erro"] = str(erro)[:200]
            time.sleep(2)
        resultado[nome] = item
        print(nome, {k: v for k, v in item.items() if k not in ("robots", "texto")})
    (destino / "_sondagem.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

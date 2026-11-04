"""Sondagem de viabilidade de várias bancas (roda no GitHub Actions, de onde o coletor roda).

Para cada endereço candidato: robots.txt do host, se o acesso é permitido, status/tipo/tamanho da resposta, e, nas
páginas HTML, os scripts, rotas JSON/API e links de concursos citados. Scripts próprios com nome de banner/concurso
também são lidos (se o robots.txt permitir) para achar as rotas de dados. Nada bloqueado é acessado.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
DESTINO = Path("coletor/tests/fixtures/sondagem2")
BANCAS = {
    "fcc": ["https://www.concursosfcc.com.br/", "https://www1.concursosfcc.com.br/"],
    "cesgranrio": ["https://www.cesgranrio.org.br/", "https://www.cesgranrio.org.br/concursos/"],
    "vunesp": ["https://www.vunesp.com.br/", "https://vunesp.com.br/"],
    "aocp": ["https://www.institutoaocp.org.br/", "https://www.institutoaocp.org.br/concursos"],
    "ibfc": ["https://www.ibfc.org.br/", "https://ibfc.org.br/"],
    "quadrix": ["https://site.quadrix.org.br/", "https://www.quadrix.org.br/"],
    "idecan": ["https://www.idecan.org.br/", "https://idecan.org.br/"],
    "fundep": ["https://www.gestaodeconcursos.com.br/", "https://www.fundep.ufmg.br/"],
    "fumarc": ["https://www.fumarc.com.br/", "https://fumarc.com.br/"],
    "consulplan": ["https://www.institutoconsulplan.org.br/", "https://institutoconsulplan.org.br/"],
    "cpcon": ["https://cpcon.uepb.edu.br/"],
    "comperve": ["https://www.comperve.ufrn.br/", "https://comperve.ufrn.br/"],
}
_ROTAS = re.compile(r"""["'`]((?:https?://[^"'`\s]{4,200})|(?:/[A-Za-z0-9_./?=&%-]{2,160}))["'`]""")
_INTERESSE = re.compile(r"api|json|ajax|banner|concurso|edital|inscri|wp-json|graphql", re.IGNORECASE)


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
    robots: dict[str, urllib.robotparser.RobotFileParser] = {}
    relatorio: dict = {}

    def robo(host: str) -> urllib.robotparser.RobotFileParser:
        if host not in robots:
            parser = urllib.robotparser.RobotFileParser()
            info: dict = {}
            try:
                r = s.get(f"https://{host}/robots.txt", timeout=20)
                info = {"status": r.status_code, "texto": r.text[:3000] if r.ok else ""}
                parser.parse(r.text.splitlines() if r.ok else [])
                if r.status_code in (401, 403) or r.status_code >= 500:
                    parser.disallow_all = True
            except requests.RequestException as erro:
                info = {"erro": str(erro)[:200]}
                parser.disallow_all = True
            relatorio.setdefault("_robots", {})[host] = info
            robots[host] = parser
            time.sleep(2)
        return robots[host]

    for banca, urls in BANCAS.items():
        relatorio[banca] = {}
        for url in urls:
            host = urlsplit(url).netloc
            item: dict = {"permitido": robo(host).can_fetch(UA, url)}
            relatorio[banca][url] = item
            if not item["permitido"]:
                continue
            try:
                r = s.get(url, timeout=25)
            except requests.RequestException as erro:
                item["erro"] = str(erro)[:200]
                continue
            time.sleep(2)
            tipo = r.headers.get("Content-Type", "")
            item.update(status=r.status_code, final=r.url, tipo=tipo, bytes=len(r.content))
            if not (r.ok and "html" in tipo):
                continue
            nome = re.sub(r"[^a-z0-9]+", "_", url.lower()).strip("_")[:80]
            (DESTINO / f"{banca}__{nome}.html").write_text(r.text, encoding="utf-8")
            titulo = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.IGNORECASE | re.DOTALL)
            item["titulo"] = " ".join(titulo.group(1).split())[:150] if titulo else None
            scripts = re.findall(r"<script[^>]+src=[\"']([^\"']+)", r.text, re.IGNORECASE)
            item["scripts"] = scripts[:60]
            rotas = {m for m in _ROTAS.findall(r.text) if _INTERESSE.search(m)}
            item["links_concurso"] = sorted({urljoin(r.url, h) for h in re.findall(r"href=[\"']([^\"'#]+)", r.text)
                                             if re.search(r"concurso|edital|inscri", h, re.I)})[:80]  # fmt: skip
            for src in scripts:
                alvo = urljoin(r.url, src)
                proprio = urlsplit(alvo).netloc.endswith(".".join(host.split(".")[-3:]))
                if not proprio or not re.search(r"banner|concurso|config|main|app|chunk", alvo, re.I):
                    continue
                if not robo(urlsplit(alvo).netloc).can_fetch(UA, alvo):
                    item.setdefault("scripts_bloqueados", []).append(alvo)
                    continue
                try:
                    js = s.get(alvo, timeout=25)
                except requests.RequestException:
                    continue
                time.sleep(2)
                if js.ok:
                    arquivo = re.sub(r"[^a-zA-Z0-9.]+", "_", urlsplit(alvo).path)[-80:]
                    (DESTINO / f"{banca}__js_{arquivo}").write_text(js.text[:2_000_000], encoding="utf-8")
                    rotas |= {m for m in _ROTAS.findall(js.text) if _INTERESSE.search(m)}
            item["rotas"] = sorted(rotas)[:150]
            item["rotas_permitidas"] = {
                rota: robo(urlsplit(urljoin(r.url, rota)).netloc).can_fetch(UA, urljoin(r.url, rota))
                for rota in sorted(rotas)[:150]
                if re.search(r"api|json|ajax|banner|wp-json", rota, re.I)
            }
        print(banca, json.dumps({u: {k: v for k, v in i.items() if k in ("permitido", "status", "tipo", "bytes", "titulo")}
                                 for u, i in relatorio[banca].items()}, ensure_ascii=False))  # fmt: skip
    (DESTINO / "_sondagem.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

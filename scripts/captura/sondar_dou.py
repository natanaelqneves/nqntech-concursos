"""Sondagem da base de dados abertos do DOU (in.gov.br): robots.txt e links da página de downloads."""

from __future__ import annotations

import json
import re
import sys
import urllib.robotparser
from pathlib import Path

import requests

UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
PAGINA = "https://www.in.gov.br/acesso-a-informacao/dados-abertos/base-de-dados"
DESTINO = Path("coletor/tests/fixtures/dou")


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    rel: dict = {}
    r = s.get("https://www.in.gov.br/robots.txt", timeout=30)
    rel["robots"] = {"status": r.status_code, "texto": r.text[:4000]}
    p = urllib.robotparser.RobotFileParser()
    p.parse(r.text.splitlines() if r.ok else [])
    for url in [PAGINA, "https://www.in.gov.br/documents/", "https://www.in.gov.br/web/dou/"]:
        rel[f"permitido {url}"] = p.can_fetch(UA, url) if r.ok else r.status_code == 404
    if rel[f"permitido {PAGINA}"]:
        r = s.get(PAGINA, timeout=60)
        rel["pagina"] = {"status": r.status_code, "bytes": len(r.content)}
        if r.ok:
            links = re.findall(r'href="([^"]+)"[^>]*>(.*?)</a>', r.text, flags=re.S)
            rel["links"] = [(h, " ".join(re.sub("<[^>]+>", " ", t).split())[:80]) for h, t in links
                            if re.search(r"zip|xml|document|dados", h, re.I)][:150]
            rel["texto"] = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", "", r.text, flags=re.S)).split())[:3000]
            zips = [h for h, _ in links if ".zip" in h.lower()]
            if zips:
                alvo = zips[0] if zips[0].startswith("http") else "https://www.in.gov.br" + zips[0]
                rel["permitido zip"] = p.can_fetch(UA, alvo)
                if rel["permitido zip"]:
                    h = s.head(alvo, timeout=60, allow_redirects=True)
                    rel["zip"] = {"url": alvo, "status": h.status_code, "tipo": h.headers.get("Content-Type"),
                                  "tamanho": h.headers.get("Content-Length")}
    (DESTINO / "_relatorio.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rel, ensure_ascii=False, indent=1)[:60000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

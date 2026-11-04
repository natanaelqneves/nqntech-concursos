"""Sondagem 3: texto completo de uma publicação do DOE-SP e resultado da busca do SIGPub."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
DESTINO = Path("coletor/tests/fixtures/diarios")
SLUG = "executivo/universidade-estadual-paulista/edital-n-145-2026stgp-dtad-de-27-de-outubro-de-2026-202610271344421162237843"
ID = "bd936be7-8232-4819-2f9e-08df2e3de7b6"


def main() -> int:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    rel: dict = {}
    urls = {
        "sp_pagina": f"https://doe.sp.gov.br/{SLUG}",
        "sp_api_slug": f"https://do-api-web-search.doe.sp.gov.br/v2/publications/{SLUG}",
        "sp_api_id": f"https://do-api-web-search.doe.sp.gov.br/v2/publications/{ID}",
        "sp_api2_slug": f"https://do-api.doe.sp.gov.br/v2/publications/{SLUG}",
        "sigpub_busca": "https://www.diariomunicipal.com.br/famup/pesquisar?busca_avancada%5Btexto%5D=edital+de+abertura+concurso+p%C3%BAblico",
    }
    for nome, url in urls.items():
        time.sleep(3)
        try:
            r = s.get(url, timeout=60)
        except requests.RequestException as erro:
            rel[nome] = {"erro": str(erro)[:200]}
            continue
        corpo = re.sub(r"<script.*?</script>|<style.*?</style>", "", r.text, flags=re.S)
        rel[nome] = {"status": r.status_code, "tipo": r.headers.get("Content-Type"),
                     "texto": " ".join(re.sub(r"<[^>]+>", " ", corpo).split())[:2500],
                     "links": sorted(set(re.findall(r'href="([^"#]+)"', r.text)))[:60],
                     "apis": sorted(set(re.findall(r'https://[a-z0-9.-]*doe\.sp\.gov\.br[^"\'\s]*', r.text)))[:20]}
        if r.ok:
            ext = "json" if "json" in (r.headers.get("Content-Type") or "") else "html"
            (DESTINO / f"{nome}.{ext}").write_text(r.text, encoding="utf-8")
    (DESTINO / "_relatorio3.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: {x: v.get(x) for x in ("status", "tipo", "erro")} for k, v in rel.items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

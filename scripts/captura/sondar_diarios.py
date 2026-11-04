"""Sondagem 2: API de busca do DOE-SP e formulário de pesquisa do SIGPub (diários municipais)."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
DESTINO = Path("coletor/tests/fixtures/diarios")
SP = "https://do-api-web-search.doe.sp.gov.br/v2/advanced-search/publications"


def main() -> int:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    rel: dict = {}
    variantes = {
        "sp_periodo": {"Terms[0]": "edital de abertura", "FromDate": "2026-10-28", "ToDate": "2026-11-04",
                       "PageNumber": 1, "PageSize": 20, "periodStartingDate": "personalized"},
        "sp_concurso": {"Terms[0]": "concurso público", "FromDate": "2026-10-28", "ToDate": "2026-11-04",
                        "PageNumber": 1, "PageSize": 20, "periodStartingDate": "personalized", "SortField": "Date"},
    }
    for nome, params in variantes.items():
        time.sleep(3)
        r = s.get(SP, params=params, timeout=60)
        rel[nome] = {"url": r.url, "status": r.status_code, "inicio": r.text[:3000]}
        if r.ok:
            (DESTINO / f"{nome}.json").write_text(r.text, encoding="utf-8")
    for caminho in ["https://doe.sp.gov.br/busca-avancada", "https://www.diariomunicipal.com.br/famup/pesquisar"]:
        time.sleep(3)
        r = s.get(caminho, timeout=60)
        nome = re.sub(r"\W+", "_", caminho.split("//")[1])[:50]
        (DESTINO / f"{nome}.html").write_text(r.text, encoding="utf-8")
        forms = re.findall(r"<form[^>]*>.*?</form>", r.text, flags=re.S | re.I)
        rel[nome] = {"status": r.status_code, "forms": [re.sub(r"\s+", " ", f)[:2500] for f in forms][:3],
                     "scripts": re.findall(r'src="([^"]+\.js[^"]*)"', r.text)[:15]}
    (DESTINO / "_relatorio2.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rel, ensure_ascii=False, indent=1)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

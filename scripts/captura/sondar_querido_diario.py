"""Sondagem Querido Diário (Fase 6): robots.txt, termos e uma busca de editais de abertura recentes."""

from __future__ import annotations

import json
import sys
import time
import urllib.robotparser
from datetime import date, timedelta
from pathlib import Path

import requests

UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
DESTINO = Path("coletor/tests/fixtures/querido_diario")
API = "https://api.queridodiario.ok.org.br"


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    rel: dict = {}
    for host in (API, "https://queridodiario.ok.org.br"):
        r = s.get(f"{host}/robots.txt", timeout=20)
        rel[f"robots {host}"] = {"status": r.status_code, "texto": r.text[:1500]}
    p = urllib.robotparser.RobotFileParser()
    r = s.get(f"{API}/robots.txt", timeout=20)
    p.parse(r.text.splitlines() if r.ok else [])
    url = f"{API}/gazettes"
    rel["permitido /gazettes"] = p.can_fetch(UA, url) if r.ok else (r.status_code == 404)
    if not rel["permitido /gazettes"]:
        print(json.dumps(rel, ensure_ascii=False, indent=1))
        return 0
    desde = (date.today() - timedelta(days=3)).isoformat()
    for nome, consulta in {
        "abertura": '"concurso público" + "edital de abertura"',
        "inscricoes": '"concurso público" + "inscrições"',
    }.items():
        time.sleep(3)
        r = s.get(url, timeout=60, params={
            "querystring": consulta, "published_since": desde, "excerpt_size": 600,
            "number_of_excerpts": 2, "size": 20, "sort_by": "descending_date",
        })
        rel[nome] = {"status": r.status_code, "tipo": r.headers.get("Content-Type"), "url": r.url}
        if r.ok:
            (DESTINO / f"gazettes_{nome}.json").write_text(r.text, encoding="utf-8")
            d = r.json()
            rel[nome]["total"] = d.get("total_gazettes")
            rel[nome]["campos"] = sorted((d.get("gazettes") or [{}])[0].keys())
            rel[nome]["amostra"] = [
                {k: g.get(k) for k in ("territory_name", "state_code", "date", "url", "txt_url")}
                | {"trecho": (g.get("excerpts") or [""])[0][:300]}
                for g in d.get("gazettes", [])[:6]
            ]
    time.sleep(3)
    r = s.get(f"{API}/cities", params={"levels": "3"}, timeout=60)
    rel["cities"] = {"status": r.status_code, "n": len(r.json().get("cities", [])) if r.ok else None}
    (DESTINO / "_relatorio.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rel, ensure_ascii=False, indent=1)[:60000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Sondagem da Cebraspe (roda no GitHub Actions): robots.txt do site e da API, e respostas reais da API JSON que o
próprio app de concursos usa (fases "novos" e "inscricoes-abertas" + um detalhe), salvas como fixtures de teste.
Só acessa o que o robots.txt de cada host permite."""

from __future__ import annotations

import json
import sys
import time
import urllib.robotparser
from pathlib import Path

import requests

UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
API = "https://apis.cebraspe.org.br/cebraspe/eventos"
FASES = ("novos", "inscricoes-abertas")
DESTINO = Path("coletor/tests/fixtures/cebraspe")


def robots(sessao: requests.Session, host: str) -> tuple[urllib.robotparser.RobotFileParser, dict]:
    r = sessao.get(f"https://{host}/robots.txt", timeout=20)
    robo = urllib.robotparser.RobotFileParser()
    robo.parse(r.text.splitlines() if r.ok else [])
    if r.status_code in (401, 403) or r.status_code >= 500:
        robo.disallow_all = True
    (DESTINO / f"robots_{host}.txt").write_text(r.text if r.ok else f"HTTP {r.status_code}", encoding="utf-8")
    return robo, {"status": r.status_code, "texto": r.text[:2000] if r.ok else ""}


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    relatorio: dict = {}
    robo_api, relatorio["robots_api"] = robots(s, "apis.cebraspe.org.br")
    _, relatorio["robots_site"] = robots(s, "www.cebraspe.org.br")
    identificador = None
    for fase in FASES:
        url = f"{API}/tipo/concursos/fase/{fase}"
        item: dict = {"permitido": robo_api.can_fetch(UA, url)}
        relatorio[fase] = item
        if not item["permitido"]:
            continue
        time.sleep(3)
        r = s.get(url, timeout=25, headers={"Accept": "application/json"})
        item.update(status=r.status_code, tipo=r.headers.get("Content-Type"), bytes=len(r.content))
        if r.ok:
            (DESTINO / f"fase_{fase}.json").write_text(r.text, encoding="utf-8")
            dados = r.json()
            item["itens"] = len(dados) if isinstance(dados, list) else None
            if isinstance(dados, list) and dados:
                item["chaves"] = sorted(dados[0].keys()) if isinstance(dados[0], dict) else None
                item["exemplo"] = dados[0]
                identificador = identificador or next(
                    (d.get(k) for d in dados for k in ("identificador", "slug", "id") if isinstance(d, dict) and d.get(k)),
                    None,
                )
    if identificador is not None:
        url = f"{API}/{identificador}"
        relatorio["detalhe"] = {"url": url, "permitido": robo_api.can_fetch(UA, url)}
        if relatorio["detalhe"]["permitido"]:
            time.sleep(3)
            r = s.get(url, timeout=25, headers={"Accept": "application/json"})
            relatorio["detalhe"].update(status=r.status_code, bytes=len(r.content))
            if r.ok:
                (DESTINO / "detalhe.json").write_text(r.text, encoding="utf-8")
                d = r.json()
                relatorio["detalhe"]["chaves"] = sorted(d.keys()) if isinstance(d, dict) else None
    (DESTINO / "_sondagem.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(relatorio, ensure_ascii=False, indent=1)[:8000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

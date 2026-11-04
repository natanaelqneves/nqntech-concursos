"""Sondagem da Cebraspe (roda no GitHub Actions): robots.txt, página de concursos e possíveis rotas JSON citadas
nos scripts da página. Só acessa o que o robots.txt permite; não segue nada bloqueado."""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin

import requests

UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
BASE = "https://www.cebraspe.org.br"
PAGINAS = ["/concursos/", "/concursos"]
DESTINO = Path("coletor/tests/fixtures/cebraspe")


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    relatorio: dict = {}
    r = s.get(f"{BASE}/robots.txt", timeout=20)
    relatorio["robots_status"] = r.status_code
    relatorio["robots"] = r.text[:4000] if r.ok else ""
    (DESTINO / "robots.txt").write_text(r.text if r.ok else f"HTTP {r.status_code}", encoding="utf-8")
    robo = urllib.robotparser.RobotFileParser()
    robo.parse(r.text.splitlines() if r.ok else [])
    if r.status_code in (401, 403) or r.status_code >= 500:
        robo.disallow_all = True

    def permitido(url: str) -> bool:
        return robo.can_fetch(UA, url)

    for caminho in PAGINAS:
        url = BASE + caminho
        relatorio[caminho] = {"permitido": permitido(url)}
        if not permitido(url):
            continue
        time.sleep(3)
        p = s.get(url, timeout=25)
        relatorio[caminho].update(status=p.status_code, tipo=p.headers.get("Content-Type"), final=p.url)
        if p.ok and "html" in (p.headers.get("Content-Type") or ""):
            (DESTINO / "concursos.html").write_text(p.text, encoding="utf-8")
            scripts = re.findall(r'<script[^>]+src="([^"]+)"', p.text)
            relatorio[caminho]["scripts"] = scripts[:40]
            # Rotas de API citadas no HTML ou nos scripts próprios do site.
            rotas = set(re.findall(r'["\'](/(?:api|_api|wp-json)[^"\'\s]{1,120})["\']', p.text))
            for src in scripts:
                alvo = urljoin(url, src)
                if "cebraspe.org.br" not in alvo or not permitido(alvo):
                    continue
                time.sleep(2)
                js = s.get(alvo, timeout=25)
                if js.ok:
                    rotas |= set(re.findall(r'["\'`]((?:https://[a-z0-9.-]*cebraspe\.org\.br)?/(?:api|_api|wp-json)[^"\'`\s]{1,160})["\'`]', js.text))
            # A lista é um app React (/concursos/static/js/*.chunk.js): as URLs de dados estão no bundle.
            for src in re.findall(r'(/concursos/static/js/[^"]+\.js)', p.text):
                alvo = urljoin(url, src)
                if not permitido(alvo):
                    continue
                time.sleep(2)
                js = s.get(alvo, timeout=25)
                if js.ok:
                    (DESTINO / Path(src).name).write_text(js.text, encoding="utf-8")
                    rotas |= set(re.findall(r'["\'`](https?://[^"\'`\s]{8,200})["\'`]', js.text))
                    rotas |= set(re.findall(r'["\'`](/[a-zA-Z0-9_-]+/[^"\'`\s]{2,160})["\'`]', js.text))
            relatorio[caminho]["rotas_api"] = sorted(rotas)[:200]
            relatorio["rotas_permitidas"] = {
                rota: permitido(urljoin(BASE, rota)) for rota in sorted(rotas)[:200] if "cebraspe" in rota or rota[0] == "/"
            }
        break
    (DESTINO / "_sondagem.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(relatorio, ensure_ascii=False, indent=1)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

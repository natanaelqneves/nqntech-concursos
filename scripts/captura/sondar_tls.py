"""Sondagem FUMARC e COMPERVE (2ª rodada), com verificação TLS ATIVA usando o bundle padrão + o intermediário
GlobalSign RSA OV SSL CA 2018 que esses servidores deixam de enviar (baixado na 1ª rodada, público)."""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import certifi
import requests

UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
DESTINO = Path("coletor/tests/fixtures/tls")
INTERMEDIARIO = DESTINO / "intermediario_www_fumarc_com_br.pem"
ALVOS = [
    "https://www.comperve.ufrn.br/conteudo/concursos/cref_202601/documentos.php",
    "https://www.comperve.ufrn.br/conteudo/concursos/mossoro_202601/informacoes.php",
    "https://www.comperve.ufrn.br/conteudo/concursos/mossoro_202601/documentos.php",
    "https://www.comperve.ufrn.br/conteudo/concursos/mossoro_202601/inscricoes.php",
]


def main() -> int:
    bundle = DESTINO / "_bundle.pem"
    bundle.write_text(Path(certifi.where()).read_text() + "\n" + INTERMEDIARIO.read_text(), encoding="utf-8")
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.verify = str(bundle)
    robots: dict[str, urllib.robotparser.RobotFileParser] = {}
    relatorio: dict = {}

    def permitido(url: str) -> bool:
        host = urlsplit(url).netloc
        if host not in robots:
            p = urllib.robotparser.RobotFileParser()
            r = s.get(f"https://{host}/robots.txt", timeout=20)
            p.parse(r.text.splitlines() if r.ok else [])
            p.disallow_all = r.status_code in (401, 403) or r.status_code >= 500
            robots[host] = p
        return robots[host].can_fetch(UA, url)

    def baixar(nome: str, url: str) -> requests.Response | None:
        item: dict = {"url": url, "permitido": permitido(url)}
        relatorio[nome] = item
        if not item["permitido"]:
            return None
        time.sleep(3)
        r = s.get(url, timeout=30, headers={"Accept": "application/json;odata=nometadata, text/html;q=0.9, */*;q=0.5"})
        item.update(status=r.status_code, tipo=r.headers.get("Content-Type"), bytes=len(r.content))
        return r

    for url in ALVOS:
        nome = re.sub(r"[^a-z0-9]+", "_", urlsplit(url).path.lower()).strip("_")[-60:]
        r = baixar(nome, url)
        if r is None or not r.ok:
            continue
        if url.endswith(".js"):
            rotas = sorted(
                set(re.findall(r"[\"'`]((?:https?://[^\"'`\s]{4,200})|(?:/[^\"'`\s]{2,200}))[\"'`]", r.text))
            )
            relatorio[nome]["rotas"] = [x for x in rotas if re.search(r"_api|lists|getbytitle|concurso|json", x, re.I)][
                :80
            ]
            relatorio[nome]["trechos"] = re.findall(r".{0,120}(?:_api|getbytitle).{0,200}", r.text)[:15]
        else:
            (DESTINO / f"{nome}.html").write_text(r.text, encoding="utf-8")
    bundle.unlink()
    (DESTINO / "_tls2.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(relatorio, ensure_ascii=False, indent=1)[:8000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

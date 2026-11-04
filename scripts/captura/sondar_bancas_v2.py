"""Sondagem de viabilidade (2ª rodada, só os candidatos viáveis): baixa as respostas reais das rotas de listagem
permitidas pelo robots.txt e grava como fixtures de teste (com chaves de terceiros removidas)."""

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
ALVOS = {
    "fcc_publicacoes": "https://www.concursosfcc.com.br/webapi/publicacao/v1/Publicacao/ListarPublicacaoLiberadas/0",
    "fcc_home": "https://www.concursosfcc.com.br/",
    "aocp_api": "https://www.institutoaocp.org.br/api/concursos",
    "aocp_abertas": "https://www.institutoaocp.org.br/concursos/status/inscricoes-abertas",
    "aocp_novos": "https://www.institutoaocp.org.br/concursos/status/novos",
    "idecan_editais": "https://concurso.idecan.org.br/editais",
    "fundep_home": "https://www.gestaodeconcursos.com.br/",
    "fundep_anexos": "https://www.gestaodeconcursos.com.br/site/Site/AnexosConcursos.aspx",
}
_CHAVE = re.compile(r"((?:key|token|apikey|api_key|secret|sig)=)[^&\"'\s]+", re.IGNORECASE)


def limpar(texto: str) -> str:
    return re.sub(r"AIza[0-9A-Za-z_-]{20,}", "***", _CHAVE.sub(r"\1***", texto))


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
    robots: dict[str, urllib.robotparser.RobotFileParser] = {}
    relatorio: dict = {}

    def permitido(url: str) -> bool:
        host = urlsplit(url).netloc
        if host not in robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                r = s.get(f"https://{host}/robots.txt", timeout=20)
                parser.parse(r.text.splitlines() if r.ok else [])
                parser.disallow_all = r.status_code in (401, 403) or r.status_code >= 500
                relatorio.setdefault("_robots", {})[host] = {
                    "status": r.status_code,
                    "texto": r.text[:1500] if r.ok else "",
                }
            except requests.RequestException as erro:
                parser.disallow_all = True
                relatorio.setdefault("_robots", {})[host] = {"erro": str(erro)[:200]}
            robots[host] = parser
            time.sleep(2)
        return robots[host].can_fetch(UA, url)

    for nome, url in ALVOS.items():
        item: dict = {"url": url, "permitido": permitido(url)}
        relatorio[nome] = item
        if not item["permitido"]:
            continue
        try:
            r = s.get(url, timeout=30, headers={"Accept": "application/json, text/html;q=0.9"})
        except requests.RequestException as erro:
            item["erro"] = str(erro)[:200]
            continue
        time.sleep(3)
        tipo = r.headers.get("Content-Type", "")
        item.update(status=r.status_code, tipo=tipo, bytes=len(r.content), final=r.url)
        if r.ok and len(r.content) < 3_000_000:
            extensao = "json" if "json" in tipo else "html"
            (DESTINO / f"{nome}.{extensao}").write_text(limpar(r.text), encoding="utf-8")
            if extensao == "html":
                links = sorted({urljoin(r.url, h) for h in re.findall(r"href=[\"']([^\"'#]+)", r.text)})
                item["links"] = [link for link in links if not link.startswith("mailto")][:150]
                item["rotas_api"] = sorted(
                    set(re.findall(r"[\"'`](/api/[^\"'`\s]{1,120}|https?://[^\"'`\s]*/api/[^\"'`\s]{1,120})", r.text))
                )[:40]
        print(nome, {k: v for k, v in item.items() if k in ("permitido", "status", "tipo", "bytes")})
    (DESTINO / "_sondagem2.json").write_text(
        limpar(json.dumps(relatorio, ensure_ascii=False, indent=1)), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

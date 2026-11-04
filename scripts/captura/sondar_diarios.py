"""Sondagem de diários oficiais (Fase 6): robots.txt e resposta da página inicial a partir do GitHub Actions.
Não segue links nem baixa PDFs: só diz quais podem ser coletados sem contornar nada."""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.robotparser
from pathlib import Path

import requests

UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
DESTINO = Path("coletor/tests/fixtures/diarios")
ALVOS = {
    "DOU": "https://www.in.gov.br/leiturajornal",
    "DOU-dados-abertos": "https://www.in.gov.br/acesso-a-informacao/dados-abertos/base-de-dados",
    "INLABS": "https://inlabs.in.gov.br/",
    "Querido-Diario-API": "https://api.queridodiario.ok.org.br/gazettes?querystring=concurso&size=1",
    "DOE-SP": "https://doe.sp.gov.br/",
    "DOE-SP-api": "https://do-api-web-search.doe.sp.gov.br/v2/advanced-search/publications?Terms[0]=concurso&PageNumber=1&PageSize=5",
    "DOERJ": "https://www.ioerj.com.br/portal/",
    "DOE-MG": "https://www.jornalminasgerais.mg.gov.br/",
    "DOE-PR": "https://www.documentos.dioe.pr.gov.br/dioe/consultaPublicaPDF.do",
    "DOE-RS": "https://www.diariooficial.rs.gov.br/",
    "DOE-SC": "https://portal.doe.sea.sc.gov.br/",
    "DOE-BA": "https://dool.egba.ba.gov.br/",
    "DOE-PE": "https://diariooficial.cepe.com.br/diariooficialweb/",
    "DOE-CE": "https://www.ceara.gov.br/diario-oficial/",
    "DOE-PB": "https://auniao.pb.gov.br/doe",
    "DOE-GO": "https://diariooficial.abc.go.gov.br/",
    "DODF": "https://dodf.df.gov.br/",
    "DOE-PA": "https://www.ioepa.com.br/",
    "DOE-ES": "https://ioes.dio.es.gov.br/",
    "DOM-FAMUP-PB": "https://www.diariomunicipal.com.br/famup/",
    "DOM-AMM-MG": "https://www.diariomunicipal.com.br/amm-mg/",
}


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    rel: dict = {}
    for nome, url in ALVOS.items():
        host = url.split("/")[2]
        item: dict = {"url": url}
        try:
            r = s.get(f"https://{host}/robots.txt", timeout=25)
            item["robots_status"] = r.status_code
            item["robots"] = r.text[:600] if r.ok else ""
            p = urllib.robotparser.RobotFileParser()
            p.parse(r.text.splitlines() if r.ok else [])
            permitido = p.can_fetch(UA, url) if r.ok else r.status_code in (404, 410)
            item["permitido"] = permitido
            if permitido:
                time.sleep(2)
                r = s.get(url, timeout=30)
                item.update(status=r.status_code, tipo=r.headers.get("Content-Type"), bytes=len(r.content))
                texto = re.sub(r"<script.*?</script>|<style.*?</style>", "", r.text, flags=re.S)
                item["trecho"] = " ".join(re.sub(r"<[^>]+>", " ", texto).split())[:400]
                item["links_busca"] = sorted(set(re.findall(r'(?:href|action)="([^"]*(?:busca|pesquisa|search|consulta|api)[^"]*)"', r.text, re.I)))[:15]
        except requests.RequestException as erro:
            item["erro"] = f"{type(erro).__name__}: {str(erro)[:200]}"
        rel[nome] = item
        time.sleep(1)
    (DESTINO / "_relatorio.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    for nome, item in rel.items():
        print(nome, "|", item.get("robots_status"), "| permitido:", item.get("permitido"), "| status:",
              item.get("status"), "|", item.get("erro", "")[:120], "|", item.get("trecho", "")[:100])
    return 0


if __name__ == "__main__":
    sys.exit(main())

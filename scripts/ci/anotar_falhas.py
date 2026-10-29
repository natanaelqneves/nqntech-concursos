"""Transforma falhas de teste/compilação em anotações do GitHub Actions (visíveis no resumo da execução).

Uso: python scripts/ci/anotar_falhas.py [relatorios-junit.xml ...] [--log arquivo.log]
Lê relatórios JUnit (pytest --junitxml, Maven Surefire) e, opcionalmente, linhas [ERROR] de um log do Maven.
"""

from __future__ import annotations

import argparse
import glob
import sys
import xml.etree.ElementTree as ET

LIMITE = 10  # o GitHub mostra no máximo 10 anotações de erro por passo
MAX_MENSAGEM = 1500


def escapar(texto: str) -> str:
    # Formato dos comandos de workflow: %, \r e \n precisam ser codificados.
    return texto.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def falhas_junit(caminhos: list[str]) -> list[tuple[str, str]]:
    falhas = []
    for padrao in caminhos:
        for caminho in sorted(glob.glob(padrao)):
            try:
                raiz = ET.parse(caminho).getroot()
            except ET.ParseError:
                continue
            for caso in raiz.iter("testcase"):
                for tipo in ("failure", "error"):
                    for problema in caso.findall(tipo):
                        nome = f"{caso.get('classname', '')}.{caso.get('name', '')}"
                        detalhe = (problema.get("message") or "") + "\n" + (problema.text or "")
                        falhas.append((nome, detalhe.strip()[-MAX_MENSAGEM:]))
    return falhas


def erros_do_log(caminho: str) -> list[tuple[str, str]]:
    try:
        linhas = open(caminho, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return []
    erros = [linha for linha in linhas if linha.startswith("[ERROR]") and len(linha) > 8]
    return [("maven", "\n".join(erros[:40])[-MAX_MENSAGEM * 2:])] if erros else []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("relatorios", nargs="*")
    parser.add_argument("--log")
    args = parser.parse_args()
    falhas = falhas_junit(args.relatorios)
    if not falhas and args.log:
        falhas = erros_do_log(args.log)
    for titulo, mensagem in falhas[:LIMITE]:
        print(f"::error title={escapar(titulo)[:200]}::{escapar(mensagem)}")
    print(f"{len(falhas)} falha(s) anotada(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

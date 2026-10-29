"""Cria o .env de desenvolvimento a partir do .env.example, com senhas locais aleatórias.

Não sobrescreve um .env existente. Só troca valores que começam com "troque-" em linhas ativas
(o bloco de produção está comentado e nunca é tocado).
Uso: python scripts/criar_env.py [--email voce@exemplo.com]
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LINHA_COM_VALOR_EXEMPLO = re.compile(r"^(?P<chave>[A-Z0-9_]+)=troque-[^\s]*$")
LINHA_EMAIL = re.compile(r"^(?P<chave>COLETOR_CONTATO_EMAIL)=.*$")


def gerar_conteudo(exemplo: str, email: str | None) -> str:
    linhas: list[str] = []
    for linha in exemplo.splitlines():
        if m := LINHA_COM_VALOR_EXEMPLO.match(linha):
            # token_urlsafe evita caracteres que quebram URLs JDBC e o parser do .env.
            linha = f"{m['chave']}={secrets.token_urlsafe(24)}"
        elif email and (m := LINHA_EMAIL.match(linha)):
            linha = f"{m['chave']}={email}"
        linhas.append(linha)
    return "\n".join(linhas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cria o .env de dev com senhas aleatórias.")
    parser.add_argument("--email", help="seu e-mail (contato publicado no User-Agent do coletor)")
    args = parser.parse_args(argv)

    destino = RAIZ / ".env"
    if destino.exists():
        print(".env já existe; nada foi alterado.")
        return 0
    if args.email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", args.email):
        print(f"E-mail inválido: {args.email}", file=sys.stderr)
        return 2

    exemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
    destino.write_text(gerar_conteudo(exemplo, args.email), encoding="utf-8")
    print(".env criado com senhas locais aleatórias (fica só na sua máquina; está no .gitignore).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

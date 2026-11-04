#!/usr/bin/env bash
# Importa PDFs de uma pasta para o banco do NqnTech Concursos (Linux/macOS).
# Uso: scripts/importar/importar_pdfs.sh /caminho/da/pasta FCC [https://link-oficial]
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ $# -lt 2 ]]; then echo "Uso: $0 PASTA SIGLA_DA_BANCA [LINK_OFICIAL]"; exit 2; fi
if [[ ! -f .env ]]; then
  echo "Falta o .env na raiz do repositório: copie scripts/importar/env.importacao.example para .env e preencha."
  exit 2
fi
if [[ ! -x coletor/.venv/bin/python ]]; then
  echo "Preparando o ambiente Python pela primeira vez..."
  python3.13 -m venv coletor/.venv 2>/dev/null || python3 -m venv coletor/.venv
  coletor/.venv/bin/python -m pip install --quiet --upgrade pip
  coletor/.venv/bin/python -m pip install --quiet -e coletor
fi
args=(importar-pdfs "$1" --banca "$2")
[[ $# -ge 3 ]] && args+=(--link "$3")
exec coletor/.venv/bin/python -m coletor "${args[@]}"

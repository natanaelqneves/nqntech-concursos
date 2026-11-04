#!/usr/bin/env bash
# Sugere concursos abertos das bancas sem coleta automática (Gemini + Busca Google). Não grava nada no banco.
# Uso: scripts/importar/buscar_concursos.sh [FCC VUNESP ...]
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ -f .env ]] || { echo "Falta o .env na raiz (basta GEMINI_API_KEY=...)."; exit 2; }
if [[ ! -x coletor/.venv/bin/python ]]; then
  python3.13 -m venv coletor/.venv 2>/dev/null || python3 -m venv coletor/.venv
  coletor/.venv/bin/python -m pip install --quiet --upgrade pip
  coletor/.venv/bin/python -m pip install --quiet -e coletor
fi
if [[ $# -gt 0 ]]; then exec coletor/.venv/bin/python -m coletor buscar-concursos --bancas "$@"; fi
exec coletor/.venv/bin/python -m coletor buscar-concursos

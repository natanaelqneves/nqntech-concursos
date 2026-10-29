#!/usr/bin/env bash
# Sobe o ambiente de dev (Postgres + Flyway + Mailpit), mostra o status e roda a verificação.
# Uso: ./scripts/subir.sh [--email voce@exemplo.com]   (Linux, macOS ou Git Bash/WSL no Windows)
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="$(command -v python3 || command -v python || true)"
if [[ -z "$PYTHON" ]]; then
  echo "Python 3 não encontrado. Instale o Python 3.13+ e rode de novo." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker não está rodando. Abra o Docker Desktop (ou inicie o serviço) e rode de novo." >&2
  exit 1
fi

"$PYTHON" scripts/criar_env.py "$@"

echo "Subindo contêineres..."
docker compose up -d

"$PYTHON" scripts/verificar_ambiente.py --aguardar 180 || {
  echo
  echo "Logs do flyway (últimas 30 linhas):"
  docker compose logs --tail 30 flyway
  exit 1
}

echo
docker compose ps --all

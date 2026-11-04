#!/usr/bin/env bash
# Compila estilo/site.scss (Bootstrap enxuto + componentes) em src/main/resources/static/assets/site.css.
#   site/estilo/compilar.sh            gera o CSS (commite o resultado junto com o .scss)
#   site/estilo/compilar.sh --conferir  falha se o CSS commitado não for o que o .scss gera (usado na CI)
# Sem Node: Dart Sass standalone (binário oficial, SHA-256 conferido) e o Bootstrap pela tag do Git (commit
# conferido). Para atualizar, troque versão + hash aqui e rode de novo.
set -euo pipefail

SASS_VERSAO="1.99.0"
SASS_SHA256="f0a32ab99bc0a1eb62ea7140a056a1bca82d534390b7c3dba4f2016eb0077753"
BOOTSTRAP_TAG="v5.3.8"
BOOTSTRAP_COMMIT="25aa8cc0b32f0d1a54be575347e6d84b70b1acd7"

aqui="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
destino="$aqui/../src/main/resources/static/assets/site.css"
cache="${ESTILO_CACHE:-$aqui/.cache}"
mkdir -p "$cache"

sass="$cache/dart-sass-$SASS_VERSAO/sass"
if [[ ! -x "$sass" ]]; then
  pacote="$cache/dart-sass-$SASS_VERSAO.tar.gz"
  curl -fsSL -o "$pacote" \
    "https://github.com/sass/dart-sass/releases/download/$SASS_VERSAO/dart-sass-$SASS_VERSAO-linux-x64.tar.gz"
  echo "$SASS_SHA256  $pacote" | sha256sum --check --quiet
  mkdir -p "$cache/dart-sass-$SASS_VERSAO"
  tar -xzf "$pacote" -C "$cache/dart-sass-$SASS_VERSAO" --strip-components=1
fi

# Pasta "bootstrap" dentro do cache da versão: o .scss importa "bootstrap/scss/...".
bootstrap="$cache/bootstrap-$BOOTSTRAP_TAG/bootstrap"
if [[ ! -d "$bootstrap/scss" ]]; then
  rm -rf "$bootstrap"
  git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$BOOTSTRAP_TAG" \
    https://github.com/twbs/bootstrap.git "$bootstrap"
fi
commit="$(git -C "$bootstrap" rev-parse HEAD)"
if [[ "$commit" != "$BOOTSTRAP_COMMIT" ]]; then
  echo "Bootstrap $BOOTSTRAP_TAG aponta para $commit, esperado $BOOTSTRAP_COMMIT" >&2
  exit 1
fi

# O Bootstrap 5.3 ainda usa @import e funções globais do Sass: os avisos de depreciação dele são silenciados.
compilar() {
  "$sass" --no-source-map --style=compressed --quiet-deps \
    --silence-deprecation=import --silence-deprecation=global-builtin \
    --silence-deprecation=color-functions \
    --load-path="$cache/bootstrap-$BOOTSTRAP_TAG" --load-path="$aqui" \
    "$aqui/site.scss" "$1"
}

if [[ "${1:-}" == "--conferir" ]]; then
  temporario="$(mktemp)"
  trap 'rm -f "$temporario"' EXIT
  compilar "$temporario"
  if ! cmp -s "$temporario" "$destino"; then
    echo "site.css desatualizado: rode site/estilo/compilar.sh e commite o resultado." >&2
    exit 1
  fi
  echo "site.css confere com estilo/site.scss."
else
  compilar "$destino"
  echo "site.css: $(wc -c < "$destino") bytes ($(gzip -9c "$destino" | wc -c) compactado)."
fi

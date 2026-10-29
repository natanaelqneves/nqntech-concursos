-- Base do banco: schema da aplicação e extensões. Roda igual no Postgres local/CI e no Neon.

CREATE SCHEMA IF NOT EXISTS concursos;

-- Ninguém além do dono enxerga o schema por padrão; os papéis das aplicações recebem acesso explícito
-- (V3__papeis.sql).
REVOKE ALL ON SCHEMA concursos FROM PUBLIC;

-- Extensões num schema próprio, chamadas sempre qualificadas (extensions.unaccent, extensions.similarity).
CREATE SCHEMA IF NOT EXISTS extensions;

-- unaccent: normalizar nomes de órgãos/cargos sem acento (classificação por área e deduplicação).
CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA extensions;

-- pg_trgm: similaridade de títulos, última chave da deduplicação (seção 6 do contexto).
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;

COMMENT ON SCHEMA concursos IS 'NqnTech Concursos: concursos públicos coletados de fontes oficiais';

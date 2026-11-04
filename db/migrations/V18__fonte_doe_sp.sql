-- Fase 6, primeiro diário oficial: DOE-SP pela API pública de busca do próprio site (sondagem de 04/11/2026 a partir
-- do GitHub Actions; robots.txt inexistente). Diário oficial não tem banca: banca_id fica nulo e só a IA estrutura.
-- DOU, Querido Diário e a maioria dos diários estaduais recusaram a conexão ou deram erro de TLS na sondagem:
-- ficam de fora até responderem (nada contornado).

SET search_path = concursos;

ALTER TABLE fonte DROP CONSTRAINT fonte_tipo_ck;
ALTER TABLE fonte ADD CONSTRAINT fonte_tipo_ck
    CHECK (tipo IN ('BANCA_SITE', 'DOU_INLABS', 'QUERIDO_DIARIO', 'NOTICIA_RSS', 'MANUAL', 'DIARIO_OFICIAL'));

INSERT INTO fonte (tipo, nome, banca_id, ativa, url_base)
VALUES ('DIARIO_OFICIAL', 'doe-sp', NULL, true, 'https://do-api-web-search.doe.sp.gov.br/v2')
ON CONFLICT (nome) DO NOTHING;

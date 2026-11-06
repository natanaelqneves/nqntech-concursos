-- Nicho do site (decisão de 06/11/2026): concursos de grandes órgãos de controle, justiça, fisco, segurança e
-- carreiras militares. A categoria do órgão é gravada pelo coletor (config/nicho.yml) na etapa classificar; com o
-- nicho em modo "exclusivo", só concurso com categoria vai ao site.

SET search_path = concursos;

ALTER TABLE concurso
    ADD COLUMN orgao_categoria text,
    ADD CONSTRAINT concurso_orgao_categoria_ck CHECK (orgao_categoria IN (
        'unificado', 'tribunal_contas', 'controladoria', 'ministerio_publico', 'tribunal', 'defensoria',
        'advocacia_publica', 'fisco', 'legislativo', 'conselho', 'regulacao', 'policial', 'militar'));

COMMENT ON COLUMN concurso.orgao_categoria IS
    'Categoria do órgão no nicho do site (config/nicho.yml); nula = fora do nicho';

-- Cebraspe passa a ser coletada pela API JSON pública do próprio app de concursos (sondagem de 04/11/2026:
-- robots.txt do site libera tudo; apis.cebraspe.org.br e cdn.cebraspe.org.br não têm robots.txt).

SET search_path = concursos;

UPDATE banca
SET coleta_permitida = true,
    site             = 'https://www.cebraspe.org.br/concursos/',
    observacao       = 'API JSON (apis.cebraspe.org.br/cebraspe/eventos, fases novos e inscricoes-abertas); PDFs no '
                           || 'cdn.cebraspe.org.br; robots.txt liberado em 04/11/2026'
WHERE sigla = 'CEBRASPE';

INSERT INTO fonte (tipo, nome, banca_id, ativa, url_base)
SELECT 'BANCA_SITE', 'cebraspe', b.id, true, 'https://apis.cebraspe.org.br/cebraspe/eventos'
FROM banca b
WHERE b.sigla = 'CEBRASPE'
ON CONFLICT (nome) DO NOTHING;

-- O botão "Abrir o edital (PDF)" só pode levar a um PDF de verdade (05/11/2026). Documentos do Diário Oficial de SP
-- são lidos pela API de busca (o endereço gravado devolve JSON/texto, não PDF): ficam com abre_pdf = false e o site
-- manda a pessoa para a página da publicação (link oficial do concurso).

SET search_path = concursos;

ALTER TABLE documento ADD COLUMN abre_pdf boolean NOT NULL DEFAULT true;
UPDATE documento SET abre_pdf = false WHERE url_origem LIKE 'https://do-api-web-search.doe.sp.gov.br/%';

-- O site também confere se o arquivo foi lido como PDF (status OK/SEM_TEXTO): link que não era PDF não aparece.
GRANT SELECT (abre_pdf, status_extracao) ON documento TO site_app;

COMMENT ON COLUMN documento.abre_pdf IS 'true = url_origem abre um PDF (pode virar o botão do edital no site)';

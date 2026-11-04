-- Importação manual de PDFs (comando `importar-pdfs`, rodado no computador do administrador) para bancas cujo site
-- não permite coleta automática. Cada banca ganha uma fonte "manual-<sigla>" sempre INATIVA: a coleta diária a
-- ignora; só o comando de importação a usa. Os PDFs passam pelas mesmas etapas (texto, estruturação, IA,
-- classificação, resumo e publicação) dos baixados automaticamente.

SET search_path = concursos;

ALTER TABLE fonte DROP CONSTRAINT fonte_tipo_ck;
ALTER TABLE fonte ADD CONSTRAINT fonte_tipo_ck
    CHECK (tipo IN ('BANCA_SITE', 'DOU_INLABS', 'QUERIDO_DIARIO', 'NOTICIA_RSS', 'MANUAL'));

-- Para editais de bancas ainda sem cadastro.
INSERT INTO banca (nome, sigla, site, coleta_permitida, observacao)
VALUES ('Outra banca', 'OUTRA', NULL, false, 'editais importados manualmente sem banca cadastrada')
ON CONFLICT (sigla) DO NOTHING;

INSERT INTO fonte (tipo, nome, banca_id, ativa, url_base)
SELECT 'MANUAL', 'manual-' || lower(b.sigla), b.id, false, NULL
FROM banca b
ON CONFLICT (nome) DO NOTHING;

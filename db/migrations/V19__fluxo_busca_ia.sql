-- Fluxo único para todas as bancas (04/11/2026): busca na web com IA → pré-cadastro → edital (baixado sozinho ou
-- enviado pelo Drive com o código do concurso) → leitura do edital confere/completa → persistência → site.
-- Os coletores automáticos continuam como fontes de descoberta do mesmo fluxo.

SET search_path = concursos;

ALTER TABLE fonte DROP CONSTRAINT fonte_tipo_ck;
ALTER TABLE fonte ADD CONSTRAINT fonte_tipo_ck
    CHECK (tipo IN ('BANCA_SITE', 'DOU_INLABS', 'QUERIDO_DIARIO', 'NOTICIA_RSS', 'MANUAL', 'DIARIO_OFICIAL',
                    'BUSCA_IA'));

-- Sem banca: cada sugestão diz a banca dela (ou nenhuma, nas buscas por região).
INSERT INTO fonte (tipo, nome, banca_id, ativa, url_base)
VALUES ('BUSCA_IA', 'busca-ia', NULL, true, NULL)
ON CONFLICT (nome) DO NOTHING;

ALTER TABLE execucao_coleta DROP CONSTRAINT execucao_etapa_ck;
ALTER TABLE execucao_coleta ADD CONSTRAINT execucao_etapa_ck
    CHECK (etapa IN ('GERAL', 'DESCOBERTA', 'VINCULACAO', 'DOCUMENTOS', 'CLASSIFICACAO', 'ESTRUTURACAO', 'RESUMO',
                     'MANUTENCAO', 'LOCALIZACAO', 'PENDENCIAS'));

-- Quando cada alvo da busca (banca ou região de config/busca.yml) foi pesquisado: espaça as buscas para caber na
-- cota gratuita, mesmo com o fluxo rodando 4 vezes por dia.
CREATE TABLE busca_alvo (
    alvo       text PRIMARY KEY,
    buscado_em timestamptz NOT NULL,
    sugestoes  integer     NOT NULL DEFAULT 0,
    erro       text
);

-- Pré-cadastro: o que a busca na web disse do concurso. Fica fora de `concurso` porque o site lê todas as colunas de
-- concurso e este é dado bruto, não conferido. Depois que o edital é lido, só preenche o que o edital não trouxe.
CREATE TABLE concurso_busca (
    concurso_id         bigint PRIMARY KEY REFERENCES concurso (id) ON DELETE CASCADE,
    dados               jsonb       NOT NULL,
    atualizado_em       timestamptz NOT NULL DEFAULT now(),
    edital_procurado_em timestamptz,  -- última tentativa de achar/baixar o edital sozinho
    edital_falha        text          -- por que não conseguiu (vai para o e-mail de pendências)
);

-- Edital baixado de site não oficial (permitido para ler o texto) nunca aparece como link no site.
ALTER TABLE documento ADD COLUMN oficial boolean NOT NULL DEFAULT true;

GRANT SELECT, INSERT, UPDATE ON busca_alvo, concurso_busca TO coletor_app;
GRANT SELECT (oficial) ON documento TO site_app;
ALTER TABLE busca_alvo ENABLE ROW LEVEL SECURITY;
ALTER TABLE concurso_busca ENABLE ROW LEVEL SECURITY;
CREATE POLICY coletor_app_todas ON busca_alvo TO coletor_app USING (true) WITH CHECK (true);
CREATE POLICY coletor_app_todas ON concurso_busca TO coletor_app USING (true) WITH CHECK (true);

COMMENT ON TABLE busca_alvo IS 'Última busca na web (IA) por alvo de config/busca.yml';
COMMENT ON TABLE concurso_busca IS 'Pré-cadastro vindo da busca na web; o edital sempre prevalece';
COMMENT ON COLUMN documento.oficial IS 'false = baixado de site não oficial ou enviado à mão: lido, mas sem link no site';

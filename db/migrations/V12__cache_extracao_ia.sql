-- Camada 2 (extração com IA): cache das respostas pelo SHA-256 do PDF do edital. Garante que um edital vai à IA
-- uma única vez (por versão do esquema/prompt) e guarda também os descartes da triagem (resposta nula).

SET search_path = concursos;

CREATE TABLE extracao_ia (
    hash_sha256 char(64)    NOT NULL,
    versao      text        NOT NULL,
    origem      text        NOT NULL,  -- "<provedor>/<modelo>" ou "triagem"
    resposta    jsonb,                 -- null = não é edital de abertura (motivo explica)
    motivo      text,
    criado_em   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hash_sha256, versao),
    CONSTRAINT extracao_ia_hash_ck CHECK (hash_sha256 ~ '^[0-9a-f]{64}$')
);

-- Só o coletor usa; o site nunca enxerga (sem GRANT e sem política para site_app).
GRANT SELECT, INSERT, UPDATE ON extracao_ia TO coletor_app;
ALTER TABLE extracao_ia ENABLE ROW LEVEL SECURITY;
CREATE POLICY coletor_app_todas ON extracao_ia TO coletor_app USING (true) WITH CHECK (true);

COMMENT ON TABLE extracao_ia IS 'Respostas da IA por edital (SHA-256 do PDF + versão do esquema); evita gastar tokens de novo';

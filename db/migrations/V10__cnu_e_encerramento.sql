-- Fase 2: destaque do CNU na tela inicial (seção 4.6 do contexto) e data de encerramento informada pela fonte.

SET search_path = concursos;

-- Concurso Nacional Unificado: primeiro na tela inicial, antes dos demais nacionais. Marcado pelo coletor
-- (config/destaques.yml); por definição tem abrangência nacional.
ALTER TABLE concurso
    ADD COLUMN unificado boolean NOT NULL DEFAULT false,
    ADD CONSTRAINT concurso_unificado_ck CHECK (NOT unificado OR abrangencia IS NULL OR abrangencia = 'NACIONAL');

COMMENT ON COLUMN concurso.unificado IS 'Concurso Nacional Unificado (CNU): primeiro na tela inicial';

-- encerrado_em passa a aceitar a data informada por quem encerra (ex.: a última publicação de um concurso que a
-- banca moveu para "realizados"). Sem data informada, continua sendo o momento da mudança. Nunca no futuro.
CREATE OR REPLACE FUNCTION concursos.marcar_encerrado_em() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF NEW.situacao <> 'ENCERRADO' THEN
        NEW.encerrado_em := NULL;
    ELSIF TG_OP = 'INSERT' OR OLD.situacao <> 'ENCERRADO' THEN
        -- Fora de ENCERRADO a coluna é sempre nula (ramo acima), então um valor aqui só pode ter vindo do UPDATE.
        NEW.encerrado_em := least(coalesce(NEW.encerrado_em, now()), now());
    END IF;
    RETURN NEW;
END;
$$;

-- Tela inicial: inscrições abertas, CNU → nacionais → demais, prova mais próxima primeiro.
CREATE INDEX concurso_pub_inicio_ix ON concurso (unificado DESC, (abrangencia = 'NACIONAL') DESC, data_prova)
    WHERE publicado AND situacao = 'INSCRICOES_ABERTAS';

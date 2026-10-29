-- Campos do site (★ da seção 5 e decisões da seção 4.6): slug, local, campos desnormalizados, isenções,
-- resumo, publicação, calendário, disciplinas e redação por cargo. Preenchidos pelo coletor nas fases 2 a 4;
-- até lá os concursos existentes ficam com publicado = false e não aparecem no site.

SET search_path = concursos;

-- Concurso ------------------------------------------------------------------------------------------------------

ALTER TABLE concurso
    -- Trecho da URL /concurso/<slug>/. Estável: uma vez publicado, não muda (link compartilhado e indexado).
    ADD COLUMN slug             text,
    -- Recorte geográfico: NACIONAL (federais/nacionais, exibidos em qualquer recorte), ESTADUAL ou MUNICIPAL.
    ADD COLUMN abrangencia      text,
    -- Local principal (do órgão ou da lotação); em concursos nacionais é só informativo.
    ADD COLUMN uf               char(2) REFERENCES uf (sigla),
    ADD COLUMN municipio_ibge   integer,
    ADD COLUMN total_vagas      integer,
    ADD COLUMN salario_max      numeric(12, 2),
    ADD COLUMN escolaridades    text[]  NOT NULL DEFAULT '{}',
    ADD COLUMN areas            text[]  NOT NULL DEFAULT '{}',
    ADD COLUMN tem_isencao      boolean NOT NULL DEFAULT false,
    ADD COLUMN isencao_inicio   date,
    ADD COLUMN isencao_fim      date,
    ADD COLUMN resumo           text,
    ADD COLUMN resumo_gerado_em timestamptz,
    -- Só o que está publicado vai ao site (garantido também pela política RLS do site_app).
    ADD COLUMN publicado        boolean NOT NULL DEFAULT false,
    -- Quando passou a ENCERRADO: base da retenção (texto do edital apagado após 180 dias) e da saída das páginas.
    ADD COLUMN encerrado_em     timestamptz,
    ADD CONSTRAINT concurso_slug_uk UNIQUE (slug),
    ADD CONSTRAINT concurso_slug_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND length(slug) <= 120),
    ADD CONSTRAINT concurso_abrangencia_ck CHECK (
        abrangencia IS NULL
            OR abrangencia = 'NACIONAL'
            OR (abrangencia = 'ESTADUAL' AND uf IS NOT NULL AND municipio_ibge IS NULL)
            OR (abrangencia = 'MUNICIPAL' AND uf IS NOT NULL AND municipio_ibge IS NOT NULL)),
    -- FK composta: o município informado precisa ser da UF informada. MATCH SIMPLE ignora a FK se a UF for nula,
    -- por isso o CHECK abaixo exige a UF sempre que houver município.
    ADD CONSTRAINT concurso_municipio_fk FOREIGN KEY (uf, municipio_ibge) REFERENCES municipio (uf, codigo_ibge),
    ADD CONSTRAINT concurso_municipio_uf_ck CHECK (municipio_ibge IS NULL OR uf IS NOT NULL),
    ADD CONSTRAINT concurso_total_vagas_ck CHECK (total_vagas >= 0),
    ADD CONSTRAINT concurso_salario_max_ck CHECK (salario_max >= 0),
    ADD CONSTRAINT concurso_escolaridades_ck
        CHECK (escolaridades <@ ARRAY ['FUNDAMENTAL', 'MEDIO', 'TECNICO', 'SUPERIOR']::text[]),
    ADD CONSTRAINT concurso_isencao_periodo_ck CHECK (isencao_fim >= isencao_inicio),
    ADD CONSTRAINT concurso_isencao_coerente_ck
        CHECK (tem_isencao OR (isencao_inicio IS NULL AND isencao_fim IS NULL)),
    -- Publicar exige o mínimo para montar a página: URL, recorte geográfico e resumo.
    ADD CONSTRAINT concurso_publicavel_ck
        CHECK (NOT publicado OR (slug IS NOT NULL AND abrangencia IS NOT NULL AND resumo IS NOT NULL));

-- areas[] é checado contra o catálogo (que pode crescer por migration), o que um CHECK simples não faz.
CREATE FUNCTION concursos.validar_areas_concurso() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    invalidas text[];
BEGIN
    SELECT array_agg(a) INTO invalidas
    FROM unnest(NEW.areas) AS a
    WHERE a IS NULL OR NOT EXISTS (SELECT 1 FROM concursos.area WHERE codigo = a);
    IF invalidas IS NOT NULL THEN
        RAISE EXCEPTION 'áreas fora do catálogo: %', invalidas USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER concurso_areas_validas
    BEFORE INSERT OR UPDATE OF areas ON concurso
    FOR EACH ROW EXECUTE FUNCTION concursos.validar_areas_concurso();

CREATE FUNCTION concursos.marcar_encerrado_em() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF NEW.situacao <> 'ENCERRADO' THEN
        NEW.encerrado_em := NULL;
    ELSIF TG_OP = 'INSERT' THEN
        NEW.encerrado_em := coalesce(NEW.encerrado_em, now());
    ELSIF OLD.situacao <> 'ENCERRADO' THEN
        NEW.encerrado_em := now();
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER concurso_encerrado_em
    BEFORE INSERT OR UPDATE OF situacao, encerrado_em ON concurso
    FOR EACH ROW EXECUTE FUNCTION concursos.marcar_encerrado_em();

-- Concursos que já estavam encerrados: a melhor aproximação disponível é a última atualização (que não deve
-- mudar só por causa desta carga, daí o gatilho de atualizado_em desligado durante o UPDATE).
ALTER TABLE concurso DISABLE TRIGGER concurso_atualizado_em;
UPDATE concurso SET encerrado_em = atualizado_em WHERE situacao = 'ENCERRADO';
ALTER TABLE concurso ENABLE TRIGGER concurso_atualizado_em;

-- Órgão e cargo ---------------------------------------------------------------------------------------------------

ALTER TABLE orgao
    ADD COLUMN municipio_ibge integer,
    ADD CONSTRAINT orgao_municipio_fk FOREIGN KEY (uf, municipio_ibge) REFERENCES municipio (uf, codigo_ibge),
    ADD CONSTRAINT orgao_municipio_uf_ck CHECK (municipio_ibge IS NULL OR uf IS NOT NULL);

ALTER TABLE cargo
    ADD COLUMN area        text REFERENCES area (codigo),
    -- Só os nomes das disciplinas, nunca o conteúdo programático (seção 4.6).
    ADD COLUMN disciplinas text[] NOT NULL DEFAULT '{}',
    -- true/false quando o edital é claro; NULL = não identificado (o site mostra "confira o edital").
    ADD COLUMN tem_redacao boolean,
    ADD CONSTRAINT cargo_disciplinas_ck CHECK (array_position(disciplinas, NULL) IS NULL);

-- UFs já gravadas pelo coletor passam a apontar para o catálogo. NOT VALID + validação tolerante: se houver
-- algum valor antigo fora do catálogo em produção, a migration não falha (as linhas novas já são checadas)
-- e o aviso aparece no log do Flyway para corrigir na fase 2.
ALTER TABLE orgao ADD CONSTRAINT orgao_uf_fk FOREIGN KEY (uf) REFERENCES uf (sigla) NOT VALID;
ALTER TABLE cargo ADD CONSTRAINT cargo_uf_lotacao_fk FOREIGN KEY (uf_lotacao) REFERENCES uf (sigla) NOT VALID;
DO
$$
BEGIN
    ALTER TABLE concursos.orgao VALIDATE CONSTRAINT orgao_uf_fk;
    ALTER TABLE concursos.cargo VALIDATE CONSTRAINT cargo_uf_lotacao_fk;
EXCEPTION
    WHEN foreign_key_violation THEN
        RAISE WARNING 'UF fora do catálogo em orgao/cargo: FKs ficam NOT VALID até a correção (%)', SQLERRM;
END
$$;

-- Isenções previstas no edital e calendário -----------------------------------------------------------------------

CREATE TABLE concurso_isencao (
    concurso_id bigint NOT NULL REFERENCES concurso (id) ON DELETE CASCADE,
    tipo_codigo text   NOT NULL REFERENCES isencao_tipo (codigo),
    observacao  text,
    PRIMARY KEY (concurso_id, tipo_codigo)
);

-- Datas ausentes no edital ficam nulas e o site mostra "a definir".
CREATE TABLE concurso_evento (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    concurso_id bigint   NOT NULL REFERENCES concurso (id) ON DELETE CASCADE,
    ordem       smallint NOT NULL,
    evento      text     NOT NULL,
    inicio      date,
    fim         date,
    CONSTRAINT concurso_evento_ordem_uk UNIQUE (concurso_id, ordem),
    CONSTRAINT concurso_evento_periodo_ck CHECK (fim >= inicio),
    CONSTRAINT concurso_evento_texto_ck CHECK (length(btrim(evento)) > 0)
);

-- Índices das páginas do site (todas leem só publicados) ----------------------------------------------------------

-- Início e listas por situação, ordenadas pelo prazo de inscrição.
CREATE INDEX concurso_pub_situacao_ix ON concurso (situacao, inscricao_fim) WHERE publicado;
-- /estado/<uf>/ e /regiao/ (via uf); nacionais entram em qualquer recorte.
CREATE INDEX concurso_pub_uf_ix ON concurso (uf, situacao) WHERE publicado;
CREATE INDEX concurso_pub_abrangencia_ix ON concurso (abrangencia, situacao) WHERE publicado;
CREATE INDEX concurso_pub_municipio_ix ON concurso (municipio_ibge) WHERE publicado AND municipio_ibge IS NOT NULL;
-- /area/<area>/ e /nivel/<nivel>/: contém (@>) sobre os arrays desnormalizados.
CREATE INDEX concurso_pub_areas_ix ON concurso USING gin (areas) WHERE publicado;
CREATE INDEX concurso_pub_escolaridades_ix ON concurso USING gin (escolaridades) WHERE publicado;
-- Destaque da tela inicial: prazo de pedir isenção mais próximo.
CREATE INDEX concurso_pub_isencao_ix ON concurso (isencao_fim) WHERE publicado AND tem_isencao;
-- Retenção: encerrados antigos.
CREATE INDEX concurso_encerrado_ix ON concurso (encerrado_em) WHERE situacao = 'ENCERRADO';
-- /isencoes/<tipo>/.
CREATE INDEX concurso_isencao_tipo_ix ON concurso_isencao (tipo_codigo);
CREATE INDEX concurso_evento_concurso_ix ON concurso_evento (concurso_id);
CREATE INDEX cargo_area_ix ON cargo (area);
CREATE INDEX orgao_municipio_ix ON orgao (municipio_ibge) WHERE municipio_ibge IS NOT NULL;

COMMENT ON COLUMN concurso.areas IS 'Desnormalizado de cargo.area (sem repetição) para filtros e páginas por área';
COMMENT ON COLUMN concurso.escolaridades IS 'Desnormalizado de cargo.escolaridade para filtros e páginas por nível';
COMMENT ON COLUMN concurso.tem_isencao IS 'O edital prevê ao menos um tipo de isenção (concurso_isencao)';
COMMENT ON TABLE concurso_evento IS 'Calendário do concurso; inicio/fim nulos = "a definir" no site';

-- Modelo de dados base (seção 5 do contexto), herdado do Radar TI sem o que era específico de TI.
-- Os campos marcados com ★ no contexto (slug, áreas, isenções, resumo, campos do site) chegam na fase 1.
-- Status e enumerações como text + CHECK: mais simples de evoluir em migration do que tipos ENUM.

SET search_path = concursos;

CREATE FUNCTION concursos.tocar_atualizado_em() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    NEW.atualizado_em := now();
    RETURN NEW;
END;
$$;

CREATE TABLE banca (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome             text    NOT NULL,
    sigla            text    NOT NULL,
    site             text,
    coleta_permitida boolean NOT NULL DEFAULT false,
    observacao       text,
    CONSTRAINT banca_sigla_uk UNIQUE (sigla)
);

CREATE TABLE orgao (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome      text NOT NULL,
    sigla     text,
    esfera    text,
    uf        char(2),
    municipio text,
    CONSTRAINT orgao_esfera_ck CHECK (esfera IN ('FEDERAL', 'ESTADUAL', 'MUNICIPAL')),
    CONSTRAINT orgao_uf_ck CHECK (uf ~ '^[A-Z]{2}$'),
    -- NULLS NOT DISTINCT: dois órgãos federais sem UF com o mesmo nome também são duplicados.
    CONSTRAINT orgao_uk UNIQUE NULLS NOT DISTINCT (nome, esfera, uf, municipio)
);

CREATE TABLE fonte (
    id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo     text    NOT NULL,
    nome     text    NOT NULL,
    banca_id bigint REFERENCES banca (id),
    ativa    boolean NOT NULL DEFAULT true,
    url_base text,
    CONSTRAINT fonte_tipo_ck CHECK (tipo IN ('BANCA_SITE', 'DOU_INLABS', 'QUERIDO_DIARIO', 'NOTICIA_RSS')),
    CONSTRAINT fonte_nome_uk UNIQUE (nome)
);

CREATE TABLE concurso (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    orgao_id            bigint REFERENCES orgao (id),
    banca_id            bigint REFERENCES banca (id),
    titulo              text        NOT NULL,
    numero_edital       text,
    ano                 smallint,
    situacao            text        NOT NULL DEFAULT 'PREVISTO',
    inscricao_inicio    date,
    inscricao_fim       date,
    data_prova          date,
    taxa_min            numeric(10, 2),
    taxa_max            numeric(10, 2),
    link_oficial        text,
    link_inscricao      text,
    avisos_extracao     jsonb       NOT NULL DEFAULT '[]'::jsonb,
    possivel_duplicado  boolean     NOT NULL DEFAULT false,
    -- Edital (documento) que originou os campos estruturados; muda quando sai um edital consolidado novo.
    edital_documento_id bigint,
    -- De onde vieram os campos estruturados: leitura do edital (EDITAL) ou página da banca (FONTE).
    -- O edital prevalece: dados da fonte só são aplicados enquanto não há edital estruturado.
    origem_estrutura    text,
    criado_em           timestamptz NOT NULL DEFAULT now(),
    atualizado_em       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT concurso_situacao_ck
        CHECK (situacao IN ('PREVISTO', 'INSCRICOES_ABERTAS', 'EM_ANDAMENTO', 'ENCERRADO')),
    CONSTRAINT concurso_ano_ck CHECK (ano BETWEEN 2000 AND 2100),
    CONSTRAINT concurso_inscricao_ck CHECK (inscricao_fim >= inscricao_inicio),
    CONSTRAINT concurso_taxa_ck CHECK (taxa_min >= 0 AND taxa_max >= taxa_min),
    CONSTRAINT concurso_avisos_ck CHECK (jsonb_typeof(avisos_extracao) = 'array'),
    CONSTRAINT concurso_origem_estrutura_ck CHECK (origem_estrutura IN ('EDITAL', 'FONTE')),
    -- Primeira chave da deduplicação: a página oficial do concurso identifica o registro.
    CONSTRAINT concurso_link_oficial_uk UNIQUE (link_oficial)
);

CREATE TRIGGER concurso_atualizado_em
    BEFORE UPDATE ON concurso
    FOR EACH ROW EXECUTE FUNCTION concursos.tocar_atualizado_em();

CREATE TABLE cargo (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    concurso_id      bigint  NOT NULL REFERENCES concurso (id) ON DELETE CASCADE,
    nome             text    NOT NULL,
    especialidade    text,
    escolaridade     text,
    vagas            integer,
    cadastro_reserva boolean NOT NULL DEFAULT false,
    salario          numeric(12, 2),
    uf_lotacao       char(2),
    CONSTRAINT cargo_escolaridade_ck CHECK (escolaridade IN ('SUPERIOR', 'MEDIO', 'TECNICO', 'FUNDAMENTAL')),
    CONSTRAINT cargo_vagas_ck CHECK (vagas >= 0),
    CONSTRAINT cargo_salario_ck CHECK (salario >= 0),
    CONSTRAINT cargo_uf_ck CHECK (uf_lotacao ~ '^[A-Z]{2}$'),
    -- Permite reestruturar um edital sem duplicar o mesmo cargo/especialidade/lotação.
    CONSTRAINT cargo_uk UNIQUE NULLS NOT DISTINCT (concurso_id, nome, especialidade, uf_lotacao)
);

CREATE TABLE documento (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    concurso_id     bigint      NOT NULL REFERENCES concurso (id) ON DELETE CASCADE,
    tipo            text        NOT NULL DEFAULT 'OUTRO',
    titulo          text        NOT NULL,
    url_origem      text        NOT NULL,
    hash_sha256     char(64),
    data_publicacao date,
    texto_extraido  text,
    status_extracao text        NOT NULL DEFAULT 'PENDENTE',
    criado_em       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT documento_tipo_ck CHECK (tipo IN ('EDITAL', 'RETIFICACAO', 'COMUNICADO', 'OUTRO')),
    CONSTRAINT documento_status_ck
        CHECK (status_extracao IN ('PENDENTE', 'BAIXADO', 'OK', 'SEM_TEXTO', 'FALHA', 'IGNORADO')),
    CONSTRAINT documento_hash_ck CHECK (hash_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT documento_url_uk UNIQUE (url_origem)
);

ALTER TABLE concurso
    ADD CONSTRAINT concurso_edital_fk FOREIGN KEY (edital_documento_id) REFERENCES documento (id) ON DELETE SET NULL;

CREATE TABLE sinal_descoberta (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte_id        bigint      NOT NULL REFERENCES fonte (id),
    titulo          text        NOT NULL,
    url             text        NOT NULL,
    data_publicacao date,
    payload         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status          text        NOT NULL DEFAULT 'NOVO',
    concurso_id     bigint REFERENCES concurso (id) ON DELETE SET NULL,
    criado_em       timestamptz NOT NULL DEFAULT now(),
    -- Última vez que a fonte ainda listava o sinal; o payload é atualizado junto (novos arquivos = retificações).
    visto_em        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT sinal_status_ck CHECK (status IN ('NOVO', 'VINCULADO', 'DESCARTADO')),
    -- Reexecutar a descoberta não duplica sinais: a mesma URL vinda da mesma fonte é o mesmo sinal.
    CONSTRAINT sinal_fonte_url_uk UNIQUE (fonte_id, url)
);

-- etapa e fonte opcionais: uma falha antes de chegar a qualquer fonte (configuração, banco) também é registrada.
CREATE TABLE execucao_coleta (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte_id      bigint REFERENCES fonte (id),
    etapa         text        NOT NULL DEFAULT 'DESCOBERTA',
    inicio        timestamptz NOT NULL,
    fim           timestamptz NOT NULL DEFAULT now(),
    status        text        NOT NULL,
    itens_novos   integer     NOT NULL DEFAULT 0,
    mensagem_erro text,
    CONSTRAINT execucao_status_ck CHECK (status IN ('SUCESSO', 'FALHA', 'PARCIAL')),
    CONSTRAINT execucao_etapa_ck CHECK (etapa IN ('GERAL', 'DESCOBERTA', 'VINCULACAO', 'DOCUMENTOS',
                                                  'CLASSIFICACAO', 'ESTRUTURACAO', 'RESUMO', 'MANUTENCAO')),
    CONSTRAINT execucao_periodo_ck CHECK (fim >= inicio)
);

CREATE INDEX sinal_novo_ix ON sinal_descoberta (fonte_id) WHERE status = 'NOVO';
CREATE INDEX sinal_concurso_ix ON sinal_descoberta (concurso_id);
CREATE INDEX sinal_visto_ix ON sinal_descoberta (fonte_id, visto_em);
CREATE INDEX concurso_situacao_ix ON concurso (situacao, criado_em);
CREATE INDEX concurso_orgao_ix ON concurso (orgao_id);
CREATE INDEX concurso_banca_ix ON concurso (banca_id);
CREATE INDEX cargo_concurso_ix ON cargo (concurso_id);
CREATE INDEX documento_concurso_ix ON documento (concurso_id, criado_em);
CREATE INDEX documento_hash_ix ON documento (hash_sha256);
CREATE INDEX documento_pendente_ix ON documento (status_extracao) WHERE status_extracao IN ('PENDENTE', 'BAIXADO');
CREATE INDEX execucao_fim_ix ON execucao_coleta (fim DESC);
CREATE INDEX fonte_banca_ix ON fonte (banca_id);

COMMENT ON TABLE sinal_descoberta IS 'Evidência bruta de um concurso vinda de uma fonte; vários sinais podem apontar para o mesmo concurso';
COMMENT ON TABLE execucao_coleta IS 'Uma linha por fonte/etapa ao fim de cada execução do coletor; ausência de linha no dia = coletor não rodou';
COMMENT ON COLUMN documento.status_extracao IS 'PENDENTE→BAIXADO→OK|SEM_TEXTO|FALHA; IGNORADO = não é PDF, excedeu limites ou não interessa';

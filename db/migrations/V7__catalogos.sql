-- Catálogos fixos do domínio (seções 4.1, 4.2 e 4.4 do contexto), editáveis só por migration.
-- Os textos das páginas de isenção (descrição, documentos, base legal com link oficial) chegam na fase 3 a
-- partir de config/isencoes.yml; aqui ficam códigos e nomes, que já bastam para o modelo e os filtros.

SET search_path = concursos;

CREATE TABLE area (
    codigo text     PRIMARY KEY,
    nome   text     NOT NULL,
    slug   text     NOT NULL,
    ordem  smallint NOT NULL,
    CONSTRAINT area_codigo_ck CHECK (codigo ~ '^[A-Z_]+$'),
    CONSTRAINT area_slug_uk UNIQUE (slug),
    CONSTRAINT area_slug_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

CREATE TABLE escolaridade (
    codigo text     PRIMARY KEY,
    nome   text     NOT NULL,
    slug   text     NOT NULL,
    ordem  smallint NOT NULL,
    CONSTRAINT escolaridade_slug_uk UNIQUE (slug),
    CONSTRAINT escolaridade_slug_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

CREATE TABLE isencao_tipo (
    codigo       text     PRIMARY KEY,
    nome         text     NOT NULL,
    slug         text     NOT NULL,
    ordem        smallint NOT NULL,
    descricao    text,
    base_legal   text,
    link_oficial text,
    CONSTRAINT isencao_tipo_codigo_ck CHECK (codigo ~ '^[A-Z_]+$'),
    CONSTRAINT isencao_tipo_slug_uk UNIQUE (slug),
    CONSTRAINT isencao_tipo_slug_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT isencao_tipo_link_ck CHECK (link_oficial ~ '^https://')
);

INSERT INTO area (codigo, nome, slug, ordem)
VALUES ('ADMINISTRATIVA', 'Administrativa', 'administrativa', 1),
       ('BANCARIA', 'Bancária', 'bancaria', 2),
       ('CONTROLE_FISCAL', 'Controle e fiscal', 'controle-fiscal', 3),
       ('EDUCACAO', 'Educação', 'educacao', 4),
       ('ENGENHARIA_ARQUITETURA', 'Engenharia e arquitetura', 'engenharia-arquitetura', 5),
       ('JURIDICA', 'Jurídica', 'juridica', 6),
       ('LEGISLATIVA', 'Legislativa', 'legislativa', 7),
       ('MEIO_AMBIENTE_AGRARIA', 'Meio ambiente e agrária', 'meio-ambiente-agraria', 8),
       ('POLICIAL_SEGURANCA', 'Policial e segurança', 'policial-seguranca', 9),
       ('SAUDE', 'Saúde', 'saude', 10),
       ('TI', 'Tecnologia da informação', 'ti', 11),
       ('ASSISTENCIA_SOCIAL', 'Assistência social', 'assistencia-social', 12),
       ('COMUNICACAO_ARTES', 'Comunicação e artes', 'comunicacao-artes', 13),
       ('OPERACIONAL', 'Operacional', 'operacional', 14),
       ('OUTRAS', 'Outras', 'outras', 15);

INSERT INTO escolaridade (codigo, nome, slug, ordem)
VALUES ('FUNDAMENTAL', 'Ensino fundamental', 'fundamental', 1),
       ('MEDIO', 'Ensino médio', 'medio', 2),
       ('TECNICO', 'Ensino técnico', 'tecnico', 3),
       ('SUPERIOR', 'Ensino superior', 'superior', 4);

INSERT INTO isencao_tipo (codigo, nome, slug, ordem)
VALUES ('CADUNICO', 'Inscritos no CadÚnico', 'cadunico', 1),
       ('DOADOR_MEDULA', 'Doadores de medula óssea', 'doador-medula', 2),
       ('DOADOR_SANGUE', 'Doadores de sangue', 'doador-sangue', 3),
       ('DOADOR_PLASMA', 'Doadores de plasma', 'doador-plasma', 4),
       ('JURADO', 'Jurados', 'jurado', 5),
       ('MESARIO_ELEITORAL', 'Mesários eleitorais', 'mesario-eleitoral', 6),
       ('PESSOA_COM_DEFICIENCIA', 'Pessoas com deficiência', 'pessoa-com-deficiencia', 7),
       ('VITIMA_VIOLENCIA_DOMESTICA', 'Vítimas de violência doméstica', 'vitima-violencia-domestica', 8),
       ('ESTUDANTE', 'Estudantes', 'estudante', 9),
       ('DESEMPREGADO', 'Desempregados', 'desempregado', 10),
       ('OUTRA', 'Outros casos previstos no edital', 'outra', 11);

-- A escolaridade do cargo passa a apontar para o catálogo (antes era só um CHECK com os mesmos valores).
ALTER TABLE cargo DROP CONSTRAINT cargo_escolaridade_ck;
ALTER TABLE cargo ADD CONSTRAINT cargo_escolaridade_fk FOREIGN KEY (escolaridade) REFERENCES escolaridade (codigo);

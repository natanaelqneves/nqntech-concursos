-- Navegação geográfica Brasil → regiões → estados → municípios (seção 4.6 do contexto).
-- Regiões e UFs ficam aqui; os ~5.570 municípios vêm na V6, gerada a partir da API do IBGE.
-- slug = trecho da URL do site (/regiao/<slug>/, /estado/<slug>/, /municipio/<uf>/<slug>/).

SET search_path = concursos;

CREATE TABLE regiao (
    sigla text     PRIMARY KEY,
    nome  text     NOT NULL,
    slug  text     NOT NULL,
    ordem smallint NOT NULL,
    CONSTRAINT regiao_slug_uk UNIQUE (slug),
    CONSTRAINT regiao_slug_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

CREATE TABLE uf (
    sigla       char(2)  PRIMARY KEY,
    nome        text     NOT NULL,
    codigo_ibge smallint NOT NULL,
    regiao      text     NOT NULL REFERENCES regiao (sigla),
    slug        text     NOT NULL,
    CONSTRAINT uf_codigo_uk UNIQUE (codigo_ibge),
    CONSTRAINT uf_slug_uk UNIQUE (slug),
    CONSTRAINT uf_sigla_ck CHECK (sigla ~ '^[A-Z]{2}$')
);

CREATE TABLE municipio (
    codigo_ibge integer PRIMARY KEY,
    nome        text    NOT NULL,
    uf          char(2) NOT NULL REFERENCES uf (sigla),
    slug        text    NOT NULL,
    -- Nomes de município não se repetem dentro de uma UF, então (uf, slug) identifica a página.
    CONSTRAINT municipio_uf_slug_uk UNIQUE (uf, slug),
    -- Alvo da FK composta de concurso/orgao: garante que o município pertence à UF informada.
    CONSTRAINT municipio_uf_codigo_uk UNIQUE (uf, codigo_ibge),
    CONSTRAINT municipio_codigo_ck CHECK (codigo_ibge BETWEEN 1000000 AND 9999999),
    CONSTRAINT municipio_slug_ck CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

-- Os dois primeiros dígitos do código IBGE do município são o código da UF.
CREATE FUNCTION concursos.validar_municipio_uf() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF NEW.codigo_ibge / 100000 <> (SELECT codigo_ibge FROM concursos.uf WHERE sigla = NEW.uf) THEN
        RAISE EXCEPTION 'município % não pertence à UF %', NEW.codigo_ibge, NEW.uf USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER municipio_uf_coerente
    BEFORE INSERT OR UPDATE ON municipio
    FOR EACH ROW EXECUTE FUNCTION concursos.validar_municipio_uf();

INSERT INTO regiao (sigla, nome, slug, ordem)
VALUES ('N', 'Norte', 'norte', 1),
       ('NE', 'Nordeste', 'nordeste', 2),
       ('CO', 'Centro-Oeste', 'centro-oeste', 3),
       ('SE', 'Sudeste', 'sudeste', 4),
       ('S', 'Sul', 'sul', 5);

INSERT INTO uf (sigla, nome, codigo_ibge, regiao, slug)
VALUES ('RO', 'Rondônia', 11, 'N', 'ro'),
       ('AC', 'Acre', 12, 'N', 'ac'),
       ('AM', 'Amazonas', 13, 'N', 'am'),
       ('RR', 'Roraima', 14, 'N', 'rr'),
       ('PA', 'Pará', 15, 'N', 'pa'),
       ('AP', 'Amapá', 16, 'N', 'ap'),
       ('TO', 'Tocantins', 17, 'N', 'to'),
       ('MA', 'Maranhão', 21, 'NE', 'ma'),
       ('PI', 'Piauí', 22, 'NE', 'pi'),
       ('CE', 'Ceará', 23, 'NE', 'ce'),
       ('RN', 'Rio Grande do Norte', 24, 'NE', 'rn'),
       ('PB', 'Paraíba', 25, 'NE', 'pb'),
       ('PE', 'Pernambuco', 26, 'NE', 'pe'),
       ('AL', 'Alagoas', 27, 'NE', 'al'),
       ('SE', 'Sergipe', 28, 'NE', 'se'),
       ('BA', 'Bahia', 29, 'NE', 'ba'),
       ('MG', 'Minas Gerais', 31, 'SE', 'mg'),
       ('ES', 'Espírito Santo', 32, 'SE', 'es'),
       ('RJ', 'Rio de Janeiro', 33, 'SE', 'rj'),
       ('SP', 'São Paulo', 35, 'SE', 'sp'),
       ('PR', 'Paraná', 41, 'S', 'pr'),
       ('SC', 'Santa Catarina', 42, 'S', 'sc'),
       ('RS', 'Rio Grande do Sul', 43, 'S', 'rs'),
       ('MS', 'Mato Grosso do Sul', 50, 'CO', 'ms'),
       ('MT', 'Mato Grosso', 51, 'CO', 'mt'),
       ('GO', 'Goiás', 52, 'CO', 'go'),
       ('DF', 'Distrito Federal', 53, 'CO', 'df');

CREATE INDEX uf_regiao_ix ON uf (regiao);

COMMENT ON TABLE municipio IS 'Municípios do IBGE; carga na V6 (gerada por scripts/captura/gerar_municipios_ibge.py)';

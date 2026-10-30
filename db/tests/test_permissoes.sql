-- Prova automatizada das regras de segurança do banco. Roda na CI (e localmente) depois das migrations + seeds:
--   psql -v ON_ERROR_STOP=1 -f db/tests/test_permissoes.sql
-- Precisa de um usuário que possa fazer SET ROLE para os papéis da aplicação (o admin local/CI).
-- Qualquer regra violada levanta exceção e o psql termina com código != 0.

\set QUIET on
SET client_min_messages = notice;
-- Resultados das chamadas não interessam; as mensagens (NOTICE/ERROR) vão para o stderr.
\o /dev/null

-- Funções de apoio temporárias (somem ao fim da sessão).
CREATE FUNCTION pg_temp.deve_negar(papel text, sql text) RETURNS void
    LANGUAGE plpgsql AS
$$
BEGIN
    EXECUTE format('SET LOCAL ROLE %I', papel);
    BEGIN
        EXECUTE sql;
    EXCEPTION
        WHEN insufficient_privilege THEN
            RESET ROLE;
            RAISE NOTICE 'ok   % negado: %', papel, sql;
            RETURN;
    END;
    RESET ROLE;
    RAISE EXCEPTION 'FALHA: % deveria ser negado em: %', papel, sql;
END;
$$;

CREATE FUNCTION pg_temp.deve_permitir(papel text, sql text) RETURNS void
    LANGUAGE plpgsql AS
$$
BEGIN
    EXECUTE format('SET LOCAL ROLE %I', papel);
    EXECUTE sql;
    RESET ROLE;
    RAISE NOTICE 'ok   % permitido: %', papel, sql;
END;
$$;

CREATE FUNCTION pg_temp.contar_como(papel text, tabela text) RETURNS bigint
    LANGUAGE plpgsql AS
$$
DECLARE
    total bigint;
BEGIN
    EXECUTE format('SET LOCAL ROLE %I', papel);
    EXECUTE format('SELECT count(*) FROM concursos.%I', tabela) INTO total;
    RESET ROLE;
    RETURN total;
END;
$$;

CREATE FUNCTION pg_temp.deve_falhar(sql text, estado text) RETURNS void
    LANGUAGE plpgsql AS
$$
BEGIN
    EXECUTE sql;
    RAISE EXCEPTION 'FALHA: deveria falhar com % em: %', estado, sql;
EXCEPTION
    WHEN OTHERS THEN
        IF SQLSTATE = 'P0001' AND SQLERRM LIKE 'FALHA:%' THEN
            RAISE;
        END IF;
        IF SQLSTATE <> estado THEN
            RAISE EXCEPTION 'FALHA: esperado % mas veio % (%) em: %', estado, SQLSTATE, SQLERRM, sql;
        END IF;
        RAISE NOTICE 'ok   bloqueado (%): %', estado, left(sql, 110);
END;
$$;

BEGIN;

-- 1. Seeds e dados de referência carregados.
DO
$$
DECLARE
    n_conc int;
    n_org  int;
    n_ufs  int;
BEGIN
    SELECT count(*) INTO n_conc FROM concursos.concurso WHERE link_oficial LIKE 'https://conhecimento.fgv.br/concursos/exemplo-%';
    SELECT count(*), count(DISTINCT uf) INTO n_org, n_ufs FROM concursos.orgao WHERE nome LIKE '[EXEMPLO]%';
    IF n_conc <> 9 OR n_org <> 7 THEN
        RAISE EXCEPTION 'FALHA: seeds incompletos (concursos=%, orgaos=%)', n_conc, n_org;
    END IF;
    IF (SELECT count(*) FROM concursos.banca) < 3
       OR (SELECT count(*) FROM concursos.fonte WHERE nome IN ('fgv', 'ibam', 'ibade')) <> 3 THEN
        RAISE EXCEPTION 'FALHA: dados de referência ausentes';
    END IF;
    RAISE NOTICE 'ok   seeds: % concursos, % órgãos em % UFs', n_conc, n_org, n_ufs;
END
$$;

-- 2. Site: só lê o que é público.
SELECT pg_temp.deve_permitir('site_app',
    'SELECT count(*) FROM concursos.concurso JOIN concursos.cargo ON cargo.concurso_id = concurso.id');
SELECT pg_temp.deve_permitir('site_app', 'SELECT b.sigla, o.nome, o.uf FROM concursos.banca b, concursos.orgao o');
SELECT pg_temp.deve_permitir('site_app', 'SELECT id, tipo, titulo, url_origem FROM concursos.documento');
SELECT pg_temp.deve_permitir('site_app', 'SELECT max(fim) FROM concursos.execucao_coleta');
SELECT pg_temp.deve_negar('site_app', 'SELECT texto_extraido FROM concursos.documento');
SELECT pg_temp.deve_negar('site_app', 'SELECT * FROM concursos.documento');
SELECT pg_temp.deve_negar('site_app', 'SELECT payload FROM concursos.sinal_descoberta');
SELECT pg_temp.deve_negar('site_app', 'UPDATE concursos.concurso SET titulo = titulo');
SELECT pg_temp.deve_negar('site_app', $q$INSERT INTO concursos.orgao (nome) VALUES ('x')$q$);
SELECT pg_temp.deve_negar('site_app', 'DELETE FROM concursos.cargo');
SELECT pg_temp.deve_negar('site_app', 'SELECT * FROM concursos.flyway_schema_history');
SELECT pg_temp.deve_negar('site_app', 'CREATE TABLE concursos.invasora (id int)');
DO
$$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_db_role_setting s JOIN pg_roles r ON r.oid = s.setrole
                   WHERE r.rolname = 'site_app' AND 'default_transaction_read_only=on' = ANY (s.setconfig)) THEN
        RAISE EXCEPTION 'FALHA: site_app não nasce em transação somente leitura';
    END IF;
    RAISE NOTICE 'ok   site_app: sessão somente leitura por padrão';
END
$$;

-- 3. Coletor grava a coleta, mas não apaga concursos nem mexe no cadastro de bancas.
SELECT pg_temp.deve_negar('coletor_app', 'DELETE FROM concursos.concurso');
SELECT pg_temp.deve_negar('coletor_app', $q$UPDATE concursos.banca SET observacao = 'x'$q$);
SELECT pg_temp.deve_negar('coletor_app', $q$UPDATE concursos.fonte SET ativa = true$q$);
SELECT pg_temp.deve_negar('coletor_app', 'DELETE FROM concursos.execucao_coleta');
SELECT pg_temp.deve_negar('coletor_app', 'CREATE TABLE concursos.invasora (id int)');
SELECT pg_temp.deve_negar('coletor_app', 'SELECT * FROM concursos.flyway_schema_history');
SELECT pg_temp.deve_permitir('coletor_app',
    $q$INSERT INTO concursos.execucao_coleta (etapa, inicio, status) VALUES ('GERAL', now(), 'SUCESSO')$q$);
SELECT pg_temp.deve_permitir('coletor_app', $q$UPDATE concursos.concurso SET possivel_duplicado = false
                                               WHERE link_oficial LIKE 'https://conhecimento.fgv.br/concursos/exemplo-%'$q$);
SELECT pg_temp.deve_permitir('coletor_app',
    $q$INSERT INTO concursos.orgao (nome, esfera, uf) VALUES ('[EXEMPLO] Teste', 'ESTADUAL', 'PB')$q$);

-- 4. Unicidade: a mesma página oficial nunca vira dois concursos.
DO
$$
BEGIN
    INSERT INTO concursos.concurso (titulo, link_oficial)
    VALUES ('duplicado', 'https://conhecimento.fgv.br/concursos/exemplo-tjpb');
    RAISE EXCEPTION 'FALHA: concurso duplicado pelo link oficial';
EXCEPTION
    WHEN unique_violation THEN RAISE NOTICE 'ok   concurso: link_oficial duplicado bloqueado';
END
$$;

-- 5. RLS: um papel qualquer com GRANT de leitura (como o de uma API HTTP automática) não vê nenhuma linha.
DO
$$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'api_anonima_teste') THEN
        CREATE ROLE api_anonima_teste NOLOGIN;
    END IF;
END
$$;
GRANT USAGE ON SCHEMA concursos TO api_anonima_teste;
GRANT SELECT ON concursos.concurso TO api_anonima_teste;
DO
$$
DECLARE
    visiveis bigint := pg_temp.contar_como('api_anonima_teste', 'concurso');
    sem_rls  text;
BEGIN
    IF visiveis <> 0 THEN
        RAISE EXCEPTION 'FALHA: RLS deixou % linhas visíveis para um papel sem política', visiveis;
    END IF;
    SELECT string_agg(c.relname, ', ') INTO sem_rls
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'concursos' AND c.relkind = 'r' AND c.relname <> 'flyway_schema_history' AND NOT c.relrowsecurity;
    IF sem_rls IS NOT NULL THEN
        RAISE EXCEPTION 'FALHA: tabelas sem RLS: %', sem_rls;
    END IF;
    IF pg_temp.contar_como('site_app', 'concurso') = 0 OR pg_temp.contar_como('coletor_app', 'concurso') = 0 THEN
        RAISE EXCEPTION 'FALHA: RLS bloqueou um papel da aplicação';
    END IF;
    RAISE NOTICE 'ok   RLS ativo em todas as tabelas; papel sem política vê 0 linhas';
END
$$;

-- 6. Nenhum acesso pelo PUBLIC ao schema.
DO
$$
BEGIN
    IF has_schema_privilege('public', 'concursos', 'USAGE') THEN
        RAISE EXCEPTION 'FALHA: PUBLIC tem USAGE no schema concursos';
    END IF;
    RAISE NOTICE 'ok   schema concursos fechado para PUBLIC';
END
$$;


-- 7. Catálogos e geografia carregados (seções 4.1, 4.2, 4.4 e 4.6).
DO
$$
DECLARE
    n_mun     int;
    uf_vazias text;
BEGIN
    IF (SELECT count(*) FROM concursos.area) <> 15 OR (SELECT count(*) FROM concursos.escolaridade) <> 4
       OR (SELECT count(*) FROM concursos.isencao_tipo) <> 11 THEN
        RAISE EXCEPTION 'FALHA: catálogos de área/escolaridade/isenção incompletos';
    END IF;
    IF (SELECT count(*) FROM concursos.regiao) <> 5 OR (SELECT count(*) FROM concursos.uf) <> 27 THEN
        RAISE EXCEPTION 'FALHA: regiões/UFs incompletas';
    END IF;
    SELECT count(*) INTO n_mun FROM concursos.municipio;
    SELECT string_agg(u.sigla, ', ') INTO uf_vazias
    FROM concursos.uf u WHERE NOT EXISTS (SELECT 1 FROM concursos.municipio m WHERE m.uf = u.sigla);
    IF n_mun < 5560 OR uf_vazias IS NOT NULL THEN
        RAISE EXCEPTION 'FALHA: municípios do IBGE incompletos (%; UFs sem município: %)', n_mun, uf_vazias;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM concursos.municipio WHERE codigo_ibge = 2507507 AND uf = 'PB' AND slug = 'joao-pessoa')
       OR (SELECT count(*) FROM concursos.municipio WHERE uf = 'DF') <> 1 THEN
        RAISE EXCEPTION 'FALHA: municípios de referência ausentes ou errados';
    END IF;
    IF EXISTS (SELECT 1 FROM concursos.municipio m JOIN concursos.uf u ON u.sigla = m.uf
               WHERE m.codigo_ibge / 100000 <> u.codigo_ibge) THEN
        RAISE EXCEPTION 'FALHA: município com código IBGE de outra UF';
    END IF;
    RAISE NOTICE 'ok   catálogos: 15 áreas, 4 níveis, 11 isenções, 5 regiões, 27 UFs, % municípios', n_mun;
END
$$;

-- 8. Site só enxerga concursos publicados e o que pertence a eles (RLS), mesmo sem WHERE publicado.
DO
$$
DECLARE
    publicados int;
    rascunho   bigint;
BEGIN
    SELECT count(*) INTO publicados FROM concursos.concurso
    WHERE publicado AND link_oficial LIKE 'https://conhecimento.fgv.br/concursos/exemplo-%';
    SELECT id INTO rascunho FROM concursos.concurso
    WHERE link_oficial = 'https://conhecimento.fgv.br/concursos/exemplo-rascunho';
    IF publicados <> 8 OR rascunho IS NULL THEN
        RAISE EXCEPTION 'FALHA: seeds de publicação inesperados (publicados=%)', publicados;
    END IF;
    IF pg_temp.contar_como('site_app', 'concurso') <> (SELECT count(*) FROM concursos.concurso WHERE publicado) THEN
        RAISE EXCEPTION 'FALHA: site_app enxerga concurso não publicado';
    END IF;
    SET LOCAL ROLE site_app;
    IF EXISTS (SELECT 1 FROM concursos.concurso WHERE id = rascunho)
       OR EXISTS (SELECT 1 FROM concursos.cargo WHERE concurso_id = rascunho)
       OR EXISTS (SELECT 1 FROM concursos.documento WHERE concurso_id = rascunho)
       OR EXISTS (SELECT 1 FROM concursos.concurso_isencao WHERE concurso_id = rascunho)
       OR EXISTS (SELECT 1 FROM concursos.concurso_evento WHERE concurso_id = rascunho) THEN
        RESET ROLE;
        RAISE EXCEPTION 'FALHA: site_app enxerga dados de concurso não publicado';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM concursos.concurso_isencao) OR NOT EXISTS (SELECT 1 FROM concursos.concurso_evento)
       OR NOT EXISTS (SELECT 1 FROM concursos.municipio) OR NOT EXISTS (SELECT 1 FROM concursos.isencao_tipo) THEN
        RESET ROLE;
        RAISE EXCEPTION 'FALHA: site_app não enxerga isenções, calendário ou catálogos';
    END IF;
    RESET ROLE;
    RAISE NOTICE 'ok   site_app: só concursos publicados (rascunho invisível em todas as tabelas filhas)';
END
$$;

-- 9. Lista branca do site_app: qualquer tabela nova (ex.: assinantes na fase 7) nasce invisível para o site.
DO
$$
DECLARE
    publicas  text[] := ARRAY ['banca', 'orgao', 'fonte', 'concurso', 'cargo', 'execucao_coleta', 'regiao', 'uf',
                               'municipio', 'area', 'escolaridade', 'isencao_tipo', 'concurso_isencao',
                               'concurso_evento'];
    indevidas text;
    escrita   text;
BEGIN
    SELECT string_agg(c.relname, ', ') INTO indevidas
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'concursos' AND c.relkind IN ('r', 'v', 'm')
      AND c.relname <> ALL (publicas) AND c.relname <> 'documento'
      AND has_any_column_privilege('site_app', c.oid, 'SELECT');
    IF indevidas IS NOT NULL THEN
        RAISE EXCEPTION 'FALHA: site_app lê tabelas fora da lista branca: %', indevidas;
    END IF;
    SELECT string_agg(c.relname, ', ') INTO escrita
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'concursos' AND c.relkind = 'r'
      AND (has_table_privilege('site_app', c.oid, 'INSERT') OR has_table_privilege('site_app', c.oid, 'UPDATE')
           OR has_table_privilege('site_app', c.oid, 'DELETE') OR has_table_privilege('site_app', c.oid, 'TRUNCATE')
           OR has_any_column_privilege('site_app', c.oid, 'INSERT')
           OR has_any_column_privilege('site_app', c.oid, 'UPDATE'));
    IF escrita IS NOT NULL THEN
        RAISE EXCEPTION 'FALHA: site_app pode escrever em: %', escrita;
    END IF;
    RAISE NOTICE 'ok   site_app: leitura só da lista branca pública, nenhuma escrita';
END
$$;
SELECT pg_temp.deve_negar('site_app', $q$INSERT INTO concursos.concurso_isencao VALUES (1, 'CADUNICO', NULL)$q$);
SELECT pg_temp.deve_negar('site_app', $q$UPDATE concursos.area SET nome = 'x'$q$);

-- 10. Coletor grava isenções e calendário, mas não mexe nos catálogos.
SELECT pg_temp.deve_permitir('coletor_app', $q$INSERT INTO concursos.concurso_evento (concurso_id, ordem, evento)
    SELECT id, 99, 'Resultado' FROM concursos.concurso WHERE link_oficial LIKE '%exemplo-inss'$q$);
SELECT pg_temp.deve_permitir('coletor_app', $q$DELETE FROM concursos.concurso_isencao WHERE concurso_id IN
    (SELECT id FROM concursos.concurso WHERE link_oficial LIKE '%exemplo-inss')$q$);
SELECT pg_temp.deve_permitir('coletor_app', $q$UPDATE concursos.cargo SET area = 'TI', tem_redacao = true
    WHERE concurso_id IN (SELECT id FROM concursos.concurso WHERE link_oficial LIKE '%exemplo-rascunho')$q$);
SELECT pg_temp.deve_negar('coletor_app', $q$INSERT INTO concursos.area VALUES ('NOVA', 'Nova', 'nova', 99)$q$);
SELECT pg_temp.deve_negar('coletor_app', $q$UPDATE concursos.isencao_tipo SET nome = 'x'$q$);
SELECT pg_temp.deve_negar('coletor_app', 'DELETE FROM concursos.municipio');

-- 11. Integridade dos campos do site.
SELECT pg_temp.deve_falhar($q$UPDATE concursos.concurso SET areas = '{TI,INEXISTENTE}'
    WHERE link_oficial LIKE '%exemplo-tjpb'$q$, '23514');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.concurso SET escolaridades = '{DOUTORADO}'
    WHERE link_oficial LIKE '%exemplo-tjpb'$q$, '23514');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.concurso SET publicado = true
    WHERE link_oficial LIKE '%exemplo-rascunho'$q$, '23514');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.concurso SET slug = 'TJPB 2026'
    WHERE link_oficial LIKE '%exemplo-tjpb'$q$, '23514');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.concurso SET slug = 'exemplo-inss'
    WHERE link_oficial LIKE '%exemplo-tjpb'$q$, '23505');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.concurso SET uf = 'SP'
    WHERE link_oficial LIKE '%exemplo-pmjp-saude'$q$, '23503');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.concurso SET uf = NULL
    WHERE link_oficial LIKE '%exemplo-pmjp-saude'$q$, '23514');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.concurso SET municipio_ibge = NULL
    WHERE link_oficial LIKE '%exemplo-pmjp-saude'$q$, '23514');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.concurso SET isencao_fim = isencao_inicio - 1
    WHERE link_oficial LIKE '%exemplo-tjpb'$q$, '23514');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.concurso SET tem_isencao = false
    WHERE link_oficial LIKE '%exemplo-tjpb'$q$, '23514');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.cargo SET area = 'NAO_EXISTE'$q$, '23503');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.cargo SET escolaridade = 'DOUTORADO'$q$, '23503');
SELECT pg_temp.deve_falhar($q$UPDATE concursos.cargo SET disciplinas = ARRAY['Português', NULL]$q$, '23514');
SELECT pg_temp.deve_falhar($q$INSERT INTO concursos.concurso_isencao
    SELECT id, 'NAO_EXISTE', NULL FROM concursos.concurso WHERE link_oficial LIKE '%exemplo-tjpb'$q$, '23503');
SELECT pg_temp.deve_falhar($q$INSERT INTO concursos.concurso_evento (concurso_id, ordem, evento, inicio, fim)
    SELECT id, 50, 'X', current_date, current_date - 1 FROM concursos.concurso
    WHERE link_oficial LIKE '%exemplo-tjpb'$q$, '23514');
SELECT pg_temp.deve_falhar($q$INSERT INTO concursos.municipio VALUES (2599999, 'Fora', 'SP', 'fora')$q$, '23514');
-- CNU é sempre nacional.
SELECT pg_temp.deve_falhar($q$UPDATE concursos.concurso SET unificado = true
    WHERE link_oficial LIKE '%exemplo-tjpb'$q$, '23514');
SELECT pg_temp.deve_permitir('coletor_app', $q$UPDATE concursos.concurso SET unificado = false
    WHERE link_oficial LIKE '%exemplo-cnu'$q$);

-- 12. encerrado_em acompanha a situação (base da retenção).
DO
$$
DECLARE
    marcado timestamptz;
    antigo  timestamptz;
BEGIN
    UPDATE concursos.concurso SET situacao = 'ENCERRADO'
    WHERE link_oficial LIKE '%exemplo-sefazal' RETURNING encerrado_em INTO marcado;
    UPDATE concursos.concurso SET titulo = titulo || ' '
    WHERE link_oficial LIKE '%exemplo-pmf-educacao' RETURNING encerrado_em INTO antigo;
    IF marcado IS NULL OR antigo > now() - interval '169 days' THEN
        RAISE EXCEPTION 'FALHA: encerrado_em não marcado ou sobrescrito (%, %)', marcado, antigo;
    END IF;
    UPDATE concursos.concurso SET situacao = 'EM_ANDAMENTO'
    WHERE link_oficial LIKE '%exemplo-sefazal' RETURNING encerrado_em INTO marcado;
    IF marcado IS NOT NULL THEN
        RAISE EXCEPTION 'FALHA: encerrado_em não foi limpo ao reabrir';
    END IF;
    -- Data informada por quem encerra (última publicação da banca) é respeitada; data futura vira "agora".
    UPDATE concursos.concurso SET situacao = 'ENCERRADO', encerrado_em = now() - interval '30 days'
    WHERE link_oficial LIKE '%exemplo-sefazal' RETURNING encerrado_em INTO marcado;
    IF marcado IS NULL OR marcado > now() - interval '29 days' THEN
        RAISE EXCEPTION 'FALHA: encerrado_em informado foi ignorado (%)', marcado;
    END IF;
    UPDATE concursos.concurso SET situacao = 'EM_ANDAMENTO'
    WHERE link_oficial LIKE '%exemplo-sefazal';
    UPDATE concursos.concurso SET situacao = 'ENCERRADO', encerrado_em = now() + interval '10 days'
    WHERE link_oficial LIKE '%exemplo-sefazal' RETURNING encerrado_em INTO marcado;
    IF marcado > now() THEN
        RAISE EXCEPTION 'FALHA: encerrado_em no futuro (%)', marcado;
    END IF;
    RAISE NOTICE 'ok   encerrado_em: marcado ao encerrar, preservado, limpo ao reabrir e com data informada';
END
$$;

-- Tudo (inclusive o papel de teste) é desfeito: o teste não deixa rastro no banco.
ROLLBACK;

\o
\echo 'TODOS OS TESTES DE PERMISSÃO PASSARAM'

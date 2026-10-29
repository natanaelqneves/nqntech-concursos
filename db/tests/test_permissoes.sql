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
    IF n_conc <> 7 OR n_org <> 6 THEN
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

-- Tudo (inclusive o papel de teste) é desfeito: o teste não deixa rastro no banco.
ROLLBACK;

\o
\echo 'TODOS OS TESTES DE PERMISSÃO PASSARAM'

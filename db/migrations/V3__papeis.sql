-- Papéis das aplicações com privilégio mínimo (seção 10 do contexto).
-- As senhas chegam como placeholders do Flyway (${coletor_senha}, ${site_senha}) vindos de variáveis de ambiente:
-- .env no Docker local, GitHub Secrets no migrar.yml. Nunca ficam no repositório.
-- No Neon, papéis criados por SQL exigem senha com pelo menos 60 bits de entropia.
-- alertas_app e api_app nascem na fase 7, junto com as tabelas de assinantes.

DO
$$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'coletor_app') THEN
        EXECUTE format('CREATE ROLE coletor_app LOGIN PASSWORD %L', '${coletor_senha}');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'site_app') THEN
        EXECUTE format('CREATE ROLE site_app LOGIN PASSWORD %L', '${site_senha}');
    END IF;
END
$$;

-- CREATE ROLE já nasce sem SUPERUSER/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS; só ajustamos o que difere.
-- (Alterar esses atributos exigiria privilégio que o dono do banco no Neon não tem.)
ALTER ROLE coletor_app NOINHERIT CONNECTION LIMIT 5;
ALTER ROLE site_app NOINHERIT CONNECTION LIMIT 5;

-- Defaults por papel: as aplicações não precisam qualificar o schema e nenhuma consulta trava a execução diária.
ALTER ROLE coletor_app SET search_path = concursos;
ALTER ROLE coletor_app SET statement_timeout = '120s';
ALTER ROLE coletor_app SET idle_in_transaction_session_timeout = '300s';
-- O gerador do site só lê: além do GRANT, a sessão nasce somente leitura.
ALTER ROLE site_app SET search_path = concursos;
ALTER ROLE site_app SET statement_timeout = '60s';
ALTER ROLE site_app SET idle_in_transaction_session_timeout = '120s';
ALTER ROLE site_app SET default_transaction_read_only = on;

GRANT USAGE ON SCHEMA concursos TO coletor_app, site_app;
GRANT USAGE ON SCHEMA extensions TO coletor_app, site_app;

-- Coletor: lê o cadastro e grava tudo da coleta.
-- orgao também é gravado pelo coletor: o órgão só é conhecido ao estruturar o edital.
GRANT SELECT ON concursos.banca, concursos.fonte TO coletor_app;
GRANT SELECT, INSERT, UPDATE ON concursos.orgao TO coletor_app;
GRANT SELECT, INSERT, UPDATE ON concursos.sinal_descoberta, concursos.concurso, concursos.documento TO coletor_app;
-- DELETE em cargo: reestruturar um edital substitui o quadro de cargos inteiro.
GRANT SELECT, INSERT, UPDATE, DELETE ON concursos.cargo TO coletor_app;
GRANT SELECT, INSERT ON concursos.execucao_coleta TO coletor_app;

-- Site: só leitura do que vai ao público. Não lê sinais (payload bruto da fonte) nem o texto dos editais;
-- de documento, só os metadados para os links oficiais. execucao_coleta alimenta "última atualização" e a
-- cobertura por fonte em /sobre/ (sem dado pessoal).
GRANT SELECT ON concursos.banca, concursos.orgao, concursos.fonte, concursos.concurso, concursos.cargo,
    concursos.execucao_coleta TO site_app;
GRANT SELECT (id, concurso_id, tipo, titulo, url_origem, data_publicacao, criado_em) ON concursos.documento TO site_app;

-- RLS em todas as tabelas como segunda barreira: qualquer papel sem política explícita não enxerga nenhuma linha.
-- As políticas só liberam LINHAS; o que cada papel pode fazer continua limitado pelos GRANTs acima.
-- Fase 1: a política do site_app passa a filtrar concurso.publicado.
DO
$$
DECLARE
    tabela text;
BEGIN
    FOR tabela IN
        SELECT c.relname
        FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'concursos'
          AND c.relkind = 'r'
          AND c.relname <> 'flyway_schema_history'
        LOOP
            EXECUTE format('ALTER TABLE concursos.%I ENABLE ROW LEVEL SECURITY', tabela);
            EXECUTE format('CREATE POLICY coletor_app_todas ON concursos.%I TO coletor_app USING (true) WITH CHECK (true)',
                           tabela);
            IF tabela IN ('banca', 'orgao', 'fonte', 'concurso', 'cargo', 'documento', 'execucao_coleta') THEN
                EXECUTE format('CREATE POLICY site_app_leitura ON concursos.%I FOR SELECT TO site_app USING (true)',
                               tabela);
            END IF;
        END LOOP;
END
$$;

-- O histórico do Flyway não é dado da aplicação.
REVOKE ALL ON concursos.flyway_schema_history FROM coletor_app, site_app;

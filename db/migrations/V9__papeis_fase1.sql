-- Privilégios e RLS das tabelas da fase 1 (seção 10 do contexto). Mesmo princípio da V3: GRANT define o que
-- cada papel pode fazer; RLS define quais linhas ele enxerga. Tabela nova sem política = invisível.

SET search_path = concursos;

-- Catálogos e geografia: leitura para os dois papéis; ninguém da aplicação altera (só migration).
GRANT SELECT ON regiao, uf, municipio, area, escolaridade, isencao_tipo TO coletor_app, site_app;

-- Coletor: grava isenções e calendário. DELETE porque reestruturar um edital substitui o conjunto inteiro,
-- como já acontece com cargo.
GRANT SELECT, INSERT, UPDATE, DELETE ON concurso_isencao, concurso_evento TO coletor_app;

-- Site: só leitura.
GRANT SELECT ON concurso_isencao, concurso_evento TO site_app;

DO
$$
DECLARE
    tabela text;
BEGIN
    FOREACH tabela IN ARRAY ARRAY ['regiao', 'uf', 'municipio', 'area', 'escolaridade', 'isencao_tipo',
                                   'concurso_isencao', 'concurso_evento']
        LOOP
            EXECUTE format('ALTER TABLE concursos.%I ENABLE ROW LEVEL SECURITY', tabela);
            EXECUTE format('CREATE POLICY coletor_app_todas ON concursos.%I TO coletor_app USING (true) WITH CHECK (true)',
                           tabela);
        END LOOP;
    FOREACH tabela IN ARRAY ARRAY ['regiao', 'uf', 'municipio', 'area', 'escolaridade', 'isencao_tipo']
        LOOP
            EXECUTE format('CREATE POLICY site_app_leitura ON concursos.%I FOR SELECT TO site_app USING (true)',
                           tabela);
        END LOOP;
END
$$;

-- O site só enxerga concursos publicados e o que pertence a eles. A subconsulta em concurso também passa pela
-- RLS do site_app, então o filtro vale mesmo se alguém esquecer o WHERE publicado no gerador.
DROP POLICY site_app_leitura ON concurso;
CREATE POLICY site_app_publicados ON concurso FOR SELECT TO site_app USING (publicado);

DROP POLICY site_app_leitura ON cargo;
DROP POLICY site_app_leitura ON documento;
CREATE POLICY site_app_publicados ON cargo FOR SELECT TO site_app
    USING (EXISTS (SELECT 1 FROM concurso c WHERE c.id = cargo.concurso_id AND c.publicado));
CREATE POLICY site_app_publicados ON documento FOR SELECT TO site_app
    USING (EXISTS (SELECT 1 FROM concurso c WHERE c.id = documento.concurso_id AND c.publicado));
CREATE POLICY site_app_publicados ON concurso_isencao FOR SELECT TO site_app
    USING (EXISTS (SELECT 1 FROM concurso c WHERE c.id = concurso_isencao.concurso_id AND c.publicado));
CREATE POLICY site_app_publicados ON concurso_evento FOR SELECT TO site_app
    USING (EXISTS (SELECT 1 FROM concurso c WHERE c.id = concurso_evento.concurso_id AND c.publicado));

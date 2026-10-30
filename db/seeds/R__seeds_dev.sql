-- Dados fictícios SÓ para desenvolvimento e testes (nunca carregados em produção: a pasta db/seeds só entra
-- no Flyway do docker-compose e da CI). Repetível: apaga e recria tudo que tem o prefixo "exemplo-".
-- Datas relativas a current_date para os concursos continuarem "com inscrições abertas" em qualquer dia.
-- Variedade proposital: áreas, níveis, abrangência (nacional/estadual/municipal), UFs, com e sem isenção,
-- previsto, em andamento, encerrado e um concurso ainda não publicado (o site não pode enxergá-lo).

DELETE FROM concursos.sinal_descoberta WHERE url LIKE 'https://conhecimento.fgv.br/concursos/exemplo-%';
DELETE FROM concursos.concurso WHERE link_oficial LIKE 'https://conhecimento.fgv.br/concursos/exemplo-%';
DELETE FROM concursos.orgao WHERE nome LIKE '[EXEMPLO]%';

INSERT INTO concursos.orgao (nome, sigla, esfera, uf, municipio, municipio_ibge)
VALUES ('[EXEMPLO] Tribunal de Justiça da Paraíba', 'TJPB', 'ESTADUAL', 'PB', NULL, NULL),
       ('[EXEMPLO] Instituto Nacional do Seguro Social', 'INSS', 'FEDERAL', NULL, NULL, NULL),
       ('[EXEMPLO] Prefeitura de João Pessoa', 'PMJP', 'MUNICIPAL', 'PB', 'João Pessoa', 2507507),
       ('[EXEMPLO] Secretaria da Fazenda de Alagoas', 'SEFAZ-AL', 'ESTADUAL', 'AL', NULL, NULL),
       ('[EXEMPLO] Polícia Civil do Paraná', 'PCPR', 'ESTADUAL', 'PR', NULL, NULL),
       ('[EXEMPLO] Prefeitura de Fraiburgo', 'PMF', 'MUNICIPAL', 'SC', 'Fraiburgo', 4205506),
       ('[EXEMPLO] Ministério da Gestão e da Inovação em Serviços Públicos', 'MGI', 'FEDERAL', NULL, NULL, NULL);

INSERT INTO concursos.concurso (orgao_id, banca_id, titulo, numero_edital, ano, situacao,
                                inscricao_inicio, inscricao_fim, data_prova, taxa_min, taxa_max,
                                link_oficial, link_inscricao, avisos_extracao, origem_estrutura,
                                slug, abrangencia, uf, municipio_ibge, tem_isencao, isencao_inicio, isencao_fim,
                                resumo, resumo_gerado_em, publicado, unificado)
SELECT o.id, b.id, v.titulo, v.numero, extract(year FROM current_date)::smallint, v.situacao,
       current_date + v.ini, current_date + v.fim, current_date + v.prova, v.taxa_min, v.taxa_max,
       'https://conhecimento.fgv.br/concursos/exemplo-' || v.chave,
       CASE WHEN v.situacao = 'PREVISTO' THEN NULL ELSE 'https://portal.conhecimento.fgv.br/Concurso/Inscricao' END,
       v.avisos::jsonb,
       CASE WHEN v.situacao = 'PREVISTO' THEN NULL ELSE 'EDITAL' END,
       CASE WHEN v.publicado THEN 'exemplo-' || v.chave END, v.abrangencia, o.uf, o.municipio_ibge,
       v.isen_ini IS NOT NULL, current_date + v.isen_ini, current_date + v.isen_fim,
       CASE WHEN v.publicado THEN 'Resumo fictício de ' || v.titulo || '. Confira sempre o edital.' END,
       CASE WHEN v.publicado THEN now() END,
       v.publicado, v.chave = 'cnu'
FROM (VALUES ('TJPB', 'tjpb', '[EXEMPLO] Concurso Público TJPB - Analista e Técnico Judiciário', '01/2026', 'INSCRICOES_ABERTAS', -5, 20, 80, 90.00, 120.00, '[]', 'ESTADUAL', -5, 3, true),
             ('INSS', 'inss', '[EXEMPLO] Concurso Público INSS - Técnico do Seguro Social', '02/2026', 'INSCRICOES_ABERTAS', -2, 25, 70, 85.00, 85.00, '[]', 'NACIONAL', -2, 6, true),
             ('PMJP', 'pmjp-saude', '[EXEMPLO] Concurso Público Prefeitura de João Pessoa - Saúde', '03/2026', 'INSCRICOES_ABERTAS', -1, 30, 90, 60.00, 90.00, '["data da prova não encontrada no edital"]', 'MUNICIPAL', -1, 9, true),
             ('SEFAZ-AL', 'sefazal', '[EXEMPLO] Concurso Público SEFAZ/AL - Auditor Fiscal', '04/2026', 'EM_ANDAMENTO', -40, -10, 30, 150.00, 150.00, '[]', 'ESTADUAL', NULL, NULL, true),
             ('PCPR', 'pcpr-previsto', '[EXEMPLO] Concurso Público PCPR - Investigador', NULL, 'PREVISTO', NULL, NULL, NULL, NULL, NULL, '[]', 'ESTADUAL', NULL, NULL, true),
             ('PCPR', 'pcpr-agente', '[EXEMPLO] Concurso Público PCPR - Agente', '05/2026', 'INSCRICOES_ABERTAS', -3, 20, 75, 90.00, 90.00, '[]', 'ESTADUAL', -3, 12, true),
             ('PMF', 'pmf-educacao', '[EXEMPLO] Processo Seletivo Prefeitura de Fraiburgo - Educação', '06/2026', 'ENCERRADO', -200, -170, -140, 50.00, 80.00, '[]', 'MUNICIPAL', -200, -190, true),
             ('MGI', 'cnu', '[EXEMPLO] Concurso Público Nacional Unificado', '08/2026', 'INSCRICOES_ABERTAS', -4, 18, 95, 70.00, 110.00, '[]', 'NACIONAL', -4, 4, true),
             ('INSS', 'rascunho', '[EXEMPLO] Concurso recém-coletado, ainda sem resumo', '07/2026', 'INSCRICOES_ABERTAS', -1, 15, 60, 70.00, 70.00, '[]', NULL, NULL, NULL, false))
         AS v(sigla, chave, titulo, numero, situacao, ini, fim, prova, taxa_min, taxa_max, avisos, abrangencia,
              isen_ini, isen_fim, publicado)
         JOIN concursos.orgao o ON o.sigla = v.sigla AND o.nome LIKE '[EXEMPLO]%'
         JOIN concursos.banca b ON b.sigla = 'FGV';

-- Encerrado há tempo suficiente para cair na retenção de 180 dias nos testes.
UPDATE concursos.concurso SET encerrado_em = now() - interval '170 days'
WHERE link_oficial = 'https://conhecimento.fgv.br/concursos/exemplo-pmf-educacao';

INSERT INTO concursos.cargo (concurso_id, nome, especialidade, escolaridade, vagas, cadastro_reserva, salario,
                             uf_lotacao, area, disciplinas, tem_redacao)
SELECT c.id, v.nome, v.esp, v.esc, v.vagas, v.cr, v.salario, v.uf, v.area, v.disciplinas::text[], v.redacao
FROM (VALUES ('tjpb', 'Analista Judiciário', 'Judiciária', 'SUPERIOR', 25, false, 7526.14, 'PB', 'JURIDICA', '{Língua Portuguesa,Direito Constitucional,Direito Civil,Direito Processual Civil}', true),
             ('tjpb', 'Analista Judiciário', 'TI – Desenvolvimento de Sistemas', 'SUPERIOR', 10, false, 7526.14, 'PB', 'TI', '{Língua Portuguesa,Engenharia de Software,Banco de Dados}', true),
             ('tjpb', 'Técnico Judiciário', NULL, 'MEDIO', 40, true, 4300.00, 'PB', 'ADMINISTRATIVA', '{Língua Portuguesa,Noções de Direito,Raciocínio Lógico}', false),
             ('inss', 'Técnico do Seguro Social', NULL, 'MEDIO', 1000, true, 5900.00, NULL, 'ADMINISTRATIVA', '{Língua Portuguesa,Direito Previdenciário,Informática}', NULL),
             ('pmjp-saude', 'Enfermeiro', NULL, 'SUPERIOR', 30, false, 4100.00, 'PB', 'SAUDE', '{Língua Portuguesa,SUS,Conhecimentos Específicos}', false),
             ('pmjp-saude', 'Técnico em Enfermagem', NULL, 'TECNICO', 60, false, 2400.00, 'PB', 'SAUDE', '{Língua Portuguesa,SUS}', false),
             ('pmjp-saude', 'Agente Comunitário de Saúde', NULL, 'FUNDAMENTAL', 80, false, 1700.00, 'PB', 'SAUDE', '{Língua Portuguesa,Matemática}', false),
             ('sefazal', 'Auditor Fiscal da Receita Estadual', NULL, 'SUPERIOR', 30, false, 21000.00, 'AL', 'CONTROLE_FISCAL', '{Direito Tributário,Contabilidade,Auditoria}', true),
             ('pcpr-agente', 'Agente de Polícia', NULL, 'SUPERIOR', 200, false, 6900.00, 'PR', 'POLICIAL_SEGURANCA', '{Língua Portuguesa,Direito Penal,Direito Processual Penal}', true),
             ('pmf-educacao', 'Professor', 'Anos Iniciais', 'SUPERIOR', 12, true, 3500.00, 'SC', 'EDUCACAO', '{Língua Portuguesa,Didática}', false),
             ('pmf-educacao', 'Motorista', NULL, 'FUNDAMENTAL', 3, false, 2300.00, 'SC', 'OPERACIONAL', '{Legislação de Trânsito}', false),
             ('cnu', 'Analista Técnico de Políticas Sociais', NULL, 'SUPERIOR', 300, false, 6800.00, NULL, 'ASSISTENCIA_SOCIAL', '{Língua Portuguesa,Políticas Públicas}', true),
             ('rascunho', 'Analista do Seguro Social', NULL, 'SUPERIOR', 5, false, 9000.00, NULL, NULL, '{}', NULL))
         AS v(chave, nome, esp, esc, vagas, cr, salario, uf, area, disciplinas, redacao)
         JOIN concursos.concurso c ON c.link_oficial = 'https://conhecimento.fgv.br/concursos/exemplo-' || v.chave;

-- Campos desnormalizados calculados a partir dos cargos, do mesmo jeito que o coletor fará na fase 4.
UPDATE concursos.concurso c
SET total_vagas   = d.total_vagas,
    salario_max   = d.salario_max,
    areas         = d.areas,
    escolaridades = d.escolaridades
FROM (SELECT concurso_id,
             sum(vagas)::integer                                                             AS total_vagas,
             max(salario)                                                                    AS salario_max,
             coalesce(array_agg(DISTINCT area ORDER BY area) FILTER (WHERE area IS NOT NULL), '{}') AS areas,
             coalesce(array_agg(DISTINCT escolaridade ORDER BY escolaridade)
                      FILTER (WHERE escolaridade IS NOT NULL), '{}')                        AS escolaridades
      FROM concursos.cargo
      GROUP BY concurso_id) d
WHERE d.concurso_id = c.id
  AND c.link_oficial LIKE 'https://conhecimento.fgv.br/concursos/exemplo-%';

INSERT INTO concursos.concurso_isencao (concurso_id, tipo_codigo, observacao)
SELECT c.id, v.tipo, v.obs
FROM (VALUES ('tjpb', 'CADUNICO', NULL),
             ('tjpb', 'DOADOR_SANGUE', NULL),
             ('tjpb', 'DOADOR_MEDULA', NULL),
             ('tjpb', 'JURADO', NULL),
             ('tjpb', 'VITIMA_VIOLENCIA_DOMESTICA', 'mulheres vítimas de violência doméstica'),
             ('tjpb', 'DOADOR_PLASMA', NULL),
             ('inss', 'CADUNICO', NULL),
             ('inss', 'DOADOR_MEDULA', NULL),
             ('pmjp-saude', 'CADUNICO', NULL),
             ('pcpr-agente', 'DOADOR_SANGUE', 'mínimo de doações exigido pelo edital'),
             ('pmf-educacao', 'CADUNICO', NULL))
         AS v(chave, tipo, obs)
         JOIN concursos.concurso c ON c.link_oficial = 'https://conhecimento.fgv.br/concursos/exemplo-' || v.chave;

INSERT INTO concursos.concurso_evento (concurso_id, ordem, evento, inicio, fim)
SELECT c.id, v.ordem, v.evento, current_date + v.ini, current_date + v.fim
FROM (VALUES ('tjpb', 1, 'Pedido de isenção da taxa', -5, 3),
             ('tjpb', 2, 'Inscrições', -5, 20),
             ('tjpb', 3, 'Prova objetiva e discursiva', 80, 80),
             ('tjpb', 4, 'Resultado final', NULL, NULL),
             ('pmjp-saude', 1, 'Pedido de isenção da taxa', -1, 9),
             ('pmjp-saude', 2, 'Inscrições', -1, 30),
             ('pmjp-saude', 3, 'Prova objetiva', NULL, NULL))
         AS v(chave, ordem, evento, ini, fim)
         JOIN concursos.concurso c ON c.link_oficial = 'https://conhecimento.fgv.br/concursos/exemplo-' || v.chave;

INSERT INTO concursos.documento (concurso_id, tipo, titulo, url_origem, hash_sha256, data_publicacao, texto_extraido,
                                 status_extracao)
SELECT c.id, v.tipo, v.titulo,
       'https://conhecimento.fgv.br/sites/default/files/concursos/exemplo-' || v.chave || '-' || v.arquivo || '.pdf',
       encode(sha256(convert_to(v.chave || v.arquivo, 'UTF8')), 'hex'),
       current_date + v.dias, 'Texto fictício do ' || v.titulo || '.', 'OK'
FROM (VALUES ('tjpb', 'EDITAL', 'Edital de abertura', 'edital', -5),
             ('tjpb', 'RETIFICACAO', '1ª Retificação', 'ret1', -1),
             ('inss', 'EDITAL', 'Edital de abertura', 'edital', -2),
             ('pmjp-saude', 'EDITAL', 'Edital de abertura', 'edital', -1),
             ('sefazal', 'EDITAL', 'Edital de abertura', 'edital', -40),
             ('pcpr-agente', 'EDITAL', 'Edital de abertura', 'edital', -3),
             ('pmf-educacao', 'EDITAL', 'Edital de abertura', 'edital', -200),
             ('rascunho', 'EDITAL', 'Edital de abertura', 'edital', -1))
         AS v(chave, tipo, titulo, arquivo, dias)
         JOIN concursos.concurso c ON c.link_oficial = 'https://conhecimento.fgv.br/concursos/exemplo-' || v.chave;

INSERT INTO concursos.sinal_descoberta (fonte_id, titulo, url, data_publicacao, payload, status, concurso_id)
SELECT f.id, c.titulo, c.link_oficial, current_date, '{"origem": "seed"}'::jsonb, 'VINCULADO', c.id
FROM concursos.concurso c
         JOIN concursos.fonte f ON f.nome = 'fgv'
WHERE c.link_oficial LIKE 'https://conhecimento.fgv.br/concursos/exemplo-%';

INSERT INTO concursos.execucao_coleta (fonte_id, etapa, inicio, fim, status, itens_novos)
SELECT f.id, 'DESCOBERTA', now() - interval '5 minutes', now(), 'SUCESSO', 8
FROM concursos.fonte f
WHERE f.nome = 'fgv';

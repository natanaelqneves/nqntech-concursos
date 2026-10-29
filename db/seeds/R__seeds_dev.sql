-- Dados fictícios SÓ para desenvolvimento e testes (nunca carregados em produção: a pasta db/seeds só entra
-- no Flyway do docker-compose e da CI). Repetível: apaga e recria tudo que tem o prefixo "exemplo-".
-- Datas relativas a current_date para os concursos continuarem "com inscrições abertas" em qualquer dia.
-- Variedade proposital de áreas, níveis, esferas e UFs; a fase 1 acrescenta áreas, isenções e resumo.

DELETE FROM concursos.sinal_descoberta WHERE url LIKE 'https://conhecimento.fgv.br/concursos/exemplo-%';
DELETE FROM concursos.concurso WHERE link_oficial LIKE 'https://conhecimento.fgv.br/concursos/exemplo-%';
DELETE FROM concursos.orgao WHERE nome LIKE '[EXEMPLO]%';

INSERT INTO concursos.orgao (nome, sigla, esfera, uf, municipio)
VALUES ('[EXEMPLO] Tribunal de Justiça da Paraíba', 'TJPB', 'ESTADUAL', 'PB', NULL),
       ('[EXEMPLO] Instituto Nacional do Seguro Social', 'INSS', 'FEDERAL', NULL, NULL),
       ('[EXEMPLO] Prefeitura de João Pessoa', 'PMJP', 'MUNICIPAL', 'PB', 'João Pessoa'),
       ('[EXEMPLO] Secretaria da Fazenda de Alagoas', 'SEFAZ-AL', 'ESTADUAL', 'AL', NULL),
       ('[EXEMPLO] Polícia Civil do Paraná', 'PCPR', 'ESTADUAL', 'PR', NULL),
       ('[EXEMPLO] Prefeitura de Fraiburgo', 'PMF', 'MUNICIPAL', 'SC', 'Fraiburgo');

INSERT INTO concursos.concurso (orgao_id, banca_id, titulo, numero_edital, ano, situacao,
                                inscricao_inicio, inscricao_fim, data_prova, taxa_min, taxa_max,
                                link_oficial, link_inscricao, avisos_extracao, origem_estrutura)
SELECT o.id, b.id, v.titulo, v.numero, extract(year FROM current_date)::smallint, v.situacao,
       current_date + v.ini, current_date + v.fim, current_date + v.prova, v.taxa_min, v.taxa_max,
       'https://conhecimento.fgv.br/concursos/exemplo-' || v.slug,
       CASE WHEN v.situacao = 'PREVISTO' THEN NULL ELSE 'https://portal.conhecimento.fgv.br/Concurso/Inscricao' END,
       v.avisos::jsonb,
       CASE WHEN v.situacao = 'PREVISTO' THEN NULL ELSE 'EDITAL' END
FROM (VALUES ('TJPB', 'tjpb', '[EXEMPLO] Concurso Público TJPB - Analista e Técnico Judiciário', '01/2026', 'INSCRICOES_ABERTAS', -5, 20, 80, 90.00, 120.00, '[]'),
             ('INSS', 'inss', '[EXEMPLO] Concurso Público INSS - Técnico do Seguro Social', '02/2026', 'INSCRICOES_ABERTAS', -2, 25, 70, 85.00, 85.00, '[]'),
             ('PMJP', 'pmjp-saude', '[EXEMPLO] Concurso Público Prefeitura de João Pessoa - Saúde', '03/2026', 'INSCRICOES_ABERTAS', -1, 30, 90, 60.00, 90.00, '["data da prova não encontrada no edital"]'),
             ('SEFAZ-AL', 'sefazal', '[EXEMPLO] Concurso Público SEFAZ/AL - Auditor Fiscal', '04/2026', 'EM_ANDAMENTO', -40, -10, 30, 150.00, 150.00, '[]'),
             ('PCPR', 'pcpr-previsto', '[EXEMPLO] Concurso Público PCPR - Investigador', NULL, 'PREVISTO', NULL, NULL, NULL, NULL, NULL, '[]'),
             ('PCPR', 'pcpr-agente', '[EXEMPLO] Concurso Público PCPR - Agente', '05/2026', 'INSCRICOES_ABERTAS', -3, 20, 75, 90.00, 90.00, '[]'),
             ('PMF', 'pmf-educacao', '[EXEMPLO] Processo Seletivo Prefeitura de Fraiburgo - Educação', '06/2026', 'ENCERRADO', -200, -170, -140, 50.00, 80.00, '[]'))
         AS v(sigla, slug, titulo, numero, situacao, ini, fim, prova, taxa_min, taxa_max, avisos)
         JOIN concursos.orgao o ON o.sigla = v.sigla AND o.nome LIKE '[EXEMPLO]%'
         JOIN concursos.banca b ON b.sigla = 'FGV';

INSERT INTO concursos.cargo (concurso_id, nome, especialidade, escolaridade, vagas, cadastro_reserva, salario, uf_lotacao)
SELECT c.id, v.nome, v.esp, v.esc, v.vagas, v.cr, v.salario, v.uf
FROM (VALUES ('tjpb', 'Analista Judiciário', 'Judiciária', 'SUPERIOR', 25, false, 7526.14, 'PB'),
             ('tjpb', 'Analista Judiciário', 'TI – Desenvolvimento de Sistemas', 'SUPERIOR', 10, false, 7526.14, 'PB'),
             ('tjpb', 'Técnico Judiciário', NULL, 'MEDIO', 40, true, 4300.00, 'PB'),
             ('inss', 'Técnico do Seguro Social', NULL, 'MEDIO', 1000, true, 5900.00, NULL),
             ('pmjp-saude', 'Enfermeiro', NULL, 'SUPERIOR', 30, false, 4100.00, 'PB'),
             ('pmjp-saude', 'Técnico em Enfermagem', NULL, 'TECNICO', 60, false, 2400.00, 'PB'),
             ('pmjp-saude', 'Agente Comunitário de Saúde', NULL, 'FUNDAMENTAL', 80, false, 1700.00, 'PB'),
             ('sefazal', 'Auditor Fiscal da Receita Estadual', NULL, 'SUPERIOR', 30, false, 21000.00, 'AL'),
             ('pcpr-agente', 'Agente de Polícia', NULL, 'SUPERIOR', 200, false, 6900.00, 'PR'),
             ('pmf-educacao', 'Professor', 'Anos Iniciais', 'SUPERIOR', 12, true, 3500.00, 'SC'),
             ('pmf-educacao', 'Motorista', NULL, 'FUNDAMENTAL', 3, false, 2300.00, 'SC'))
         AS v(slug, nome, esp, esc, vagas, cr, salario, uf)
         JOIN concursos.concurso c ON c.link_oficial = 'https://conhecimento.fgv.br/concursos/exemplo-' || v.slug;

INSERT INTO concursos.documento (concurso_id, tipo, titulo, url_origem, hash_sha256, data_publicacao, texto_extraido,
                                 status_extracao)
SELECT c.id, v.tipo, v.titulo,
       'https://conhecimento.fgv.br/sites/default/files/concursos/exemplo-' || v.slug || '-' || v.arquivo || '.pdf',
       encode(sha256(convert_to(v.slug || v.arquivo, 'UTF8')), 'hex'),
       current_date + v.dias, 'Texto fictício do ' || v.titulo || '.', 'OK'
FROM (VALUES ('tjpb', 'EDITAL', 'Edital de abertura', 'edital', -5),
             ('tjpb', 'RETIFICACAO', '1ª Retificação', 'ret1', -1),
             ('inss', 'EDITAL', 'Edital de abertura', 'edital', -2),
             ('pmjp-saude', 'EDITAL', 'Edital de abertura', 'edital', -1),
             ('sefazal', 'EDITAL', 'Edital de abertura', 'edital', -40),
             ('pcpr-agente', 'EDITAL', 'Edital de abertura', 'edital', -3),
             ('pmf-educacao', 'EDITAL', 'Edital de abertura', 'edital', -200))
         AS v(slug, tipo, titulo, arquivo, dias)
         JOIN concursos.concurso c ON c.link_oficial = 'https://conhecimento.fgv.br/concursos/exemplo-' || v.slug;

INSERT INTO concursos.sinal_descoberta (fonte_id, titulo, url, data_publicacao, payload, status, concurso_id)
SELECT f.id, c.titulo, c.link_oficial, current_date, '{"origem": "seed"}'::jsonb, 'VINCULADO', c.id
FROM concursos.concurso c
         JOIN concursos.fonte f ON f.nome = 'fgv'
WHERE c.link_oficial LIKE 'https://conhecimento.fgv.br/concursos/exemplo-%';

INSERT INTO concursos.execucao_coleta (fonte_id, etapa, inicio, fim, status, itens_novos)
SELECT f.id, 'DESCOBERTA', now() - interval '5 minutes', now(), 'SUCESSO', 7
FROM concursos.fonte f
WHERE f.nome = 'fgv';

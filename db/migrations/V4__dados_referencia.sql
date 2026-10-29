-- Dados de referência necessários também em produção: bancas conhecidas e fontes de coleta.
-- coleta_permitida reflete robots.txt, termos e anti-bot verificados (herdado do Radar TI, sondagem a partir do
-- GitHub Actions em 29/10/2026). 403 = bloqueio a servidores: nunca contornar.

INSERT INTO concursos.banca (nome, sigla, site, coleta_permitida, observacao)
VALUES ('Fundação Getulio Vargas', 'FGV', 'https://conhecimento.fgv.br/concursos', true,
        'HTML pronto; robots.txt libera /concursos e os PDFs'),
       ('Instituto Brasileiro de Administração Municipal', 'IBAM', 'https://www.ibam-concursos.org.br', true,
        'Página única com cargos, vagas, taxas e documentos; sem robots.txt'),
       ('Instituto Brasileiro de Apoio e Desenvolvimento Executivo', 'IBADE', 'https://portal.ibade.selecao.site/edital',
        true, 'Lista + página por concurso com cargos e arquivos; datas e vagas só no PDF'),
       ('Fundação Vunesp', 'VUNESP', 'https://www.vunesp.com.br', false,
        '403 até no robots.txt a partir do GitHub Actions (29/10/2026): não contornar'),
       ('Instituto Selecon', 'SELECON', 'https://selecon.org.br', false,
        'Lista liberada, mas páginas de detalhe (selecao.net.br) respondem 403 (29/10/2026)'),
       ('Cebraspe', 'CEBRASPE', 'https://www.cebraspe.org.br', false,
        'Lista carregada por JavaScript; depende de API JSON'),
       ('Instituto AOCP', 'AOCP', 'https://www.institutoaocp.org.br', false,
        'Lista carregada por JavaScript; depende de API JSON'),
       ('Fundação Cesgranrio', 'CESGRANRIO', 'https://www.cesgranrio.org.br', false,
        '403 até no robots.txt a partir do GitHub Actions (29/10/2026): não contornar'),
       ('Instituto Brasileiro de Formação e Capacitação', 'IBFC', 'https://www.ibfc.org.br', false,
        '403 até no robots.txt a partir do GitHub Actions (29/10/2026): não contornar'),
       ('Instituto de Desenvolvimento Educacional, Cultural e Assistencial Nacional', 'IDECAN',
        'https://www.idecan.org.br', false,
        'Portal de editais responde 403 (proteção anti-robô) em 29/10/2026: não contornar'),
       ('Fundação Carlos Chagas', 'FCC', 'https://www.concursosfcc.com.br', false,
        'robots.txt bloqueia /concursos/ e *.pdf'),
       ('Comissão Permanente do Concurso Vestibular (UEPB)', 'CPCON', 'https://cpcon.uepb.edu.br', false,
        'Bloqueia acesso automatizado'),
       ('Instituto Consulplan', 'CONSULPLAN', 'https://www.institutoconsulplan.org.br', false,
        '403 até no robots.txt a partir do GitHub Actions (29/10/2026): não contornar'),
       ('Fundatec', 'FUNDATEC', 'https://www.fundatec.org.br', false,
        '403 até no robots.txt a partir do GitHub Actions (29/10/2026): não contornar'),
       ('Instituto Quadrix', 'QUADRIX', 'https://site.quadrix.org.br', false,
        'Página de concursos responde 403 ao coletor (29/10/2026): não contornar')
ON CONFLICT (sigla) DO NOTHING;

INSERT INTO concursos.fonte (tipo, nome, banca_id, ativa, url_base)
SELECT 'BANCA_SITE', v.nome, b.id, true, v.url
FROM (VALUES ('fgv', 'FGV', 'https://conhecimento.fgv.br/concursos'),
             ('ibam', 'IBAM', 'https://www.ibam-concursos.org.br/default.asp?status=2'),
             ('ibade', 'IBADE', 'https://portal.ibade.selecao.site/edital')) AS v(nome, sigla, url)
         JOIN concursos.banca b ON b.sigla = v.sigla
ON CONFLICT (nome) DO NOTHING;

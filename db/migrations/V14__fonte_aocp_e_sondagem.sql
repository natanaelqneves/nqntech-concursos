-- AOCP passa a ser coletada pela API JSON pública do próprio site; observações das demais bancas da lista
-- atualizadas com a sondagem de 04/11/2026 (workflow captura-sondagem, a partir do GitHub Actions).

SET search_path = concursos;

UPDATE banca
SET coleta_permitida = true,
    observacao       = 'API JSON www.institutoaocp.org.br/api/concursos (status SUBSCRIBE); robots.txt inexistente; '
                           || 'editais fora da API (dados só da listagem) — 04/11/2026'
WHERE sigla = 'AOCP';

INSERT INTO fonte (tipo, nome, banca_id, ativa, url_base)
SELECT 'BANCA_SITE', 'aocp', b.id, true, 'https://www.institutoaocp.org.br/api/concursos'
FROM banca b
WHERE b.sigla = 'AOCP'
ON CONFLICT (nome) DO NOTHING;

UPDATE banca SET observacao = v.obs
FROM (VALUES
          ('FCC', 'robots.txt bloqueia /concursos/ (inclui bannersConcurso.js) e *.pdf; a webapi liberada lista '
              || 'formulários publicados com prazos já vencidos, sem como confirmar inscrição aberta — 04/11/2026'),
          ('CESGRANRIO', 'robots.txt responde 403 ao coletor (04/11/2026): não contornar'),
          ('VUNESP', 'robots.txt responde 403 ao coletor (04/11/2026): não contornar'),
          ('IBFC', 'robots.txt responde 403 ao coletor (04/11/2026): não contornar'),
          ('QUADRIX', 'páginas respondem 403 (proteção anti-robô) em 04/11/2026: não contornar'),
          ('IDECAN', 'robots.txt permite (search=yes, ai-train=no), mas concurso.idecan.org.br/editais responde 403 '
              || '(anti-robô) em 04/11/2026: não contornar'),
          ('CONSULPLAN', 'robots.txt responde 403 ao coletor (04/11/2026): não contornar'),
          ('CPCON', 'servidor recusa conexão a partir do GitHub Actions (04/11/2026)'))
         AS v(sigla, obs)
WHERE banca.sigla = v.sigla;

INSERT INTO banca (nome, sigla, site, coleta_permitida, observacao)
VALUES ('Fundação de Desenvolvimento da Pesquisa', 'FUNDEP', 'https://www.gestaodeconcursos.com.br', false,
        'concursos abertos ficam em fundep.selecao.net.br, cujo robots.txt responde 403 (04/11/2026)'),
       ('Fundação Mariana Resende Costa', 'FUMARC', 'https://www.fumarc.com.br', false,
        'certificado TLS inválido a partir do GitHub Actions (04/11/2026): não desligar a verificação'),
       ('Comissão Permanente do Vestibular (UFRN)', 'COMPERVE', 'https://www.comperve.ufrn.br', false,
        'certificado TLS inválido a partir do GitHub Actions (04/11/2026): não desligar a verificação')
ON CONFLICT (sigla) DO NOTHING;

-- COMPERVE (UFRN) passa a ser coletada (sondagem de 04/11/2026: HTML estático, robots.txt inexistente). O servidor
-- não envia o intermediário GlobalSign RSA OV SSL CA 2018; o coletor o traz em coletor/certificados com a
-- verificação TLS ativa (cadeia completa até a raiz GlobalSign R3 do certifi).

SET search_path = concursos;

UPDATE banca
SET coleta_permitida = true,
    site             = 'https://www.comperve.ufrn.br/conteudo/concursos.php',
    observacao       = 'HTML estático (categorias NOVOS e INSCRIÇÕES ABERTAS); servidor sem o certificado '
                           || 'intermediário, completado pelo coletor; robots.txt inexistente em 04/11/2026'
WHERE sigla = 'COMPERVE';

INSERT INTO fonte (tipo, nome, banca_id, ativa, url_base)
SELECT 'BANCA_SITE', 'comperve', b.id, true, 'https://www.comperve.ufrn.br/conteudo/concursos.php'
FROM banca b
WHERE b.sigla = 'COMPERVE'
ON CONFLICT (nome) DO NOTHING;

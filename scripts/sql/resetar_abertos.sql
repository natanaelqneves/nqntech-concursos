-- Reinício da coleta SÓ dos concursos abertos e previstos (rodar no SQL Editor do Neon, como dono do banco).
-- Ficam no banco os EM_ANDAMENTO e ENCERRADO: o coletor os reconhece e não relê as páginas nem os editais deles.
-- Apagar o concurso apaga também cargos, documentos (texto), isenções e calendário (ON DELETE CASCADE); os sinais
-- da fonte saem junto para a próxima coleta redescobrir a página e baixar o edital de novo.
-- PDFs importados à mão/pelo Drive: o sinal some também; para reimportar, volte o PDF da subpasta "processados".

SET search_path = concursos;

-- 1) Confira antes o que vai sair:
SELECT situacao, count(*) FROM concurso
WHERE situacao IN ('INSCRICOES_ABERTAS', 'PREVISTO')
GROUP BY situacao;

-- 2) Apague (tudo ou nada):
BEGIN;

DELETE FROM sinal_descoberta
WHERE concurso_id IN (SELECT id FROM concurso WHERE situacao IN ('INSCRICOES_ABERTAS', 'PREVISTO'));

DELETE FROM concurso
WHERE situacao IN ('INSCRICOES_ABERTAS', 'PREVISTO');

-- Órgãos que ficaram sem nenhum concurso (a coleta recria com o local lido no edital).
DELETE FROM orgao o WHERE NOT EXISTS (SELECT 1 FROM concurso c WHERE c.orgao_id = o.id);

COMMIT;

-- O cache da IA não precisa ser apagado: a versão do esquema mudou (2), então todo edital é lido de novo.
-- Depois: Actions → diario → Run workflow (com o limite padrão, alguns dias para reler tudo).

-- Fase 3: textos do catálogo de isenções (fonte: config/isencoes.yml; o teste test_catalogo_isencoes_igual_ao_banco
-- confere que batem) e reestruturação dos editais já lidos com o extrator novo (isenção, calendário, disciplinas e
-- prova discursiva por cargo).

SET search_path = concursos;

UPDATE isencao_tipo
SET nome         = 'Inscritos no CadÚnico',
    descricao    = 'Pessoas de família inscrita no Cadastro Único (CadÚnico), o cadastro do governo federal para famílias de baixa renda. Muitos editais pedem renda por pessoa de até meio salário mínimo e o cadastro atualizado.',
    base_legal   = 'Em concursos federais, Lei nº 13.656/2018. Estados e municípios têm leis próprias, citadas em cada edital.',
    link_oficial = 'https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13656.htm'
WHERE codigo = 'CADUNICO';

UPDATE isencao_tipo
SET nome         = 'Doadores de medula óssea',
    descricao    = 'Pessoas cadastradas como doadoras de medula óssea em hemocentro ou entidade reconhecida. Alguns editais aceitam só o cadastro; outros pedem a doação já feita.',
    base_legal   = 'Em concursos federais, Lei nº 13.656/2018. Estados e municípios têm leis próprias, citadas em cada edital.',
    link_oficial = 'https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13656.htm'
WHERE codigo = 'DOADOR_MEDULA';

UPDATE isencao_tipo
SET nome         = 'Doadores de sangue',
    descricao    = 'Pessoas que doam sangue com regularidade. Os editais costumam exigir um número mínimo de doações num período, por exemplo três doações nos últimos doze meses.',
    base_legal   = 'Leis estaduais e municipais. Exemplo: Lei Estadual nº 11.213/2018 da Paraíba, citada no edital do TJPB 2026.',
    link_oficial = NULL
WHERE codigo = 'DOADOR_SANGUE';

UPDATE isencao_tipo
SET nome         = 'Doadores de plasma',
    descricao    = 'Pessoas que doaram plasma, em geral quem se curou da COVID-19 e doou plasma convalescente, conforme lei do estado.',
    base_legal   = 'Leis estaduais. Exemplo: Lei Estadual nº 11.755/2020 da Paraíba, citada no edital do TJPB 2026.',
    link_oficial = NULL
WHERE codigo = 'DOADOR_PLASMA';

UPDATE isencao_tipo
SET nome         = 'Jurados',
    descricao    = 'Pessoas que atuaram como jurado no Tribunal do Júri. Os editais costumam pedir um número mínimo de sessões e às vezes limitam o tempo desde o último júri.',
    base_legal   = 'Leis estaduais. Exemplos: Lei Estadual nº 13.704/2025 da Paraíba (TJPB 2026) e Lei Estadual nº 4.530/2024 do Tocantins (SES-TO 2026).',
    link_oficial = NULL
WHERE codigo = 'JURADO';

UPDATE isencao_tipo
SET nome         = 'Mesários e trabalhadores das eleições',
    descricao    = 'Eleitores convocados pela Justiça Eleitoral que trabalharam nas eleições, como mesários ou no apoio.',
    base_legal   = 'Leis estaduais e municipais. Exemplos: Lei Estadual nº 19.196/2017 do Paraná (PCPR 2026) e Lei Estadual nº 4.000/2022 do Tocantins (SES-TO 2026).',
    link_oficial = NULL
WHERE codigo = 'MESARIO_ELEITORAL';

UPDATE isencao_tipo
SET nome         = 'Pessoas com deficiência',
    descricao    = 'Pessoas com deficiência, quando a lei do local prevê isenção da taxa. Isso é diferente da reserva de vagas, que existe em quase todos os concursos.',
    base_legal   = 'Leis estaduais e municipais. Exemplo: Lei Estadual nº 6.988/2007 do Pará (SEDUC-PA 2026).',
    link_oficial = NULL
WHERE codigo = 'PESSOA_COM_DEFICIENCIA';

UPDATE isencao_tipo
SET nome         = 'Mulheres vítimas de violência doméstica',
    descricao    = 'Mulheres vítimas de violência doméstica e familiar, conforme lei do estado. As leis usam a definição da Lei Maria da Penha.',
    base_legal   = 'Leis estaduais, com base na Lei nº 11.340/2006 (Lei Maria da Penha). Exemplos: Lei Estadual nº 14.372/2026 da Paraíba (TJPB 2026) e Lei Estadual nº 11.040/2025 do Pará (SEDUC-PA 2026).',
    link_oficial = 'https://www2.camara.leg.br/legin/fed/lei/2006/lei-11340-7-agosto-2006-545133-norma-pl.html'
WHERE codigo = 'VITIMA_VIOLENCIA_DOMESTICA';

UPDATE isencao_tipo
SET nome         = 'Estudantes',
    descricao    = 'Estudantes, em geral de baixa renda ou da rede pública, quando a lei do local prevê.',
    base_legal   = 'Leis estaduais e municipais, citadas em cada edital.',
    link_oficial = NULL
WHERE codigo = 'ESTUDANTE';

UPDATE isencao_tipo
SET nome         = 'Desempregados',
    descricao    = 'Pessoas sem emprego, quando a lei do local prevê. Alguns editais também exigem baixa renda.',
    base_legal   = 'Leis estaduais e municipais, citadas em cada edital.',
    link_oficial = NULL
WHERE codigo = 'DESEMPREGADO';

UPDATE isencao_tipo
SET nome         = 'Outros casos previstos no edital',
    descricao    = 'Outras situações que o edital prevê, como doadoras de leite humano. Cada caso tem regras próprias.',
    base_legal   = 'Leis citadas em cada edital.',
    link_oficial = NULL
WHERE codigo = 'OUTRA';

-- O texto dos editais continua no banco: zerar o vínculo faz a etapa "estruturar" reprocessar tudo na próxima coleta,
-- sem baixar nenhum PDF de novo.
UPDATE concurso SET edital_documento_id = NULL WHERE origem_estrutura = 'EDITAL';

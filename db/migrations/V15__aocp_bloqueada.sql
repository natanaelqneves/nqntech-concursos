-- A API da AOCP respondeu 200 à sondagem e 403 ao coletor no mesmo dia (04/11/2026): bloqueio do servidor a robôs.
-- Regra do projeto: 403 não se contorna. A fonte fica desativada (o adaptador continua no código para quando a banca
-- liberar); reativar é um UPDATE em fonte.ativa depois de uma nova sondagem.

SET search_path = concursos;

UPDATE fonte SET ativa = false WHERE nome = 'aocp';

UPDATE banca
SET coleta_permitida = false,
    observacao       = 'API JSON /api/concursos respondeu 200 à sondagem e 403 ao coletor em 04/11/2026 (bloqueio a '
                           || 'robôs): fonte desativada, não contornar'
WHERE sigla = 'AOCP';

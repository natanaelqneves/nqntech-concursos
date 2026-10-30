package br.com.nqntech.site.dados;

import java.util.List;

/** Tipo de isenção com os textos da página explicativa (config/isencoes.yml). */
public record TipoIsencao(
        String codigo,
        String nome,
        String slug,
        String descricao,
        List<String> documentos,
        String baseLegal,
        String linkOficial) {}

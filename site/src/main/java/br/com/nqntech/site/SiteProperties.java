package br.com.nqntech.site;

import java.nio.file.Path;
import java.time.LocalDate;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * @param urlBase    endereço público, sem barra final (URL canônica, sitemap, JSON-LD)
 * @param saida      pasta onde o HTML é gerado (apagada e recriada a cada execução)
 * @param isencoes   config/isencoes.yml (documentos usuais de cada isenção)
 * @param hoje       data de referência; vazio = hoje em Brasília (fixada só em testes)
 */
@ConfigurationProperties("site")
public record SiteProperties(String urlBase, Path saida, Path isencoes, LocalDate hoje) {

    public SiteProperties {
        urlBase = urlBase == null || urlBase.isBlank() ? "http://localhost:8080" : urlBase.replaceAll("/+$", "");
        saida = saida == null ? Path.of("saida-site") : saida;
        isencoes = isencoes == null ? Path.of("config", "isencoes.yml") : isencoes;
    }
}

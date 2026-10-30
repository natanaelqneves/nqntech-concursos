package br.com.nqntech.site;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ConfigurableApplicationContext;

import br.com.nqntech.site.geracao.GeradorSite;

/** Gera o site estático e termina (roda no GitHub Actions depois da coleta). */
@SpringBootApplication
@EnableConfigurationProperties(SiteProperties.class)
public class SiteApplication {

    public static void main(String[] args) throws Exception {
        try (ConfigurableApplicationContext contexto = SpringApplication.run(SiteApplication.class, args)) {
            contexto.getBean(GeradorSite.class).gerar();
        }
    }
}

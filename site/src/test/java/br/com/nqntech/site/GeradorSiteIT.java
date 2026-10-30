package br.com.nqntech.site;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import br.com.nqntech.site.geracao.GeradorSite;

/**
 * Gera o site contra o banco da CI (migrations + seeds de dev), conectado como site_app, exatamente como em
 * produção. Precisa de SITE_DB_URL/SITE_DB_PASSWORD no ambiente (o ci.yml define).
 */
@SpringBootTest
class GeradorSiteIT {

    @TempDir
    static Path saida;

    @DynamicPropertySource
    static void propriedades(DynamicPropertyRegistry registro) {
        registro.add("site.saida", () -> saida.toString());
        registro.add("site.url-base", () -> "https://exemplo.dev");
    }

    @Autowired
    GeradorSite gerador;

    @Test
    void geraSoOportunidadesComLinksInternosValidos() throws Exception {
        Map<String, String> arquivos = gerador.gerar();

        // Seeds: publicados e oportunidade aparecem; encerrado, em andamento sem isenção e não publicado, não.
        assertThat(saida.resolve("concurso/exemplo-tjpb/index.html")).exists();
        assertThat(saida.resolve("concurso/exemplo-cnu/index.html")).exists();
        assertThat(saida.resolve("concurso/exemplo-pcpr-previsto/index.html")).exists();
        assertThat(saida.resolve("concurso/exemplo-pmf-educacao/index.html")).doesNotExist();
        assertThat(saida.resolve("concurso/exemplo-sefazal/index.html")).doesNotExist();
        assertThat(arquivos.keySet()).noneMatch(k -> k.contains("rascunho"));

        // Município só com concurso municipal publicado.
        assertThat(saida.resolve("municipio/pb/joao-pessoa/index.html")).exists();
        assertThat(saida.resolve("municipio/sc/fraiburgo/index.html")).doesNotExist();
        assertThat(saida.resolve("estado/pb/index.html")).exists();
        assertThat(saida.resolve("regiao/nordeste/index.html")).exists();
        assertThat(saida.resolve("isencoes/cadunico/index.html")).exists();

        // Tela inicial: CNU primeiro, depois o nacional (INSS), depois os demais.
        String inicio = Files.readString(saida.resolve("index.html"));
        int cnu = inicio.indexOf("/concurso/exemplo-cnu/");
        int inss = inicio.indexOf("/concurso/exemplo-inss/");
        int tjpb = inicio.indexOf("/concurso/exemplo-tjpb/");
        assertThat(cnu).isPositive().isLessThan(inss);
        assertThat(inss).isLessThan(tjpb);
        assertThat(inicio.indexOf("/concurso/exemplo-pcpr-previsto/", inicio.indexOf("Inscrições abertas</h2>")))
                .as("previsto fora da lista de inscrições abertas").isNegative();

        // Arquivos de apoio.
        assertThat(saida.resolve("404.html")).exists();
        assertThat(saida.resolve("assets/site.css")).exists();
        assertThat(saida.resolve("_headers")).exists();
        assertThat(Files.readString(saida.resolve("robots.txt"))).contains("Sitemap: https://exemplo.dev/sitemap.xml");
        String sitemap = Files.readString(saida.resolve("sitemap.xml"));
        assertThat(sitemap).contains("<loc>https://exemplo.dev/concurso/exemplo-tjpb/</loc>")
                .doesNotContain("exemplo-pmf-educacao");
        assertThat(Files.readString(saida.resolve("busca.json"))).contains("\"url\":\"/concurso/exemplo-cnu/\"");

        // Nenhum link interno quebrado em nenhuma página.
        Pattern href = Pattern.compile("href=\"(/[^\"#?]*)");
        Set<String> quebrados = new HashSet<>();
        try (var caminhos = Files.walk(saida)) {
            for (Path pagina : caminhos.filter(p -> p.toString().endsWith(".html")).toList()) {
                Matcher m = href.matcher(Files.readString(pagina));
                while (m.find()) {
                    String link = m.group(1);
                    Path alvo = link.endsWith("/") ? saida.resolve(link.substring(1) + "index.html")
                            : saida.resolve(link.substring(1));
                    if (!Files.exists(alvo)) {
                        quebrados.add(saida.relativize(pagina) + " -> " + link);
                    }
                }
            }
        }
        assertThat(quebrados).isEmpty();
    }
}

package br.com.nqntech.site.geracao;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.Predicate;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.stereotype.Service;
import org.thymeleaf.TemplateEngine;
import org.thymeleaf.templatemode.TemplateMode;
import org.thymeleaf.templateresolver.ClassLoaderTemplateResolver;

import br.com.nqntech.site.SiteProperties;
import br.com.nqntech.site.dados.Concurso;
import br.com.nqntech.site.dados.Item;
import br.com.nqntech.site.dados.Municipio;
import br.com.nqntech.site.dados.RepositorioSite;
import br.com.nqntech.site.dados.TipoIsencao;
import br.com.nqntech.site.dados.Uf;

/**
 * Gera todas as páginas a cada execução, numa pasta limpa. "Só o que mudou" chega à Cloudflare porque o
 * {@code wrangler deploy} compara o hash de cada arquivo e envia apenas os diferentes.
 */
@Service
public class GeradorSite {

    private static final Logger log = LoggerFactory.getLogger(GeradorSite.class);
    public static final String NOME = "NqnTech Concursos";

    private final RepositorioSite repositorio;
    private final SiteProperties propriedades;
    private final TemplateEngine templates;

    public GeradorSite(RepositorioSite repositorio, SiteProperties propriedades) {
        this.repositorio = repositorio;
        this.propriedades = propriedades;
        this.templates = criarTemplates();
    }

    static TemplateEngine criarTemplates() {
        ClassLoaderTemplateResolver resolvedor = new ClassLoaderTemplateResolver();
        resolvedor.setPrefix("templates/");
        resolvedor.setSuffix(".html");
        resolvedor.setTemplateMode(TemplateMode.HTML);
        resolvedor.setCharacterEncoding(StandardCharsets.UTF_8.name());
        resolvedor.setCacheable(true);
        TemplateEngine motor = new TemplateEngine();
        motor.setTemplateResolver(resolvedor);
        return motor;
    }

    public Map<String, String> gerar() throws IOException {
        LocalDate hoje = Objects.requireNonNullElseGet(propriedades.hoje(), () -> LocalDate.now(Formatos.FUSO));
        Map<String, String> arquivos = montar(hoje);
        gravar(arquivos);
        log.info("site gerado em {}: {} arquivos", propriedades.saida().toAbsolutePath(), arquivos.size());
        return arquivos;
    }

    /** Monta o conteúdo de todos os arquivos (caminho relativo → conteúdo), sem tocar no disco. */
    public Map<String, String> montar(LocalDate hoje) throws IOException {
        List<Concurso> concursos = repositorio.concursosPublicados(hoje);
        List<Item> areas = repositorio.areas();
        Map<String, String> nomesAreas = areas.stream().collect(Collectors.toMap(Item::codigo, Item::nome));
        Formatos fmt = new Formatos(hoje, nomesAreas);
        List<Item> niveis = repositorio.escolaridades();
        List<Item> regioes = repositorio.regioes();
        List<Uf> ufs = repositorio.ufs();
        List<Municipio> municipios = repositorio.municipios(concursos.stream()
                .map(Concurso::municipioIbge).filter(Objects::nonNull).distinct().toList());
        List<TipoIsencao> tipos = repositorio.tiposIsencao(CatalogoIsencoes.documentos(propriedades.isencoes()));
        String atualizacao = repositorio.ultimaColeta().map(fmt::dataHora).orElse("");

        Paginas paginas = new Paginas(templates, propriedades.urlBase(), fmt, atualizacao);
        Map<String, String> arquivos = new LinkedHashMap<>();
        List<String> urls = new ArrayList<>();
        PaginaGerada.adicionar(arquivos, urls, paginas.inicio(
                Ordenacao.telaInicial(concursos, hoje), Ordenacao.isencaoEmPrazo(concursos, hoje), concursos.size()));
        PaginaGerada.adicionar(arquivos, urls, paginas.lista("/concursos/", "Todos os concursos",
                "Concursos públicos com inscrições abertas, previstos e com prazo para pedir isenção da taxa.",
                Ordenacao.lista(concursos, hoje), true, List.of()));

        for (Concurso c : concursos) {
            PaginaGerada.adicionar(arquivos, urls, paginas.concurso(c, tipos));
        }

        // Navegação geográfica: nacionais entram em todos os recortes; estaduais também nos municípios da UF.
        Map<String, Uf> ufPorSigla = ufs.stream().collect(Collectors.toMap(Uf::sigla, u -> u));
        Map<String, Long> porUf = concursos.stream().filter(c -> c.uf() != null && !c.nacional())
                .collect(Collectors.groupingBy(Concurso::uf, Collectors.counting()));
        long nacionais = concursos.stream().filter(Concurso::nacional).count();
        PaginaGerada.adicionar(arquivos, urls, paginas.brasil(regioes, ufs, porUf, nacionais));
        for (Item regiao : regioes) {
            List<Uf> doRegiao = ufs.stream().filter(u -> u.regiao().equals(regiao.codigo())).toList();
            Predicate<Concurso> naRegiao = c -> c.nacional()
                    || (c.uf() != null && ufPorSigla.containsKey(c.uf())
                    && ufPorSigla.get(c.uf()).regiao().equals(regiao.codigo()));
            PaginaGerada.adicionar(arquivos, urls, paginas.lista("/regiao/" + regiao.slug() + "/",
                    "Concursos na região " + regiao.nome(),
                    "Concursos abertos e previstos na região " + regiao.nome() + ", incluindo os nacionais.",
                    Ordenacao.lista(filtrar(concursos, naRegiao), hoje), false,
                    doRegiao.stream().map(u -> new Paginas.Atalho(u.nome(), "/estado/" + u.slug() + "/",
                            porUf.getOrDefault(u.sigla(), 0L))).toList()));
        }
        for (Uf uf : ufs) {
            List<Paginas.Atalho> cidades = municipios.stream().filter(m -> m.uf().equals(uf.sigla()))
                    .map(m -> new Paginas.Atalho(m.nome(), caminhoMunicipio(uf, m), concursos.stream()
                            .filter(c -> Objects.equals(c.municipioIbge(), m.codigoIbge())).count()))
                    .toList();
            PaginaGerada.adicionar(arquivos, urls, paginas.lista("/estado/" + uf.slug() + "/",
                    "Concursos em " + uf.nome() + " (" + uf.sigla() + ")",
                    "Concursos abertos e previstos em " + uf.nome() + ": estaduais, municipais e nacionais.",
                    Ordenacao.lista(filtrar(concursos, c -> c.nacional() || uf.sigla().equals(c.uf())), hoje), false,
                    cidades));
            for (Municipio m : municipios.stream().filter(m -> m.uf().equals(uf.sigla())).toList()) {
                Predicate<Concurso> naCidade = c -> c.nacional()
                        || (uf.sigla().equals(c.uf()) && !"MUNICIPAL".equals(c.abrangencia()))
                        || Objects.equals(c.municipioIbge(), m.codigoIbge());
                PaginaGerada.adicionar(arquivos, urls, paginas.lista(caminhoMunicipio(uf, m),
                        "Concursos em " + m.nome() + " (" + uf.sigla() + ")",
                        "Concursos da prefeitura e de órgãos de " + m.nome() + ", estaduais de " + uf.nome()
                                + " e nacionais.",
                        Ordenacao.lista(filtrar(concursos, naCidade), hoje), false, List.of()));
            }
        }

        List<Paginas.Atalho> atalhosAreas = new ArrayList<>();
        for (Item area : areas) {
            List<Concurso> daArea = filtrar(concursos, c -> c.areas().contains(area.codigo()));
            if (!daArea.isEmpty()) {
                String caminho = "/area/" + area.slug() + "/";
                atalhosAreas.add(new Paginas.Atalho(area.nome(), caminho, daArea.size()));
                PaginaGerada.adicionar(arquivos, urls, paginas.lista(caminho, "Concursos na área " + area.nome(),
                        "Concursos abertos e previstos com cargos na área " + area.nome() + ".",
                        Ordenacao.lista(daArea, hoje), false, List.of()));
            }
        }
        for (Item nivel : niveis) {
            List<Concurso> doNivel = filtrar(concursos, c -> c.escolaridades().contains(nivel.codigo()));
            if (!doNivel.isEmpty()) {
                PaginaGerada.adicionar(arquivos, urls, paginas.lista("/nivel/" + nivel.slug() + "/",
                        "Concursos de nível " + fmt.nivel(nivel.codigo()).toLowerCase(),
                        "Concursos abertos e previstos para quem tem " + nivel.nome().toLowerCase() + ".",
                        Ordenacao.lista(doNivel, hoje), false, List.of()));
            }
        }

        Map<String, List<Concurso>> porTipo = new LinkedHashMap<>();
        for (TipoIsencao tipo : tipos) {
            porTipo.put(tipo.codigo(), concursos.stream()
                    .filter(c -> c.isencoes().stream().anyMatch(i -> i.codigo().equals(tipo.codigo())))
                    .sorted(Comparator.comparing((Concurso c) -> !c.isencaoEmPrazo(hoje))
                            .thenComparing(Ordenacao.POR_PROVA))
                    .toList());
        }
        PaginaGerada.adicionar(arquivos, urls, paginas.isencoes(tipos, porTipo, Ordenacao.isencaoEmPrazo(concursos, hoje)));
        for (TipoIsencao tipo : tipos) {
            PaginaGerada.adicionar(arquivos, urls, paginas.isencao(tipo, porTipo.get(tipo.codigo())));
        }
        PaginaGerada.adicionar(arquivos, urls, paginas.texto("/sobre/", "sobre", "Sobre o NqnTech Concursos",
                "De onde vêm as informações, como o site é atualizado e quais são os limites."));
        PaginaGerada.adicionar(arquivos, urls, paginas.texto("/privacidade/", "privacidade", "Privacidade",
                "Que dados o NqnTech Concursos trata e como."));
        arquivos.put("404.html", paginas.naoEncontrada());

        arquivos.put("busca.json", BuscaJson.gerar(concursos, fmt));
        arquivos.put("sitemap.xml", Sitemap.gerar(propriedades.urlBase(), urls, hoje));
        arquivos.put("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: " + propriedades.urlBase() + "/sitemap.xml\n");
        return arquivos;
    }

    static String caminhoMunicipio(Uf uf, Municipio m) {
        return "/municipio/" + uf.slug() + "/" + m.slug() + "/";
    }

    private static List<Concurso> filtrar(List<Concurso> concursos, Predicate<Concurso> filtro) {
        return concursos.stream().filter(filtro).toList();
    }

    private void gravar(Map<String, String> arquivos) throws IOException {
        Path saida = propriedades.saida();
        apagar(saida);
        Files.createDirectories(saida);
        for (Map.Entry<String, String> arquivo : arquivos.entrySet()) {
            Path destino = saida.resolve(arquivo.getKey()).normalize();
            if (!destino.startsWith(saida.normalize())) {
                throw new IllegalStateException("caminho fora da pasta do site: " + arquivo.getKey());
            }
            Files.createDirectories(destino.getParent());
            Files.writeString(destino, arquivo.getValue(), StandardCharsets.UTF_8);
        }
        copiarEstaticos(saida);
    }

    private static void copiarEstaticos(Path saida) throws IOException {
        Resource[] recursos = new PathMatchingResourcePatternResolver().getResources("classpath*:static/**");
        for (Resource recurso : recursos) {
            if (!recurso.isReadable() || recurso.getFilename() == null || recurso.getFilename().isBlank()) {
                continue;
            }
            String url = recurso.getURL().toString();
            String relativo = url.substring(url.lastIndexOf("static/") + "static/".length());
            if (relativo.isEmpty() || relativo.endsWith("/")) {
                continue;
            }
            Path destino = saida.resolve(relativo).normalize();
            Files.createDirectories(destino.getParent());
            try (InputStream entrada = recurso.getInputStream()) {
                Files.copy(entrada, destino, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            }
        }
    }

    private static void apagar(Path pasta) throws IOException {
        if (!Files.exists(pasta)) {
            return;
        }
        try (Stream<Path> caminhos = Files.walk(pasta)) {
            for (Path caminho : caminhos.sorted(Comparator.reverseOrder()).toList()) {
                Files.delete(caminho);
            }
        }
    }

    /** Página pronta: URL pública (com barra final) e HTML. */
    public record PaginaGerada(String url, String html) {

        static void adicionar(Map<String, String> arquivos, List<String> urls, PaginaGerada pagina) {
            String arquivo = pagina.url().equals("/") ? "index.html" : pagina.url().substring(1) + "index.html";
            if (arquivos.putIfAbsent(arquivo, pagina.html()) != null) {
                throw new IllegalStateException("duas páginas no mesmo endereço: " + pagina.url());
            }
            urls.add(pagina.url());
        }
    }
}

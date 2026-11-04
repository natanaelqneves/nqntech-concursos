package br.com.nqntech.site.geracao;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.thymeleaf.TemplateEngine;
import org.thymeleaf.context.Context;

import br.com.nqntech.site.dados.Concurso;
import br.com.nqntech.site.dados.Item;
import br.com.nqntech.site.dados.TipoIsencao;
import br.com.nqntech.site.dados.Uf;
import br.com.nqntech.site.geracao.GeradorSite.PaginaGerada;

/** Monta cada página a partir dos templates em {@code resources/templates}. */
public class Paginas {

    /** Link de navegação com contador ("Paraíba (3)"). */
    public record Atalho(String nome, String url, long quantidade) {}

    /** Metadados de SEO de uma página. */
    public record Meta(String titulo, String descricao, String url, String canonica, String jsonLd) {}

    public record Site(String nome, String urlBase, String atualizacao) {}

    private final TemplateEngine templates;
    private final String urlBase;
    private final Formatos fmt;
    private final Site site;

    public Paginas(TemplateEngine templates, String urlBase, Formatos fmt, String atualizacao) {
        this.templates = templates;
        this.urlBase = urlBase;
        this.fmt = fmt;
        this.site = new Site(GeradorSite.NOME, urlBase, atualizacao);
    }

    public PaginaGerada inicio(List<Concurso> abertos, List<Concurso> isencao, int total) {
        String descricao = "Concursos públicos com inscrições abertas em todo o Brasil, com resumo simples de cada "
                + "edital e prazos para pedir isenção da taxa. Informação gratuita.";
        Map<String, Object> jsonLd = new LinkedHashMap<>();
        jsonLd.put("@context", "https://schema.org");
        jsonLd.put("@type", "WebSite");
        jsonLd.put("name", GeradorSite.NOME);
        jsonLd.put("url", urlBase + "/");
        jsonLd.put("description", descricao);
        Meta meta = new Meta(GeradorSite.NOME + ": concursos com inscrições abertas", descricao, "/",
                urlBase + "/", Json.escrever(jsonLd));
        return render("inicio", meta, Map.of("abertos", abertos, "isencao", isencao, "total", total));
    }

    public PaginaGerada lista(String url, String titulo, String descricao, List<Concurso> concursos, boolean filtros,
            List<Atalho> atalhos) {
        Meta meta = new Meta(titulo + " | " + GeradorSite.NOME, descricao, url, urlBase + url,
                Json.escrever(trilha(List.of(new Atalho(titulo, url, 0)))));
        return render("lista", meta, Map.of("titulo", titulo, "descricao", descricao, "concursos", concursos,
                "filtros", filtros, "atalhos", atalhos));
    }

    public PaginaGerada concurso(Concurso c, List<TipoIsencao> tipos) {
        String url = "/concurso/" + c.slug() + "/";
        String titulo = c.nomeExibicao() + (c.unificado() ? " (CNU)" : "");
        String descricao = c.resumo().length() > 300 ? c.resumo().substring(0, 297) + "..." : c.resumo();
        Meta meta = new Meta("Concurso " + titulo + " | " + GeradorSite.NOME, descricao, url, urlBase + url,
                Json.escrever(trilha(List.of(new Atalho("Concursos", "/concursos/", 0), new Atalho(titulo, url, 0)))));
        Map<String, TipoIsencao> porCodigo = tipos.stream()
                .collect(Collectors.toMap(TipoIsencao::codigo, Function.identity()));
        Map<String, Object> variaveis = new LinkedHashMap<>();
        variaveis.put("c", c);
        variaveis.put("tipos", porCodigo);
        variaveis.put("linkOficial", UrlSegura.http(c.linkOficial()));
        variaveis.put("linkInscricao", UrlSegura.http(c.linkInscricao()));
        variaveis.put("linkEdital", UrlSegura.http(c.linkEdital()));
        variaveis.put("titulo", titulo);
        return render("concurso", meta, variaveis);
    }

    public PaginaGerada brasil(List<Item> regioes, List<Uf> ufs, Map<String, Long> porUf, long nacionais) {
        String descricao = "Escolha a região, o estado ou o município para ver os concursos abertos e previstos.";
        Map<String, List<Atalho>> estados = new LinkedHashMap<>();
        for (Item regiao : regioes) {
            estados.put(regiao.codigo(), ufs.stream().filter(u -> u.regiao().equals(regiao.codigo()))
                    .map(u -> new Atalho(u.nome(), "/estado/" + u.slug() + "/", porUf.getOrDefault(u.sigla(), 0L)))
                    .toList());
        }
        Meta meta = new Meta("Concursos por estado | " + GeradorSite.NOME, descricao, "/brasil/",
                urlBase + "/brasil/", Json.escrever(trilha(List.of(new Atalho("Brasil", "/brasil/", 0)))));
        return render("brasil", meta, Map.of("regioes", regioes, "estados", estados, "nacionais", nacionais));
    }

    public PaginaGerada isencoes(List<TipoIsencao> tipos, Map<String, List<Concurso>> porTipo, List<Concurso> emPrazo) {
        String descricao = "Quem pode pedir isenção da taxa de inscrição em concursos e quais editais abertos "
                + "preveem cada tipo. As regras mudam de um edital para outro: confira sempre o edital.";
        Meta meta = new Meta("Isenção da taxa de concursos | " + GeradorSite.NOME, descricao, "/isencoes/",
                urlBase + "/isencoes/", Json.escrever(trilha(List.of(new Atalho("Isenções", "/isencoes/", 0)))));
        return render("isencoes", meta, Map.of("tipos", tipos, "porTipo", porTipo, "emPrazo", emPrazo));
    }

    public PaginaGerada isencao(TipoIsencao tipo, List<Concurso> concursos) {
        String url = "/isencoes/" + tipo.slug() + "/";
        String descricao = "Isenção da taxa de concursos para " + tipo.nome().toLowerCase()
                + ": quem costuma ter, documentos usuais e concursos que preveem.";
        Meta meta = new Meta("Isenção da taxa: " + tipo.nome() + " | " + GeradorSite.NOME, descricao, url,
                urlBase + url, Json.escrever(trilha(List.of(new Atalho("Isenções", "/isencoes/", 0),
                        new Atalho(tipo.nome(), url, 0)))));
        return render("isencao", meta, Map.of("tipo", tipo, "concursos", concursos,
                "linkLei", java.util.Objects.requireNonNullElse(UrlSegura.http(tipo.linkOficial()), "")));
    }

    public PaginaGerada texto(String url, String fragmento, String titulo, String descricao) {
        Meta meta = new Meta(titulo + " | " + GeradorSite.NOME, descricao, url, urlBase + url,
                Json.escrever(trilha(List.of(new Atalho(titulo, url, 0)))));
        return render("texto", meta, Map.of("titulo", titulo, "fragmento", fragmento));
    }

    public String naoEncontrada() {
        Meta meta = new Meta("Página não encontrada | " + GeradorSite.NOME,
                "Esta página não existe ou o concurso já saiu do site.", "/404.html", "", "");
        return render("404", meta, Map.of()).html();
    }

    private Map<String, Object> trilha(List<Atalho> itens) {
        List<Map<String, Object>> elementos = new java.util.ArrayList<>();
        elementos.add(Map.of("@type", "ListItem", "position", 1, "name", "Início", "item", urlBase + "/"));
        for (int i = 0; i < itens.size(); i++) {
            elementos.add(Map.of("@type", "ListItem", "position", i + 2, "name", itens.get(i).nome(),
                    "item", urlBase + itens.get(i).url()));
        }
        Map<String, Object> jsonLd = new LinkedHashMap<>();
        jsonLd.put("@context", "https://schema.org");
        jsonLd.put("@type", "BreadcrumbList");
        jsonLd.put("itemListElement", elementos);
        return jsonLd;
    }

    private PaginaGerada render(String template, Meta meta, Map<String, Object> variaveis) {
        Context contexto = new Context(java.util.Locale.of("pt", "BR"));
        contexto.setVariable("site", site);
        contexto.setVariable("fmt", fmt);
        contexto.setVariable("meta", meta);
        contexto.setVariables(variaveis);
        return new PaginaGerada(meta.url(), templates.process(template, contexto));
    }
}

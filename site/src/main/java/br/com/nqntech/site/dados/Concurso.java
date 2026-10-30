package br.com.nqntech.site.dados;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

/** Concurso publicado, como o site o exibe. Textos vêm do banco e são dados não confiáveis: sempre escapar. */
public record Concurso(
        long id,
        String slug,
        String titulo,
        String orgao,
        String banca,
        String situacao,
        String abrangencia,
        String uf,
        Integer municipioIbge,
        String municipio,
        boolean unificado,
        LocalDate inscricaoInicio,
        LocalDate inscricaoFim,
        LocalDate dataProva,
        BigDecimal taxaMin,
        BigDecimal taxaMax,
        Integer totalVagas,
        BigDecimal salarioMax,
        List<String> escolaridades,
        List<String> areas,
        boolean temIsencao,
        LocalDate isencaoInicio,
        LocalDate isencaoFim,
        String resumo,
        String linkOficial,
        String linkInscricao,
        String linkEdital,
        OffsetDateTime atualizadoEm,
        List<Cargo> cargos,
        List<Evento> eventos,
        List<IsencaoPrevista> isencoes) {

    public String nomeExibicao() {
        return orgao != null && !orgao.isBlank() ? orgao : titulo;
    }

    public boolean nacional() {
        return "NACIONAL".equals(abrangencia);
    }

    public boolean inscricoesAbertas(LocalDate hoje) {
        return "INSCRICOES_ABERTAS".equals(situacao)
                && (inscricaoInicio == null || !inscricaoInicio.isAfter(hoje))
                && (inscricaoFim == null || !inscricaoFim.isBefore(hoje));
    }

    public boolean isencaoEmPrazo(LocalDate hoje) {
        return isencaoFim != null && !isencaoFim.isBefore(hoje) && (isencaoInicio == null || !isencaoInicio.isAfter(hoje));
    }

    public boolean temDisciplinas() {
        return cargos.stream().anyMatch(c -> !c.disciplinas().isEmpty());
    }

    public Concurso comDetalhes(List<Cargo> cargos, List<Evento> eventos, List<IsencaoPrevista> isencoes) {
        return new Concurso(id, slug, titulo, orgao, banca, situacao, abrangencia, uf, municipioIbge, municipio,
                unificado, inscricaoInicio, inscricaoFim, dataProva, taxaMin, taxaMax, totalVagas, salarioMax,
                escolaridades, areas, temIsencao, isencaoInicio, isencaoFim, resumo, linkOficial, linkInscricao,
                linkEdital, atualizadoEm, List.copyOf(cargos), List.copyOf(eventos), List.copyOf(isencoes));
    }
}

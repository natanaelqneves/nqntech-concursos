package br.com.nqntech.site.dados;

import java.time.LocalDate;

/** Linha do calendário; datas nulas são exibidas como "a definir". */
public record Evento(String evento, LocalDate inicio, LocalDate fim) {}

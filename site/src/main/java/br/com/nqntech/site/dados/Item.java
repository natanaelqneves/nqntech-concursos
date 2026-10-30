package br.com.nqntech.site.dados;

/** Entrada de catálogo (área, nível, região): código no banco, nome exibido e trecho da URL. */
public record Item(String codigo, String nome, String slug) {}

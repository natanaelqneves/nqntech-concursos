// Melhorias progressivas: o site funciona sem JavaScript. Nada aqui usa innerHTML com dados (só textContent).
(function () {
  "use strict";

  // Prazos de isenção: "faltam N dias", calculado no navegador para o HTML estático não envelhecer.
  function diasAte(iso) {
    var p = iso.split("-");
    var alvo = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    var hoje = new Date();
    hoje.setHours(0, 0, 0, 0);
    return Math.round((alvo - hoje) / 86400000);
  }

  function atualizarPrazos() {
    document.querySelectorAll("[data-prazo]").forEach(function (el) {
      var iso = el.getAttribute("data-prazo");
      if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return;
      var dias = diasAte(iso);
      el.textContent = dias < 0 ? "prazo de isenção encerrado"
        : dias === 0 ? "isenção: último dia hoje"
        : dias === 1 ? "isenção: falta 1 dia"
        : "isenção: faltam " + dias + " dias";
      if (dias >= 0 && dias <= 3) el.classList.add("prazo--urgente");
    });
  }

  // Botão claro/escuro: troca o atributo no <html> e lembra a escolha (tema.js aplica antes de desenhar).
  function iniciarTema() {
    var botao = document.getElementById("alternar-tema");
    if (!botao) return;
    var html = document.documentElement;
    function refletir() {
      var escuro = html.getAttribute("data-bs-theme") === "dark";
      botao.setAttribute("aria-pressed", String(escuro));
      botao.setAttribute("aria-label", escuro ? "Usar tema claro" : "Usar tema escuro");
    }
    botao.addEventListener("click", function () {
      var escuro = html.getAttribute("data-bs-theme") !== "dark";
      if (escuro) html.setAttribute("data-bs-theme", "dark"); else html.removeAttribute("data-bs-theme");
      try { localStorage.setItem("tema", escuro ? "dark" : "light"); } catch (e) { /* sem armazenamento */ }
      refletir();
    });
    refletir();
  }

  document.addEventListener("DOMContentLoaded", function () {
    atualizarPrazos();
    iniciarTema();
  });
})();

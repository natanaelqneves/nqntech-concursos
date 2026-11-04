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
      var texto = dias < 0 ? "prazo de isenção encerrado"
        : dias === 0 ? "isenção: último dia hoje"
        : dias === 1 ? "isenção: falta 1 dia"
        : "isenção: faltam " + dias + " dias";
      el.textContent = texto;
    });
  }

  // Filtros de /concursos/: mostram e escondem os cartões já presentes na página.
  function iniciarFiltros() {
    var form = document.getElementById("filtros");
    var grade = document.getElementById("resultados");
    if (!form || !grade) return;
    var cartoes = Array.prototype.slice.call(grade.querySelectorAll(".cartao"));
    var resultado = form.querySelector(".filtros__resultado");

    function preencher(select, valores) {
      valores.sort(function (a, b) { return a.rotulo.localeCompare(b.rotulo, "pt-BR"); }).forEach(function (v) {
        var op = document.createElement("option");
        op.value = v.valor;
        op.textContent = v.rotulo;
        select.appendChild(op);
      });
    }
    var ufs = {}, areas = {};
    cartoes.forEach(function (c) {
      if (c.dataset.uf) ufs[c.dataset.uf] = true;
      (c.dataset.areas || "").split(" ").forEach(function (a) { if (a) areas[a] = true; });
    });
    preencher(form.elements.uf, Object.keys(ufs).map(function (u) { return { valor: u, rotulo: u }; }));
    preencher(form.elements.area, Object.keys(areas).map(function (a) {
      return { valor: a, rotulo: a.charAt(0) + a.slice(1).toLowerCase().replace(/_/g, " ") };
    }));

    var params = new URLSearchParams(window.location.search);
    ["q", "uf", "area", "nivel", "situacao"].forEach(function (n) { if (params.get(n)) form.elements[n].value = params.get(n); });
    if (params.get("isencao")) form.elements.isencao.checked = true;

    function aplicar() {
      var q = form.elements.q.value.trim().toLowerCase();
      var uf = form.elements.uf.value, area = form.elements.area.value, nivel = form.elements.nivel.value;
      var situacao = form.elements.situacao.value, isencao = form.elements.isencao.checked;
      var visiveis = 0;
      cartoes.forEach(function (c) {
        var d = c.dataset;
        var ok = (!q || (d.busca || "").indexOf(q) !== -1)
          && (!uf || d.uf === uf || d.abrangencia === "NACIONAL")
          && (!area || (" " + d.areas + " ").indexOf(" " + area + " ") !== -1)
          && (!nivel || (" " + d.niveis + " ").indexOf(" " + nivel + " ") !== -1)
          && (!situacao || d.situacao === situacao)
          && (!isencao || d.isencao === "true");
        c.hidden = !ok;
        if (ok) visiveis++;
      });
      resultado.textContent = visiveis === 1 ? "1 concurso" : visiveis + " concursos";
      var novos = new URLSearchParams();
      ["q", "uf", "area", "nivel", "situacao"].forEach(function (n) { if (form.elements[n].value) novos.set(n, form.elements[n].value); });
      if (isencao) novos.set("isencao", "1");
      var busca = novos.toString();
      history.replaceState(null, "", busca ? "?" + busca : window.location.pathname);
    }
    form.addEventListener("input", aplicar);
    form.addEventListener("submit", function (e) { e.preventDefault(); });
    form.hidden = false;
    aplicar();
  }

  document.addEventListener("DOMContentLoaded", function () {
    atualizarPrazos();
    iniciarFiltros();
  });

  // Botão claro/escuro: troca o atributo no <html> e lembra a escolha (tema.js aplica antes de desenhar).
  function iniciarTema() {
    var botao = document.getElementById("alternar-tema");
    if (!botao) return;
    var html = document.documentElement;
    function refletir() {
      var escuro = html.getAttribute("data-tema") === "dark";
      botao.setAttribute("aria-pressed", String(escuro));
      botao.setAttribute("aria-label", escuro ? "Usar tema claro" : "Usar tema escuro");
    }
    botao.addEventListener("click", function () {
      var escuro = html.getAttribute("data-tema") !== "dark";
      if (escuro) html.setAttribute("data-tema", "dark"); else html.removeAttribute("data-tema");
      try { localStorage.setItem("tema", escuro ? "dark" : "light"); } catch (e) { /* sem armazenamento */ }
      refletir();
    });
    refletir();
  }

  document.addEventListener("DOMContentLoaded", iniciarTema);

  // Menu do celular: o botão recolhe e abre a navegação; Esc fecha; abrir um submenu fecha o outro.
  function iniciarMenu() {
    var botao = document.getElementById("abrir-menu");
    var nav = document.getElementById("menu-principal");
    if (!botao || !nav) return;
    function definir(aberto) {
      nav.classList.toggle("navegacao--aberta", aberto);
      botao.setAttribute("aria-expanded", String(aberto));
      botao.setAttribute("aria-label", aberto ? "Fechar menu" : "Abrir menu");
    }
    botao.addEventListener("click", function () { definir(!nav.classList.contains("navegacao--aberta")); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        definir(false);
        nav.querySelectorAll("details[open]").forEach(function (d) { d.open = false; });
      }
    });
    var submenus = nav.querySelectorAll("details.submenu");
    submenus.forEach(function (d) {
      d.addEventListener("toggle", function () {
        if (d.open) submenus.forEach(function (o) { if (o !== d) o.open = false; });
      });
    });
    document.addEventListener("click", function (e) {
      if (!nav.contains(e.target)) submenus.forEach(function (d) { d.open = false; });
    });
  }
  document.addEventListener("DOMContentLoaded", iniciarMenu);
})();

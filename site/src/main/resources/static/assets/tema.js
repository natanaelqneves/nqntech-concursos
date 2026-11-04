// Tema: claro por padrão; escuro só se a pessoa escolheu (guardado no navegador). Roda antes do CSS desenhar.
(function () {
  document.documentElement.classList.add("js"); // o CSS só recolhe o menu quando há JS para reabri-lo
  try {
    if (localStorage.getItem("tema") === "dark") document.documentElement.setAttribute("data-tema", "dark");
  } catch (e) { /* navegação privada sem localStorage: fica no claro */ }
})();

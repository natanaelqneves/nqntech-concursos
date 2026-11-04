// Tema: claro por padrão; escuro só se a pessoa escolheu (guardado no navegador). Roda antes do CSS desenhar.
// Usa o atributo de cor do Bootstrap 5.3 (data-bs-theme).
(function () {
  try {
    if (localStorage.getItem("tema") === "dark") document.documentElement.setAttribute("data-bs-theme", "dark");
  } catch (e) { /* navegação privada sem localStorage: fica no claro */ }
})();

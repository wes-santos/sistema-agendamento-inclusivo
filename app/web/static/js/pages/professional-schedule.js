// Navegação simples da agenda (prev/next/hoje) e submissão reativa do "view"
(() => {
  const d = document;
  const view = d.getElementById("view");
  if (view) {
    view.addEventListener("change", () => {
      // submete o form para alternar entre dia/semana
      const form = d.querySelector(".sched-controls__form");
      if (form) form.submit();
    });
  }

  // Garante que links de navegação respeitam os filtros atuais do formulário
  const form = d.querySelector(".sched-controls__form");
  if (!form) return;

  function buildUrl(base) {
    const url = new URL(base, window.location.origin);
    const data = new FormData(form);
    for (const [k, v] of data.entries()) {
      if (v !== "") url.searchParams.set(k, v);
      else url.searchParams.delete(k);
    }
    return url.toString();
  }

  d.querySelectorAll("[data-nav]").forEach((a) => {
    const baseHref = a.getAttribute("href");
    if (!baseHref) return;
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      window.location.assign(buildUrl(baseHref));
    });
  });
})();

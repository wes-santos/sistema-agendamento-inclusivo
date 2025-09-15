// Navegação da agenda (prev/next/hoje) e submissão reativa do "view"
(() => {
  const d = document;
  

  const applyBtn = d.querySelector("button[type='submit']");
  if(applyBtn) {
    applyBtn.addEventListener("click", () => {
        const form = d.querySelector("form.sched-controls__form");
        if (form) form.submit();
    });
  }

  // Garante que links de navegação respeitam os filtros atuais do formulário
  const form = d.querySelector(".sched-controls__form");
  if (!form) return;

  const dateFrom = d.getElementById("date_from");
  const dateTo = d.getElementById("date_to");
  function parseDate(val) {
    // val expected: YYYY-MM-DD
    try {
      if (!val) return new Date();
      const [y, m, d] = val.split("-").map((x) => parseInt(x, 10));
      return new Date(y, (m || 1) - 1, d || 1);
    } catch (_) {
      return new Date();
    }
  }

  function toISODate(dt) {
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, "0");
    const d2 = String(dt.getDate()).padStart(2, "0");
    return `${y}-${m}-${d2}`;
  }

  d.querySelectorAll("[data-nav]").forEach((a) => {
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      const which = a.getAttribute("data-nav");
      const view = (viewSel && viewSel.value) || "week";
      const baseFrom = parseDate(dateFrom && dateFrom.value);
      const baseTo = dateTo && dateTo.value ? parseDate(dateTo.value) : null;

      if (which === "today") {
        // Set interval to show only the current day
        const today = new Date();
        const iso = toISODate(today);
        if (dateFrom) dateFrom.value = iso;
        if (dateTo) dateTo.value = iso;
        form.submit();
        return;
      }

      // Step size: week when in week view, otherwise one day
      const step = view === "week" ? 7 : 1;
      const sign = which === "prev" ? -1 : 1;
      const delta = step * sign;

      if (view === "week") {
        const from = new Date(baseFrom.getFullYear(), baseFrom.getMonth(), baseFrom.getDate() + delta);
        const to = baseTo
          ? new Date(baseTo.getFullYear(), baseTo.getMonth(), baseTo.getDate() + delta)
          : new Date(from.getFullYear(), from.getMonth(), from.getDate() + 6);
        if (dateFrom) dateFrom.value = toISODate(from);
        if (dateTo) dateTo.value = toISODate(to);
      } else {
        const target = new Date(baseFrom.getFullYear(), baseFrom.getMonth(), baseFrom.getDate() + delta);
        if (dateFrom) dateFrom.value = toISODate(target);
        if (dateTo) dateTo.value = "";
      }
      form.submit();
    });
  });
})();

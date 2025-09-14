// static/js/pages/family-appointments.js
(() => {
  const d = document;
  const dialog = d.getElementById("cancel-modal");
  let pendingCancelUrl = null;

  function openCancelDialog(url) {
    pendingCancelUrl = url;

    // Se o navegador suporta <dialog>, usa a UX bonita; senão, fallback pro confirm() nativo
    if (dialog && typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      const ok = window.confirm(
        "Tem certeza que deseja cancelar este agendamento? Esta ação não pode ser desfeita."
      );
      if (ok) window.location.assign(pendingCancelUrl);
      pendingCancelUrl = null;
    }
  }

  // Event delegation: captura cliques em qualquer botão com data-action="cancel"
  d.addEventListener("click", (ev) => {
    const btn = ev.target.closest('button[data-action="cancel"]');
    if (!btn) return;

    ev.preventDefault();
    const url = btn.getAttribute("data-cancel-url");
    if (!url) return;

    openCancelDialog(url);
  });

  // Quando o modal fechar, verifica o retorno (definido pelos <button value="..."> do macro confirm)
  if (dialog) {
    dialog.addEventListener("close", () => {
      if (dialog.returnValue === "confirm" && pendingCancelUrl) {
        // Bloqueia o botão para evitar clique duplo e navega
        const confirmBtn = dialog.querySelector('button[value="confirm"]');
        if (confirmBtn) confirmBtn.disabled = true;

        // GET /cancel/{token} (conforme seu contrato)
        window.location.assign(pendingCancelUrl);
      }
      pendingCancelUrl = null;
    });

    // Opcional: se quiser fechar com ESC sempre, o <dialog> já faz; aqui só garantimos limpar estado
    dialog.addEventListener("cancel", () => {
      pendingCancelUrl = null;
    });
  }
})();

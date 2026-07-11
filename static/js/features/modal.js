export function createModal(ctx) {
  const { ui } = ctx;
  let activeResolver = null;
  let lastFocusedElement = null;
  let currentOptions = null;

  const modal = {
    elements() {
      return {
        backdrop: ui.byKey("appModalBackdrop"),
        title: ui.byKey("modalTitle"),
        description: ui.byKey("modalDescription"),
        label: ui.byKey("modalLabel"),
        input: ui.byKey("modalInput"),
        textarea: ui.byKey("modalTextarea"),
        hint: ui.byKey("modalHint"),
        cancel: ui.byKey("modalCancel"),
        confirm: ui.byKey("modalConfirm"),
        close: ui.byKey("modalClose"),
      };
    },

    openInput(options = {}) {
      const defaults = {
        title: "Input",
        description: "",
        label: "Value",
        defaultValue: "",
        placeholder: "",
        hint: "",
        confirmText: "OK",
        cancelText: "Cancel",
        multiline: false,
        required: true,
        readOnly: false,
      };
      currentOptions = { ...defaults, ...options };
      const els = modal.elements();
      if (!els.backdrop) return Promise.resolve(null);

      lastFocusedElement = document.activeElement;
      els.title.textContent = currentOptions.title;
      els.description.textContent = currentOptions.description;
      els.description.hidden = !currentOptions.description;
      els.label.textContent = currentOptions.label;
      els.hint.textContent = currentOptions.hint;
      els.hint.classList.remove("error");
      els.cancel.textContent = currentOptions.cancelText;
      els.confirm.textContent = currentOptions.confirmText;

      const activeField = currentOptions.multiline ? els.textarea : els.input;
      const inactiveField = currentOptions.multiline ? els.input : els.textarea;
      activeField.value = currentOptions.initialValue ?? currentOptions.defaultValue ?? "";
      activeField.placeholder = currentOptions.placeholder || "";
      activeField.readOnly = Boolean(currentOptions.readOnly);
      activeField.hidden = false;
      inactiveField.hidden = true;
      inactiveField.readOnly = false;

      els.backdrop.hidden = false;
      document.body.classList.add("modal-open");
      setTimeout(() => activeField.focus(), 0);

      return new Promise((resolve) => {
        activeResolver = resolve;
      });
    },

    value() {
      const els = modal.elements();
      const field = currentOptions?.multiline ? els.textarea : els.input;
      return field.value.trim();
    },

    showError(message) {
      const els = modal.elements();
      els.hint.textContent = message;
      els.hint.classList.add("error");
      const field = currentOptions?.multiline ? els.textarea : els.input;
      field.focus();
    },

    confirm() {
      if (!activeResolver || !currentOptions) return;
      const value = modal.value();
      if (currentOptions.required && !value) {
        modal.showError("Please enter a value before continuing.");
        return;
      }
      modal.close(value);
    },

    cancel() {
      modal.close(null);
    },

    close(result) {
      const els = modal.elements();
      if (els.backdrop) els.backdrop.hidden = true;
      document.body.classList.remove("modal-open");
      const resolve = activeResolver;
      activeResolver = null;
      currentOptions = null;
      if (lastFocusedElement?.focus) lastFocusedElement.focus();
      lastFocusedElement = null;
      if (resolve) resolve(result);
    },

    bind() {
      const els = modal.elements();
      if (!els.backdrop) return;
      els.confirm.onclick = () => modal.confirm();
      els.cancel.onclick = () => modal.cancel();
      els.close.onclick = () => modal.cancel();
      els.backdrop.addEventListener("click", (event) => {
        if (event.target === els.backdrop) modal.cancel();
      });
      document.addEventListener("keydown", (event) => {
        if (els.backdrop.hidden) return;
        if (event.key === "Escape") {
          event.preventDefault();
          modal.cancel();
          return;
        }
        if (!currentOptions?.multiline && event.key === "Enter") {
          event.preventDefault();
          modal.confirm();
          return;
        }
        if (currentOptions?.multiline && event.key === "Enter" && event.ctrlKey) {
          event.preventDefault();
          modal.confirm();
        }
      });
    },
  };

  return modal;
}

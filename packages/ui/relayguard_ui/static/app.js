// Copy button: copies the approved reply text, then submits the form that records the copy event.
document.addEventListener("DOMContentLoaded", () => {
  for (const button of document.querySelectorAll("[data-copy-target]")) {
    button.addEventListener("click", async (event) => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      event.preventDefault();
      try {
        await navigator.clipboard.writeText(target.textContent);
        button.form.submit();
      } catch (err) {
        const range = document.createRange();
        range.selectNodeContents(target);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        button.textContent = "選択しました。Ctrl+Cでコピーしてください";
      }
    });
  }
});

// Long-running forms (Claude reads for up to 5 minutes): say that work is under way and block a
// second submit. The server still owns the outcome; this only changes what the page shows meanwhile.
document.addEventListener("DOMContentLoaded", () => {
  for (const form of document.querySelectorAll("form[data-busy]")) {
    form.addEventListener("submit", () => {
      if (form.getAttribute("aria-busy") === "true") return;
      form.setAttribute("aria-busy", "true");
      for (const button of form.querySelectorAll("button[type=submit]")) button.disabled = true;
      const status = document.createElement("p");
      status.className = "busy";
      status.setAttribute("role", "status");
      status.textContent = form.dataset.busy;
      form.append(status);
    });
  }
});

// Coming back with the browser's Back button can restore a page frozen mid-submit: unfreeze it.
window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  for (const form of document.querySelectorAll("form[aria-busy=true]")) {
    form.removeAttribute("aria-busy");
    for (const button of form.querySelectorAll("button[type=submit]")) button.disabled = false;
    for (const status of form.querySelectorAll(".busy")) status.remove();
  }
});

// Manual registration: select text in the mail, add it as a quoted item, fill only the fields its kind
// uses. Cards are numbered 1..6 into the server's existing field names (kind_1, quote_1, ...); fields
// of the other kinds are disabled so they are not sent. The server re-checks every quote against the mail.
document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-manual-form]");
  if (!form) return;
  const MAX_ITEMS = 6;
  const body = form.querySelector("[data-manual-body]");
  const list = form.querySelector("[data-items]");
  const template = form.querySelector("[data-item-template]");
  const hint = form.querySelector("[data-manual-hint]");
  const addQuote = form.querySelector("[data-add-quote]");
  const addItem = form.querySelector("[data-add-item]");
  const defaultHint = hint.textContent;

  const guessKind = (text) => {
    if (text.includes("?")) return "question";
    if (/[$€£¥]\s?\d|\b(USD|EUR|GBP|JPY|CAD|AUD|CHF)\b|\d\s?(dollars?|euros?)\b/i.test(text)) return "money";
    if (/\b(\d{4}-\d{2}-\d{2}|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december|by the end)\b/i.test(text)) return "date";
    return "question";
  };

  const applyKind = (item) => {
    const kind = item.querySelector("[data-kind-select]").value;
    for (const group of item.querySelectorAll("[data-kinds]")) {
      const on = group.dataset.kinds.split(" ").includes(kind);
      group.hidden = !on;
      for (const field of group.querySelectorAll("input, select, textarea")) field.disabled = !on;
    }
  };

  const renumber = () => {
    const items = [...list.children];
    items.forEach((item, index) => {
      const n = index + 1;
      item.querySelector("[data-item-no]").textContent = `項目${n}`;
      for (const field of item.querySelectorAll("[data-field]")) field.name = `${field.dataset.field}_${n}`;
    });
    const full = items.length >= MAX_ITEMS;
    addQuote.disabled = full;
    addItem.disabled = full;
    hint.textContent = full ? `項目は${MAX_ITEMS}件までです。不要な項目を削除すると追加できます。` : defaultHint;
  };

  const add = (quote) => {
    if (list.children.length >= MAX_ITEMS) return;
    const item = template.content.firstElementChild.cloneNode(true);
    const select = item.querySelector("[data-kind-select]");
    item.querySelector('[data-field="quote"]').value = quote;
    select.value = quote ? guessKind(quote) : "question";
    select.addEventListener("change", () => applyKind(item));
    item.querySelector("[data-remove-item]").addEventListener("click", () => {
      item.remove();
      renumber();
      (list.lastElementChild?.querySelector("[data-kind-select]") || addQuote).focus();
    });
    list.append(item);
    applyKind(item);
    renumber();
    select.focus();
  };

  addQuote.addEventListener("click", () => {
    const quote = body.value.slice(body.selectionStart, body.selectionEnd).trim();
    if (!quote) {
      hint.textContent = "先に、本文の中で引用したい部分をなぞって選んでください。";
      body.focus();
      return;
    }
    add(quote);
  });
  addItem.addEventListener("click", () => add(""));
});

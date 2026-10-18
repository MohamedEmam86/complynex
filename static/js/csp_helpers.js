/**
 * CSP inline-handler polyfill.
 * Replaces onclick/onsubmit/onchange attributes (blocked by Content-Security-Policy)
 * with delegated event listeners keyed on data-* attributes.
 */
(function () {
  'use strict';

  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-action]');
    if (el) {
      var action = el.dataset.action;
      if (action === 'print')  { window.print(); return; }
      if (action === 'close')  { window.close(); return; }
      if (action === 'back')   { history.back(); return; }
    }

    // data-confirm on buttons / links (was onclick="return confirm('...')")
    var confirmEl = e.target.closest('[data-confirm]:not(form)');
    if (confirmEl) {
      if (!confirm(confirmEl.dataset.confirm)) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
      return;
    }

    // data-href on a row (was onclick="window.location='...'").
    // Ignored when the click landed on a real link, button or input inside the
    // row, otherwise the row handler would hijack those.
    var row = e.target.closest('[data-href]');
    if (row && !e.target.closest('a, button, input, select, label')) {
      window.location = row.dataset.href;
      return;
    }

    // data-onclick-fn — call a named global function (no-arg)
    var fnEl = e.target.closest('[data-onclick-fn]');
    if (fnEl) {
      var fn = fnEl.dataset.onclickFn;
      if (typeof window[fn] === 'function') {
        window[fn]();
      }
    }
  });

  // data-confirm on <form> elements (was onsubmit="return confirm('...')")
  document.addEventListener('submit', function (e) {
    var form = e.target.closest('form[data-confirm]');
    if (form && !confirm(form.dataset.confirm)) {
      e.preventDefault();
    }
  }, true);

  // data-auto-submit — submit closest form on change (was onchange="this.form.submit()")
  document.addEventListener('change', function (e) {
    if (e.target.matches('[data-auto-submit]')) {
      var form = e.target.closest('form');
      if (form) form.submit();
    }
  });

}());

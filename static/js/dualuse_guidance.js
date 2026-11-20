/* Dual-use guidance: "check your value against the threshold" forms (.du-check). No inline handlers (CSP);
   the endpoint comes from data-url. The check runs on the server (no external call). */
(function () {
  'use strict';
  var ar = (document.documentElement.getAttribute('lang') || '').indexOf('ar') === 0 ||
           document.documentElement.getAttribute('dir') === 'rtl';

  function bind(form) {
    var sel = form.querySelector('select[name="n"]');
    var unit = form.querySelector('input[name="u"]');
    var out = form.querySelector('.du-check-out');
    if (sel && unit) {
      sel.addEventListener('change', function () {
        var o = sel.options[sel.selectedIndex];
        unit.value = o ? (o.getAttribute('data-unit') || '') : '';
      });
    }
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var v = form.querySelector('input[name="v"]').value;
      var url = form.getAttribute('data-url') + '?d=' + encodeURIComponent(form.getAttribute('data-doc')) +
                '&n=' + encodeURIComponent(sel ? sel.value : '0') + '&v=' + encodeURIComponent(v) +
                '&u=' + encodeURIComponent(unit ? unit.value : '');
      out.textContent = '…';
      out.className = 'col-12 du-check-out small';
      fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          out.textContent = (ar && j.ar) ? j.ar : (j.en || '');
          out.className = 'col-12 du-check-out small du-check-' + (j.result || 'unknown');
        })
        .catch(function () { out.textContent = ar ? 'تعذر التحقق.' : 'The check failed.'; });
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll('form.du-check'), bind);
})();

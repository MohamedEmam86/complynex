/* Fit & proper form: show items/sections only when their condition holds (data-show-if='{"item": "value"}'). */
(function () {
  var form = document.getElementById('fpform');
  if (!form) return;
  function value(name) {
    var els = form.querySelectorAll('[name="' + name + '"]');
    var out = [];
    els.forEach(function (el) {
      if ((el.type === 'radio' || el.type === 'checkbox')) { if (el.checked) out.push(el.value); }
      else if (el.value) out.push(el.value);
    });
    return out;
  }
  function apply() {
    document.querySelectorAll('[data-show-if]').forEach(function (el) {
      var cond = {};
      try { cond = JSON.parse(el.getAttribute('data-show-if') || '{}'); } catch (e) { cond = {}; }
      var ok = Object.keys(cond).every(function (k) {
        var v = value(k);
        // a condition on a field not on this form (e.g. board type) is shown so it can be answered
        return form.querySelector('[name="' + k + '"]') === null || v.indexOf(cond[k]) !== -1;
      });
      el.style.display = ok ? '' : 'none';
    });
  }
  form.addEventListener('change', apply);
  apply();
})();

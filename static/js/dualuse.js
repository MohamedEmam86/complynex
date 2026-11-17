/* Dual-use goods search: instant suggestions (codes, CAS numbers, words in Arabic and English).
   No inline handlers (CSP); the endpoint comes from data-suggest-url. */
(function () {
  'use strict';
  var input = document.getElementById('du-q');
  var box = document.getElementById('du-suggest');
  if (!input || !box) { return; }
  var url = input.getAttribute('data-suggest-url');
  var timer = null, active = -1, items = [], lastQ = '';
  var LABEL = { code: 'code', cas: 'CAS', term: '' };

  function hide() { box.classList.add('d-none'); box.innerHTML = ''; active = -1; items = []; }

  function render(list) {
    box.innerHTML = '';
    items = list || [];
    if (!items.length) { hide(); return; }
    items.forEach(function (it, i) {
      var a = document.createElement('button');
      a.type = 'button';
      a.className = 'list-group-item list-group-item-action d-flex justify-content-between gap-2';
      a.setAttribute('role', 'option');
      a.setAttribute('data-i', String(i));
      var v = document.createElement('span');
      v.textContent = it.value;
      v.dir = 'auto';
      a.appendChild(v);
      var l = document.createElement('span');
      l.className = 'small text-muted text-truncate';
      l.textContent = (LABEL[it.type] ? LABEL[it.type] + ' · ' : '') + (it.label || '');
      l.dir = 'auto';
      a.appendChild(l);
      a.addEventListener('mousedown', function (e) { e.preventDefault(); choose(i); });
      box.appendChild(a);
    });
    box.classList.remove('d-none');
  }

  function choose(i) {
    if (!items[i]) { return; }
    input.value = items[i].value;
    hide();
    input.form.submit();
  }

  function mark() {
    Array.prototype.forEach.call(box.children, function (el, i) { el.classList.toggle('active', i === active); });
  }

  input.addEventListener('input', function () {
    var q = input.value.trim();
    clearTimeout(timer);
    if (q.length < 2) { hide(); return; }
    timer = setTimeout(function () {
      if (q === lastQ) { return; }
      lastQ = q;
      fetch(url + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (data) { if (input.value.trim() === q) { render(data); } })
        .catch(function () { hide(); });
    }, 160);
  });
  input.addEventListener('keydown', function (e) {
    if (box.classList.contains('d-none')) { return; }
    if (e.key === 'ArrowDown') { active = Math.min(items.length - 1, active + 1); mark(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { active = Math.max(0, active - 1); mark(); e.preventDefault(); }
    else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); choose(active); }
    else if (e.key === 'Escape') { hide(); }
  });
  input.addEventListener('blur', function () { setTimeout(hide, 150); });
})();

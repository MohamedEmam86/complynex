/* Vessel screening result: news about the ship (loaded after the page; CSP-safe, no inline handlers). */
(function () {
  var box = document.getElementById('vessel-news');
  if (!box || !window.fetch) { return; }
  function text(el, t) { el.textContent = t; return el; }
  fetch(box.getAttribute('data-url'), { credentials: 'same-origin' })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
    .then(function (d) {
      box.innerHTML = '';
      var items = (d && d.items) || [];
      if (d && d.error && !items.length) { text(box, box.getAttribute('data-error')); return; }
      if (!items.length) { text(box, box.getAttribute('data-empty')); return; }
      var ul = document.createElement('ul');
      ul.className = 'list-unstyled mb-0';
      items.forEach(function (it) {
        var li = document.createElement('li');
        li.className = 'border-bottom py-2';
        var a = document.createElement(it.url ? 'a' : 'span');
        if (it.url) { a.href = it.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; }
        a.className = 'fw-semibold text-decoration-none';
        text(a, it.title || '-');
        li.appendChild(a);
        var meta = document.createElement('div');
        meta.className = 'text-muted';
        text(meta, [it.source, (it.published_at || '').slice(0, 10), it.why_label].filter(Boolean).join(' · '));
        li.appendChild(meta);
        (it.categories || []).forEach(function (c) {
          var b = document.createElement('span');
          b.className = 'badge bg-warning text-dark me-1';
          text(b, c);
          li.appendChild(b);
        });
        ul.appendChild(li);
      });
      box.appendChild(ul);
    })
    .catch(function () { text(box, box.getAttribute('data-error')); });
})();

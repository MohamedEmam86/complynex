/* Per-user access matrix (templates/access/_matrix.html): requires/dependents, select-all per module,
   search, expand/collapse, mode switch and the live effective-access preview. CSP-safe (no inline code). */
(function () {
  'use strict';
  var root = document.querySelector('[data-cx-matrix]');
  if (!root) { return; }

  var boxes = Array.prototype.slice.call(root.querySelectorAll('input[name="cx_feature"]'));
  var byKey = {};
  boxes.forEach(function (b) { byKey[b.value] = b; });
  var dependents = {};
  boxes.forEach(function (b) {
    (b.dataset.requires || '').split(' ').filter(Boolean).forEach(function (r) {
      (dependents[r] = dependents[r] || []).push(b.value);
    });
  });

  function mode() {
    var r = root.querySelector('input[name="cx_mode"]:checked');
    return r ? r.value : 'cms';
  }

  function tick(key, on, seen) {
    seen = seen || {};
    if (seen[key] || !byKey[key]) { return; }
    seen[key] = true;
    var b = byKey[key];
    if (b.disabled) { return; }
    b.checked = on;
    if (on) {
      (b.dataset.requires || '').split(' ').filter(Boolean).forEach(function (r) { tick(r, true, seen); });
    } else {
      (dependents[key] || []).forEach(function (d) { tick(d, false, seen); });
    }
  }

  // a ticked box counts unless the access type makes it unavailable (locked boxes keep their stored value)
  function counts(b) { return b.checked && (!b.disabled || (b.dataset.locked && !(mode() === 'restricted' && (b.dataset.noworkspace || b.closest('[data-cx-mod]').dataset.surface !== 'cms')))); }

  function modules() { return Array.prototype.slice.call(root.querySelectorAll('[data-cx-mod]')); }
  function featsOf(m) { return Array.prototype.slice.call(m.querySelectorAll('input[name="cx_feature"]')); }

  function refresh() {
    var nMods = 0, nFeats = 0;
    modules().forEach(function (m) {
      var fs = featsOf(m), on = fs.filter(counts).length;
      var enabled = fs.filter(function (b) { return !b.disabled; }).length;
      var onEnabled = fs.filter(function (b) { return b.checked && !b.disabled; }).length;
      var all = m.querySelector('[data-cx-modall]');
      all.checked = enabled > 0 && onEnabled === enabled;
      all.indeterminate = onEnabled > 0 && onEnabled < enabled;
      all.disabled = enabled === 0;
      m.querySelector('[data-cx-modcount]').textContent = on;
      m.classList.toggle('is-on', on > 0);
      if (on) { nMods += 1; nFeats += on; }
    });
    root.querySelector('[data-cx-count-modules]').textContent = nMods;
    root.querySelector('[data-cx-count-features]').textContent = nFeats;
    schedulePreview();
  }

  function applyMode() {
    var restricted = mode() === 'restricted';
    root.dataset.mode = mode();
    modules().forEach(function (m) {
      var outside = m.dataset.surface !== 'cms';
      if (outside) { m.classList.toggle('is-disabled', restricted); }
      featsOf(m).forEach(function (b) {
        if (b.dataset.locked) { return; }            // superadmin-only or own account: never editable here
        if (outside || b.dataset.noworkspace) { b.disabled = restricted; }
      });
    });
    refresh();
  }

  function setOpen(m, open) {
    var btn = m.querySelector('[data-cx-toggle]');
    m.querySelector('.cx-mod__body').hidden = !open;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    m.classList.toggle('is-open', open);
  }

  root.addEventListener('change', function (e) {
    var t = e.target;
    if (t.name === 'cx_feature') {
      tick(t.value, t.checked);
      refresh();
    } else if (t.matches('[data-cx-modall]')) {
      var m = t.closest('[data-cx-mod]');
      featsOf(m).forEach(function (b) { tick(b.value, t.checked); });
      refresh();
    } else if (t.name === 'cx_mode') {
      applyMode();
    }
  });

  root.addEventListener('click', function (e) {
    var tg = e.target.closest('[data-cx-toggle]');
    if (tg) {
      var m = tg.closest('[data-cx-mod]');
      setOpen(m, m.querySelector('.cx-mod__body').hidden);
      return;
    }
    var act = e.target.closest('[data-cx-act]');
    if (!act) { return; }
    if (act.dataset.cxAct === 'copy') { copyFrom(); return; }
    var visible = modules().filter(function (m) { return !m.hidden; });
    if (act.dataset.cxAct === 'expand') { visible.forEach(function (m) { setOpen(m, true); }); }
    if (act.dataset.cxAct === 'collapse') { visible.forEach(function (m) { setOpen(m, false); }); }
    if (act.dataset.cxAct === 'all' || act.dataset.cxAct === 'none') {
      var on = act.dataset.cxAct === 'all';
      visible.forEach(function (m) {
        featsOf(m).forEach(function (b) {
          if (!b.closest('[data-cx-feat]').hidden) { tick(b.value, on); }
        });
      });
      refresh();
    }
  });

  var search = root.querySelector('[data-cx-search]');
  search.addEventListener('input', function () {
    var q = search.value.trim().toLowerCase();
    var any = false;
    modules().forEach(function (m) {
      var modHit = !q || m.dataset.search.indexOf(q) >= 0;
      var featHit = false;
      Array.prototype.slice.call(m.querySelectorAll('[data-cx-feat]')).forEach(function (li) {
        var hit = modHit || li.dataset.search.indexOf(q) >= 0;
        li.hidden = !hit;
        featHit = featHit || hit;
      });
      m.hidden = !featHit;
      if (q && featHit) { setOpen(m, true); }
      any = any || featHit;
    });
    Array.prototype.slice.call(root.querySelectorAll('[data-cx-area]')).forEach(function (a) {
      a.hidden = !a.querySelector('[data-cx-mod]:not([hidden])');
    });
    root.querySelector('[data-cx-nomatch]').hidden = any;
  });

  // ---- live preview (server computes the same rule the gate applies)
  var timer = null, seq = 0;
  function schedulePreview() {
    clearTimeout(timer);
    timer = setTimeout(preview, 250);
  }
  function preview() {
    var url = root.dataset.previewUrl;
    if (!url) { return; }
    var p = new URLSearchParams();
    p.set('mode', mode());
    var roleEl = root.dataset.copyUrl ? document.querySelector('select[name="role"]') : null;
    if (roleEl) { p.set('role', roleEl.value); }
    boxes.forEach(function (b) { if (counts(b)) { p.append('f', b.value); } });
    var mine = ++seq;
    fetch(url + '?' + p.toString(), { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || mine !== seq) { return; }
        root.querySelector('[data-cx-pv-home]').textContent = d.home || '—';
        root.querySelector('[data-cx-pv-pages]').textContent = d.pages + ' / ' + d.pages_total;
        var ul = root.querySelector('[data-cx-pv-mods]');
        ul.textContent = '';
        d.modules.forEach(function (m) {
          var li = document.createElement('li');
          var head = document.createElement('div');
          head.className = 'cx-pv-mod';
          var ic = document.createElement('i');
          ic.className = 'bi ' + m.icon;
          head.appendChild(ic);
          head.appendChild(document.createTextNode(' ' + m.label));
          li.appendChild(head);
          var sm = document.createElement('div');
          sm.className = 'cx-pv-feats';
          sm.textContent = m.features.join(' · ');
          li.appendChild(sm);
          ul.appendChild(li);
        });
        root.querySelector('[data-cx-pv-none]').hidden = d.modules.length > 0;
      })
      .catch(function () { /* preview is a convenience */ });
  }

  // add-user page: "copy from user" ticks the boxes here (nothing is saved until the form is)
  function copyFrom() {
    var sel = root.querySelector('[data-cx-copy-src]');
    if (!sel || !sel.value || !root.dataset.copyUrl) { return; }
    var url = root.dataset.copyUrl.replace(/\/0\/grants$/, '/' + encodeURIComponent(sel.value) + '/grants');
    fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) { return; }
        var m = root.querySelector('input[name="cx_mode"][value="' + d.mode + '"]');
        if (m) { m.checked = true; }
        var lvl = root.querySelector('select[name="cx_cms_level"]');
        if (lvl && d.cms_level) { lvl.value = d.cms_level === 'edit' ? 'edit' : 'view'; }
        var want = {};
        d.features.forEach(function (k) { want[k] = true; });
        boxes.forEach(function (b) { if (!b.dataset.locked) { b.checked = !!want[b.value]; } });
        applyMode();
      })
      .catch(function () { /* nothing ticked on failure */ });
  }

  var roleSel = root.dataset.copyUrl ? document.querySelector('select[name="role"]') : null;
  if (roleSel) { roleSel.addEventListener('change', schedulePreview); }

  applyMode();
})();

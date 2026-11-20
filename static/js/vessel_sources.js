// Copyright (c) 2026 ComplyNex (complynex.online) - All Rights Reserved.
// "Sync Now" of one vessel list on the list sources page (same behaviour as the sanctions lists: start a
// background task, poll its status, show progress, reload when done). Superadmin only (checked on the server).
(function () {
  var me = document.currentScript;
  var syncUrl = me.dataset.syncUrl, taskUrl = me.dataset.taskUrl;
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  function el(id) { return document.getElementById(id); }
  function sync(source, row) {
    var st = el('v-status-' + row), txt = el('v-statusText-' + row), bar = el('v-progressBar-' + row);
    var ok = el('v-success-' + row), err = el('v-error-' + row), btn = el('v-syncBtn-' + row);
    if (btn) { btn.disabled = true; }
    st.classList.remove('d-none'); ok.classList.add('d-none'); err.classList.add('d-none');
    txt.textContent = me.dataset.msgStart;
    function fail(m) { st.classList.add('d-none'); err.textContent = m || me.dataset.msgFailed; err.classList.remove('d-none'); if (btn) btn.disabled = false; }
    function done(m) { st.classList.add('d-none'); ok.textContent = m || me.dataset.msgDone; ok.classList.remove('d-none'); setTimeout(function () { location.reload(); }, 3000); }
    fetch(syncUrl, { method: 'POST', credentials: 'same-origin',
                     headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                     body: JSON.stringify({ source: source }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.success || !d.task_id) { fail(d.error); return; }
        var n = 0;
        var t = setInterval(function () {
          if (++n > 900) { clearInterval(t); fail('Timeout'); return; }
          fetch(taskUrl.replace('TASK', encodeURIComponent(d.task_id)), { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (s) {
              if (!s.success) return;
              bar.style.width = (s.progress || 5) + '%';
              if (s.message) txt.textContent = s.message;
              if (s.status === 'completed') { clearInterval(t); done(s.message); }
              else if (s.status === 'failed') { clearInterval(t); fail(s.message); }
            }).catch(function () {});
        }, 1500);
      })
      .catch(function (e) { fail(e.message); });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-vessel-sync]');
    if (b) sync(b.dataset.vesselSync, b.dataset.row);
  });
})();

/* Compliance Copilot — polling of AI jobs, next-best-action cards and drafts.
 * CSP-safe: loaded with a nonce, no inline handlers; model output is always
 * inserted with textContent (never as HTML). */
(function () {
  'use strict';
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = text; }
    return e;
  }

  function post(url, body) {
    return fetch(url, {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      body: JSON.stringify(body || {})}).then(function (r) { return r.json(); });
  }

  function poll(jobId, onDone, onFail, delay, started) {
    delay = delay || 1500; started = started || Date.now();
    fetch('/ai/api/jobs/' + encodeURIComponent(jobId), {credentials: 'same-origin'})
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.status === 'done') { onDone(j.result || {}); return; }
        if (j.status === 'failed' || j.error === 'not found') { onFail(j.error || 'failed'); return; }
        if (Date.now() - started > 15 * 60 * 1000) { onFail('timeout'); return; }
        setTimeout(function () { poll(jobId, onDone, onFail, Math.min(delay * 1.4, 10000), started); }, delay);
      })
      .catch(function () { setTimeout(function () { poll(jobId, onDone, onFail, Math.min(delay * 2, 10000), started); }, delay); });
  }

  /* Pages that render a job result server-side: wait, then reload. */
  document.querySelectorAll('[data-ai-job-reload]').forEach(function (box) {
    poll(box.getAttribute('data-ai-job-reload'), function () { window.location.reload(); },
      function (err) { box.textContent = box.getAttribute('data-fail-text') + ' (' + err + ')'; box.classList.add('text-danger'); });
  });

  function decisionButtons(container, sid, labels) {
    if (!sid) { return; }
    var wrap = el('div', 'mt-2 d-flex gap-2 small');
    [['accept', labels.accept, 'btn-outline-success'], ['reject', labels.reject, 'btn-outline-secondary']].forEach(function (d) {
      var b = el('button', 'btn btn-sm ' + d[2], d[1]);
      b.type = 'button';
      b.addEventListener('click', function () {
        post('/ai/api/suggestions/' + sid + '/decision', {decision: d[0]}).then(function () {
          wrap.textContent = labels.thanks;
        });
      });
      wrap.appendChild(b);
    });
    container.appendChild(wrap);
  }

  function renderSteps(body, headline, steps) {
    body.textContent = '';
    body.appendChild(el('div', 'fw-bold mb-1', headline));
    var ol = el('ol', 'mb-0 ps-3');
    (steps || []).forEach(function (s) { ol.appendChild(el('li', null, s)); });
    body.appendChild(ol);
  }

  /* Next-best-action cards. */
  document.querySelectorAll('[data-ai-nba]').forEach(function (card) {
    var btn = card.querySelector('[data-ai-nba-run]');
    var body = card.querySelector('[data-ai-nba-body]');
    var foot = card.querySelector('[data-ai-nba-foot]');
    var L = JSON.parse(card.getAttribute('data-labels') || '{}');
    if (!btn) { return; }
    btn.addEventListener('click', function () {
      btn.disabled = true;
      body.textContent = L.working;
      post(card.getAttribute('data-ai-nba'), {}).then(function (r) {
        if (r.error) { body.textContent = r.error; return; }
        renderSteps(body, r.deterministic.headline, r.deterministic.steps);
        foot.textContent = L.rules;
        poll(r.job_id, function (res) {
          renderSteps(body, res.headline, res.steps);
          foot.textContent = (res.provider === 'rules_only' ? L.rules : L.ai + ' · ' + res.provider) +
            (res.status === 'fallback' ? ' · ' + L.fallback : '');
          decisionButtons(foot, res.suggestion_id, L);
        }, function () { foot.textContent = L.rules + ' · ' + L.fallback; });
      });
    });
  });

  /* Drafts (action plan, STR narrative, board summary). */
  document.querySelectorAll('[data-ai-draft]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var out = document.getElementById(btn.getAttribute('data-target'));
      var L = JSON.parse(btn.getAttribute('data-labels') || '{}');
      btn.disabled = true;
      out.textContent = L.working;
      post('/ai/api/draft', {kind: btn.getAttribute('data-ai-draft'), obj_type: btn.getAttribute('data-obj-type'),
        obj_id: btn.getAttribute('data-obj-id')}).then(function (r) {
        if (r.error) { out.textContent = r.error; btn.disabled = false; return; }
        poll(r.job_id, function (res) {
          out.textContent = '';
          out.appendChild(el('div', 'badge bg-warning text-dark mb-2', L.label + ' · ' + (res.provider || '')));
          out.appendChild(el('div', 'fw-bold', res.title));
          var ta = el('textarea', 'form-control form-control-sm mt-1');
          ta.rows = 10; ta.value = res.text || '';
          out.appendChild(ta);
          var copy = el('button', 'btn btn-sm btn-outline-secondary mt-1', L.copy);
          copy.type = 'button';
          copy.addEventListener('click', function () { ta.select(); try { navigator.clipboard.writeText(ta.value); } catch (e) { document.execCommand('copy'); } });
          out.appendChild(copy);
          decisionButtons(out, res.suggestion_id, L);
          btn.disabled = false;
        }, function (err) { out.textContent = L.failed + ' (' + err + ')'; btn.disabled = false; });
      });
    });
  });

  /* Freeze orders: live "time since receipt" — seconds elapsed when the server rendered the page
     (data-elapsed-s), counted on from page load, so browser and server clocks / time zones need not agree. */
  document.querySelectorAll('[data-elapsed-s]').forEach(function (box) {
    var elapsed = parseInt(box.getAttribute('data-elapsed-s'), 10);
    if (isNaN(elapsed)) { return; }
    var since = new Date(Date.now() - elapsed * 1000);
    var h = box.getAttribute('data-unit-h') || 'h', mn = box.getAttribute('data-unit-min') || 'min';
    function tick() {
      var mins = Math.max(0, Math.floor((Date.now() - since.getTime()) / 60000));
      box.textContent = Math.floor(mins / 60) + ' ' + h + ' ' + (mins % 60) + ' ' + mn;
    }
    tick();
    setInterval(tick, 30000);
  });
})();

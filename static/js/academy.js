/* Integrys Academy — no inline handlers (CSP). */
(function () {
  var quiz = document.getElementById('iaQuiz');
  if (quiz) {
    var counter = document.getElementById('iaQuizCount');
    var total = counter ? parseInt(counter.getAttribute('data-total'), 10) : 0;
    var rtl = document.documentElement.dir === 'rtl';
    var update = function () {
      var names = {};
      quiz.querySelectorAll('input[type=radio]:checked').forEach(function (r) { names[r.name] = 1; });
      var n = Object.keys(names).length;
      if (counter) counter.textContent = rtl ? ('تمت الإجابة على ' + n + ' من ' + total) : (n + ' of ' + total + ' answered');
    };
    quiz.addEventListener('change', update);
    update();
    var sent = false;
    quiz.addEventListener('submit', function (e) {
      if (sent) { e.preventDefault(); return; }
      sent = true;
    });
  }
  var otp = document.querySelector('.ia-otp');
  if (otp) {
    otp.addEventListener('input', function () { otp.value = otp.value.replace(/[^0-9]/g, '').slice(0, 6); });
  }
})();

/* Mandatory full video viewing + ComplyNex intro (no inline handlers — CSP). */
(function () {
  var intro = document.getElementById('iaCnx');
  var go = document.getElementById('iaCnxGo');
  var wrap = document.getElementById('iaVideoWrap');
  var v = document.getElementById('iaVideo');
  var doneBtn = document.getElementById('iaDoneBtn');
  var note = document.getElementById('iaVideoNote');
  if (intro && go && intro.tagName === 'DIV') {
    var left = parseInt(intro.getAttribute('data-min'), 10) || 15;
    var cnt = document.getElementById('iaCnxCount');
    var tick = setInterval(function () {
      left -= 1;
      if (cnt) cnt.textContent = left;
      if (left <= 0) { clearInterval(tick); go.disabled = false; go.textContent = intro.getAttribute('data-label'); }
    }, 1000);
    go.addEventListener('click', function () {
      intro.hidden = true;
      if (wrap) wrap.hidden = false;
      if (note) note.hidden = false;
      if (v) { var p = v.play(); if (p && p.catch) p.catch(function () {}); v.scrollIntoView({behavior: 'smooth', block: 'center'}); }
    });
  }
  if (!v || v.getAttribute('data-done') === '1') return;
  var endpoint = v.getAttribute('data-endpoint');
  var maxT = parseFloat(v.getAttribute('data-max')) || 0;
  var tokenEl = document.querySelector('input[name=csrf_token]');
  var token = tokenEl ? tokenEl.value : '';
  var lastSent = 0, started = false, finished = false;
  var send = function (action, t) {
    return fetch(endpoint, {method: 'POST', credentials: 'same-origin',
      headers: {'X-CSRFToken': token, 'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'action=' + action + '&t=' + encodeURIComponent(t.toFixed(1))})
      .then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; });
  };
  v.addEventListener('loadedmetadata', function () {
    if (maxT > 2 && maxT < v.duration - 3) v.currentTime = maxT;
  });
  v.addEventListener('play', function () { if (!started) { started = true; send('start', maxT); } });
  v.addEventListener('seeking', function () {
    if (v.currentTime > maxT + 1.5) v.currentTime = maxT;
  });
  v.addEventListener('ratechange', function () { if (v.playbackRate !== 1) v.playbackRate = 1; });
  v.addEventListener('timeupdate', function () {
    if (v.currentTime > maxT + 2.5) { v.currentTime = maxT; return; }
    if (!v.seeking) maxT = Math.max(maxT, v.currentTime);
    var now = Date.now();
    if (now - lastSent > 10000) { lastSent = now; send('progress', maxT); }
  });
  v.addEventListener('ended', function () {
    if (finished) return;
    maxT = Math.max(maxT, v.duration || maxT);
    send('complete', maxT).then(function (res) {
      if (res && res.completed) {
        finished = true;
        if (doneBtn) doneBtn.disabled = false;
        var ok = document.getElementById('iaVideoDone');
        if (ok) ok.hidden = false;
        if (note) note.hidden = true;
      }
    });
  });
})();

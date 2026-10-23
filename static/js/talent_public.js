/* Talent pool public form: early CV size/type feedback (the server re-checks everything). */
(function () {
  var input = document.querySelector('input[type=file][name=cv]');
  var msg = document.getElementById('tp-cv-msg');
  if (!input || !msg) return;
  var ar = document.documentElement.lang === 'ar';
  input.addEventListener('change', function () {
    msg.textContent = '';
    var f = input.files && input.files[0];
    if (!f) return;
    var max = parseInt(input.getAttribute('data-max'), 10) || 5242880;
    var ok = /\.(pdf|docx)$/i.test(f.name);
    if (!ok) {
      msg.textContent = ar ? 'السيرة الذاتية لازم تكون PDF أو Word (.docx).' : 'Your CV must be a PDF or Word (.docx) file.';
      input.value = '';
    } else if (f.size > max) {
      msg.textContent = ar ? 'حجم الملف أكبر من 5 ميجابايت.' : 'The file is larger than 5 MB.';
      input.value = '';
    }
  });
})();

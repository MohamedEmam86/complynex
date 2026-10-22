/* Any element with data-print opens the browser print dialog (no inline handlers under the CSP). */
document.querySelectorAll('[data-print]').forEach(function (b) { b.addEventListener('click', function () { window.print(); }); });

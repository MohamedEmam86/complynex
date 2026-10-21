/* =============================================================================
 * Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
 * ESG & Carbon charts: every <canvas data-ecx-chart='{...}'> is drawn with the
 * self-hosted Chart.js. The JSON spec is built server-side from the same
 * figures the page shows, so a chart can never disagree with its tables.
 * Spec: {kind: 'bar'|'hbar'|'line'|'doughnut'|'radar'|'scatter', labels:[], series:[{name, data, color, stack, dashed, fill}],
 *        unit:'', stacked:bool, max:number, min:number, quadrants:{x, y}, pointLabels:bool, xTitle:'', yTitle:''}
 * ============================================================================= */
(function () {
  'use strict';
  if (!window.Chart) { return; }
  var rtl = (document.documentElement.getAttribute('dir') || document.body.getAttribute('dir') ||
             (document.querySelector('.ecx-page') || {}).dir) === 'rtl';
  var css = getComputedStyle(document.documentElement);
  var font = (css.getPropertyValue('--bs-body-font-family') || 'Cairo, system-ui, sans-serif').trim();
  Chart.defaults.font.family = font;
  Chart.defaults.font.size = 12;
  Chart.defaults.color = '#5b6670';
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.plugins.legend.rtl = rtl;
  Chart.defaults.plugins.tooltip.rtl = rtl;
  var GRID = 'rgba(0,0,0,.06)';

  function fmt(v, unit) {
    if (v === null || v === undefined || isNaN(v)) { return '-'; }
    var n = Math.abs(v) >= 100 ? Math.round(v) : Math.round(v * 100) / 100;
    return n.toLocaleString(rtl ? 'ar-EG' : 'en-US') + (unit ? ' ' + unit : '');
  }

  /* point labels (scatter): short names next to each point, kept inside the chart area */
  var pointLabels = {
    id: 'ecxPointLabels',
    afterDatasetsDraw: function (chart, args, opts) {
      if (!opts || !opts.enabled) { return; }
      var ctx = chart.ctx; ctx.save(); ctx.font = '11px ' + font; ctx.fillStyle = '#33404a';
      chart.data.datasets.forEach(function (ds, i) {
        chart.getDatasetMeta(i).data.forEach(function (pt, j) {
          var lbl = (ds.data[j] || {}).label; if (!lbl) { return; }
          var w = ctx.measureText(lbl).width, x = pt.x + 8, y = pt.y + 4;
          if (x + w > chart.chartArea.right) { x = pt.x - 8 - w; }
          ctx.fillText(lbl, x, y);
        });
      });
      ctx.restore();
    }
  };
  /* quadrant lines (materiality): dashed reference lines at the given x / y */
  var quadrants = {
    id: 'ecxQuadrants',
    beforeDatasetsDraw: function (chart, args, opts) {
      if (!opts || opts.x === undefined) { return; }
      var ctx = chart.ctx, xs = chart.scales.x, ys = chart.scales.y, a = chart.chartArea;
      ctx.save(); ctx.strokeStyle = 'rgba(0,0,0,.25)'; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(xs.getPixelForValue(opts.x), a.top); ctx.lineTo(xs.getPixelForValue(opts.x), a.bottom);
      ctx.moveTo(a.left, ys.getPixelForValue(opts.y)); ctx.lineTo(a.right, ys.getPixelForValue(opts.y)); ctx.stroke();
      ctx.fillStyle = 'rgba(25,135,84,.07)';
      ctx.fillRect(xs.getPixelForValue(opts.x), a.top, a.right - xs.getPixelForValue(opts.x), ys.getPixelForValue(opts.y) - a.top);
      ctx.restore();
    }
  };

  function build(el) {
    var s; try { s = JSON.parse(el.getAttribute('data-ecx-chart')); } catch (e) { return; }
    var kind = s.kind || 'bar', horizontal = kind === 'hbar', unit = s.unit || '';
    var type = horizontal ? 'bar' : kind;
    var datasets = (s.series || []).map(function (d) {
      var ds = {label: d.name, data: d.data, backgroundColor: d.color, borderColor: d.border || d.color, borderWidth: d.borderWidth || (type === 'line' || type === 'radar' ? 2 : 0)};
      if (d.stack) { ds.stack = d.stack; }
      if (d.dashed) { ds.borderDash = [6, 4]; }
      if (type === 'line') { ds.fill = !!d.fill; ds.tension = 0; ds.pointRadius = d.pointRadius === undefined ? 3 : d.pointRadius; ds.spanGaps = true; }
      if (type === 'radar') { ds.fill = true; ds.pointRadius = 3; }
      if (type === 'scatter') { ds.pointRadius = 6; ds.pointHoverRadius = 8; }
      if (type === 'doughnut') { ds.borderWidth = 2; ds.borderColor = '#fff'; }
      if (d.barMax) { ds.maxBarThickness = d.barMax; }
      return ds;
    });
    var opts = {
      responsive: true, maintainAspectRatio: false, animation: false,
      indexAxis: horizontal ? 'y' : 'x',
      plugins: {
        legend: {display: s.legend !== false && (datasets.length > 1 || type === 'doughnut'), position: type === 'doughnut' ? 'bottom' : 'top'},
        tooltip: {callbacks: {label: function (c) {
          if (type === 'scatter') { var p = c.raw || {}; return (p.label || '') + ': ' + fmt(p.x) + ' / ' + fmt(p.y); }
          var v = type === 'doughnut' ? c.raw : (horizontal ? c.parsed.x : c.parsed.y);
          if (type === 'radar') { v = c.parsed.r; }
          return (c.dataset.label ? c.dataset.label + ': ' : (type === 'doughnut' ? c.label + ': ' : '')) + fmt(v, unit);
        }}},
        ecxPointLabels: {enabled: !!s.pointLabels},
        ecxQuadrants: s.quadrants || {}
      }
    };
    if (type === 'bar' || type === 'line' || type === 'scatter') {
      var valueAxis = {beginAtZero: s.min === undefined, grid: {color: GRID}, stacked: !!s.stacked,
                       ticks: {callback: function (v) { return fmt(v); }}, title: {display: !!(horizontal ? s.xTitle : s.yTitle), text: horizontal ? s.xTitle : s.yTitle}};
      if (s.max !== undefined) { valueAxis.max = s.max; }
      if (s.min !== undefined) { valueAxis.min = s.min; }
      var catAxis = {grid: {display: false}, stacked: !!s.stacked, reverse: rtl && !horizontal, title: {display: !!(horizontal ? s.yTitle : s.xTitle), text: horizontal ? s.yTitle : s.xTitle}};
      if (type === 'scatter') {
        catAxis = {min: s.xMin, max: s.xMax, grid: {color: GRID}, reverse: rtl, title: {display: !!s.xTitle, text: s.xTitle}, ticks: {stepSize: 1}};
        valueAxis.ticks = {stepSize: 1};
      }
      opts.scales = horizontal ? {x: valueAxis, y: catAxis} : {x: catAxis, y: valueAxis};
      if (horizontal) { opts.scales.y.position = rtl ? 'right' : 'left'; } else { opts.scales.y.position = rtl ? 'right' : 'left'; }
    }
    if (type === 'radar') {
      opts.scales = {r: {min: 0, max: s.max || 5, ticks: {stepSize: 1, backdropColor: 'transparent'}, grid: {color: GRID}, angleLines: {color: GRID},
                         pointLabels: {font: {size: 12, weight: '600'}}}};
    }
    if (type === 'doughnut') { opts.cutout = '68%'; }
    /* doughnut centre text */
    var centre = s.centre ? [{id: 'ecxCentre', afterDraw: function (chart) {
      var a = chart.chartArea, ctx = chart.ctx; ctx.save(); ctx.textAlign = 'center'; ctx.fillStyle = '#1f2a33';
      ctx.font = '700 20px ' + font; ctx.fillText(s.centre[0], (a.left + a.right) / 2, (a.top + a.bottom) / 2 + 2);
      ctx.font = '12px ' + font; ctx.fillStyle = '#6c757d'; ctx.fillText(s.centre[1] || '', (a.left + a.right) / 2, (a.top + a.bottom) / 2 + 20);
      ctx.restore(); }}] : [];
    var data = type === 'scatter' ? {datasets: datasets} : {labels: s.labels || [], datasets: datasets};
    new Chart(el, {type: type, data: data, options: opts, plugins: [pointLabels, quadrants].concat(centre)});
  }
  function init() { document.querySelectorAll('canvas[data-ecx-chart]').forEach(build); }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();

/* raising-pipeline.js — SHARED between pip-daily-dashboard and the standalone
   raising page. Keep both copies identical.

   Usage:  RaisingPipeline.mount(rootElement, DATA.raising_pipeline, {selectable:true})
   Data comes from scripts/raising_pipeline.py (same CORE_VERSION). */
(function (global) {
  'use strict';
  var CARET = '<svg class="rpp-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
  var STAGE_COLOUR = {
    pending: 'var(--rpp-pending)', forms_out: 'var(--rpp-forms)', written: 'var(--rpp-written)',
    money_received: 'var(--rpp-mr)', project_live: 'var(--rpp-live)'
  };
  var LIGHT = { pending: 1, forms_out: 1 };
  var KIND_LABEL = { new_money: 'New Money', rollover: 'Rollovers', takeover: 'Takeovers' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function gbp(v) { v = Math.round(v || 0); return (v < 0 ? '−' : '') + '£' + Math.abs(v).toLocaleString('en-GB'); }
  function n(c, word) { return c + ' ' + word + (c === 1 ? '' : 's'); }
  function fmtDate(iso) {
    if (!iso) return '—';
    var d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function mount(root, data, opts) {
    opts = opts || {};
    if (!root) return;
    if (!data || !data.projects || !data.projects.length) {
      root.innerHTML = '<div class="rpp"><div class="rpp-empty">No raising projects configured.</div></div>';
      return;
    }
    var state = { idx: 0, mode: 'total', open: {}, kpiOpen: {}, trOpen: {} };
    var asAt = fmtDate(data.as_at);

    function render() {
      var p = data.projects[state.idx];
      var v = state.mode === 'monthly' ? p.monthly : p.total;
      var html = '<div class="rpp">';

      // ---- head ----
      html += '<div class="rpp-head"><div>' +
        '<h2 class="rpp-title">' + esc(p.label) + '</h2>' +
        '<div class="rpp-sub">Raising progress and pipeline · data as at ' + esc(asAt) + '</div></div>' +
        '<div class="rpp-controls">';
      if (opts.selectable && data.projects.length > 1) {
        html += '<select class="rpp-select" data-act="project" aria-label="Choose project">' +
          data.projects.map(function (q, i) {
            return '<option value="' + i + '"' + (i === state.idx ? ' selected' : '') + '>' + esc(q.label) + '</option>';
          }).join('') + '</select>';
      }
      html += '<div class="rpp-pills" role="tablist" aria-label="View">' +
        '<button type="button" class="rpp-pill' + (state.mode === 'total' ? ' active' : '') + '" data-act="mode" data-mode="total">Total</button>' +
        '<button type="button" class="rpp-pill' + (state.mode === 'monthly' ? ' active' : '') + '" data-act="mode" data-mode="monthly">Monthly</button>' +
        '</div></div></div>';

      // ---- hero: left to raise ----
      var req = v.requirement || 0;
      var left = v.left_to_raise || 0;
      var exceeded = req > 0 && left < 0;
      var periodLbl = state.mode === 'monthly' ? esc(p.monthly.month_label) : 'Total';
      var heroLabel, heroVal, heroNote;
      if (req <= 0) {
        heroLabel = periodLbl + ' — left to raise';
        heroVal = '—';
        heroNote = state.mode === 'monthly' ? 'No monthly raising requirement set for this project.'
          : 'No total raising requirement set for this project.';
      } else {
        heroLabel = exceeded ? periodLbl + ' — target exceeded by' : periodLbl + ' — left to raise';
        heroVal = gbp(Math.abs(left));
        var raisedPart = state.mode === 'monthly'
          ? 'started ' + gbp(v.started_total) + ' + money received ' + gbp(v.money_received_total)
          : 'started ' + gbp(v.started_total);
        heroNote = (state.mode === 'monthly' ? 'Monthly requirement ' : 'Raising requirement ') + gbp(req) +
          ' · ' + raisedPart + ' (' + Math.round((v.pct || 0) * 100) + '%)';
      }
      var fillPct = 0, mrPct = 0;
      if (req > 0) {
        fillPct = Math.max(0, Math.min(100, (v.started_total / req) * 100));
        if (state.mode === 'monthly') mrPct = Math.max(0, Math.min(100 - fillPct, (v.money_received_total / req) * 100));
      }
      html += '<div class="rpp-hero' + (exceeded ? ' exceeded' : '') + '">' +
        '<div class="rpp-hero-label">' + heroLabel + '</div>' +
        '<div class="rpp-hero-val">' + heroVal + '</div>' +
        (req > 0 ? '<div class="rpp-hero-bar"><div class="rpp-hero-fill" style="width:' + fillPct + '%"></div>' +
          (mrPct > 0 ? '<div class="rpp-hero-mr" style="left:' + fillPct + '%;width:' + mrPct + '%"></div>' : '') + '</div>' : '') +
        '<div class="rpp-hero-note">' + heroNote + '</div></div>';

      // ---- KPI cards ----
      var startedLbl = state.mode === 'monthly'
        ? 'Started in ' + esc(p.monthly.month_label)
        : 'Started investments';
      var startedNote = state.mode === 'monthly'
        ? n(v.started_count, 'investment') + ' · start date 1 – ' + esc(asAt) + ', flagged excluded'
        : n(v.started_count, 'investment') + ' · start date on or before ' + esc(asAt);
      var ct = p.current_tranche;
      html += '<div class="rpp-kpis">' +
        '<div class="rpp-kpi' + (state.kpiOpen.split ? ' rpp-open' : '') + '" style="--rpp-accent:#FFC553">' +
          '<button type="button" class="rpp-kpi-head" data-act="kpi" data-k="split" aria-expanded="' + (!!state.kpiOpen.split) + '">' + CARET +
          '<div class="rpp-kpi-label">' + startedLbl + '</div>' +
          '<div class="rpp-kpi-val">' + gbp(v.started_total) + '</div>' +
          '<div class="rpp-kpi-note">' + startedNote + '</div>' +
          '<div class="rpp-kpi-hint">New Money / Rollovers</div></button>' +
          '<div class="rpp-kpi-body">' +
            '<div class="rpp-split"><span class="rpp-split-name">New Money</span><span class="rpp-split-cnt">' + n(v.new_money_count, 'inv') + '</span><span class="rpp-split-val">' + gbp(v.new_money_total) + '</span></div>' +
            '<div class="rpp-split"><span class="rpp-split-name">Rollovers</span><span class="rpp-split-cnt">' + n(v.rollover_count, 'inv') + '</span><span class="rpp-split-val">' + gbp(v.rollover_total) + '</span></div>' +
          '</div></div>' +
        '<div class="rpp-kpi" style="--rpp-accent:var(--rpp-mr)"><div class="rpp-kpi-head">' +
          '<div class="rpp-kpi-label">Money received</div>' +
          '<div class="rpp-kpi-val">' + gbp(v.money_received_total) + '</div>' +
          '<div class="rpp-kpi-note">' + n(v.money_received_count, 'investment') + ' · funds in, not yet live</div></div></div>' +
        '<div class="rpp-kpi" style="--rpp-accent:var(--rpp-live)"><div class="rpp-kpi-head">' +
          '<div class="rpp-kpi-label">' + (ct ? 'Current tranche · ' + esc(ct.tranche) : 'Current tranche') + '</div>' +
          '<div class="rpp-kpi-val">' + (ct ? gbp(ct.total) : '—') + '</div>' +
          '<div class="rpp-kpi-note">' + (ct ? n(ct.count, 'investment') + ' going live when this tranche completes' : 'No tranche in progress') + '</div></div></div>' +
        '</div>';

      // ---- pipeline bar ----
      var bar = p.stages.filter(function (s) { return s.in_bar; });
      var barTotal = bar.reduce(function (a, s) { return a + s.total; }, 0);
      var barCount = bar.reduce(function (a, s) { return a + s.count; }, 0);
      var pl = p.pipeline || {};
      var split = p.pipeline ? ' <span class="rpp-bar-split">(B: ' + gbp(pl.bullet_total) + ', Q: ' + gbp(pl.quarterly_total) + ')</span>' : '';
      html += '<div class="rpp-section-title">Pipeline</div><div class="rpp-card"><div class="rpp-bar-wrap">' +
        '<div class="rpp-bar-total"><span class="rpp-bar-total-lbl">In pipeline (not yet live)</span>' +
        '<span class="rpp-bar-total-val">' + gbp(barTotal) + split + ' <span class="rpp-leg-cnt">· ' + n(barCount, 'investment') + '</span></span></div>';
      if (barTotal > 0) {
        html += '<div class="rpp-bar" role="img" aria-label="Pipeline split by stage">' + bar.map(function (s) {
          var w = (s.total / barTotal) * 100;
          if (w <= 0) return '';
          return '<div class="rpp-seg' + (LIGHT[s.key] ? ' light' : '') + '" style="width:' + w + '%;background:' + STAGE_COLOUR[s.key] + '" title="' + esc(s.label) + ': ' + gbp(s.total) + ' (' + s.count + ')">' +
            (w >= 12 ? Math.round(w) + '%' : '') + '</div>';
        }).join('') + '</div>';
      } else {
        html += '<div class="rpp-bar"></div>';
      }
      html += '<div class="rpp-legend">' + bar.map(function (s) {
        return '<div class="rpp-leg" style="--rpp-c:' + STAGE_COLOUR[s.key] + '"><div class="rpp-leg-name">' + esc(s.key === 'written' ? 'Written' : s.label) + '</div>' +
          '<div class="rpp-leg-val">' + gbp(s.total) + '</div><div class="rpp-leg-cnt">' + n(s.count, 'investment') + '</div></div>';
      }).join('') + '</div></div></div>';

      // ---- stage breakdown ----
      html += '<div class="rpp-stages">' + p.stages.map(function (s) {
        var rows = s.rows, total = s.total, count = s.count, note = '', grp = s.groups;
        if (s.key === 'project_live' && state.mode === 'monthly') {
          rows = rows.filter(function (r) { return r.m; });
          total = s.monthly_total; count = s.monthly_count; grp = s.monthly_groups;
          note = ' · ' + esc(p.monthly.month_label);
        }
        var open = !!state.open[s.key];
        var body = '';
        if (open && data.show_names === false) {
          // Main dashboard: totals only, no investment names in the page.
          body = '<div class="rpp-stage-body rpp-sum">' + ['new_money', 'rollover', 'takeover'].map(function (k) {
            var g = (grp && grp[k]) || {total: 0, count: 0};
            if (k === 'takeover' && !g.count) return '';
            return '<div class="rpp-split"><span class="rpp-split-name">' + KIND_LABEL[k] + '</span>' +
              '<span class="rpp-split-cnt">' + n(g.count, 'investment') + '</span>' +
              '<span class="rpp-split-val">' + gbp(g.total) + '</span></div>';
          }).join('') + '</div>';
        } else if (open) {
          var groups = ['new_money', 'rollover', 'takeover'].map(function (k) {
            var g = rows.filter(function (r) { return r.kind === k; });
            if (!g.length && k === 'takeover') return '';
            var gt = g.reduce(function (a, r) { return a + r.amount; }, 0);
            var head = '<div class="rpp-group-head"><span class="rpp-group-title">' + KIND_LABEL[k] + '</span>' +
              '<span class="rpp-group-meta"><strong>' + gbp(gt) + '</strong> · ' + n(g.length, 'investment') + '</span></div>';
            if (!g.length) return '<div class="rpp-group">' + head + '<div class="rpp-empty">None at this stage.</div></div>';
            return '<div class="rpp-group">' + head + '<div class="rpp-scroll"><table class="rpp-table rpp-inv-table"><thead><tr>' +
              '<th>Name</th><th class="num">Investment</th><th>Adviser</th><th class="rpp-hide-sm">' + (k !== 'new_money' ? 'Source investment project' : '') + '</th>' +
              '</tr></thead><tbody>' + g.map(function (r) {
                var url = data.record_url.replace('%s', encodeURIComponent(r.id));
                return '<tr><td><a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(r.name || r.id) + '</a></td>' +
                  '<td class="num">' + gbp(r.amount) + '</td><td>' + esc(r.adviser || '—') + '</td>' +
                  '<td class="rpp-hide-sm">' + (k !== 'new_money' ? esc(r.source || '—') : '') + '</td></tr>';
              }).join('') + '</tbody></table></div></div>';
          }).join('');
          body = '<div class="rpp-stage-body">' + groups + '</div>';
        }
        return '<div class="rpp-stage' + (open ? ' rpp-open' : '') + '" style="--rpp-c:' + STAGE_COLOUR[s.key] + '">' +
          '<button type="button" class="rpp-stage-btn" data-act="stage" data-k="' + s.key + '" aria-expanded="' + open + '">' +
          '<span class="rpp-dot"></span><span class="rpp-stage-name">' + esc(s.label) + note + '</span>' +
          '<span class="rpp-stage-cnt">' + n(count, 'investment') + '</span>' +
          '<span class="rpp-stage-val">' + gbp(total) + '</span>' + CARET + '</button>' + body + '</div>';
      }).join('') + '</div>';

      // ---- tranche table ----
      html += '<div class="rpp-section-title">Started investments by tranche</div><div class="rpp-card">';
      if (!p.tranches.length) {
        html += '<div class="rpp-empty">No investments with a start date on or before ' + esc(asAt) + '.</div>';
      } else {
        var grand = 0, grandC = 0;
        html += '<div class="rpp-scroll" style="max-height:none"><table class="rpp-table rpp-tr-table"><thead><tr><th>Tranche</th><th class="num">Subtotal</th><th>Start date</th></tr></thead><tbody>';
        p.tranches.forEach(function (t, ti) {
          grand += t.total; grandC += t.count;
          var label = t.tranche == null ? 'No tranche' : 'Tranche ' + esc(t.tranche);
          var many = t.dates.length > 1;
          var collapsible = t.dates.length > 4;
          var expanded = !!state.trOpen[ti];
          var dates = (collapsible && !expanded) ? [] : t.dates;
          var sub = many ? '<span class="rpp-tr-sub">' + gbp(t.total) + ' · ' + n(t.count, 'investment') + '</span>'
            : '<span class="rpp-tr-sub">' + n(t.count, 'investment') + '</span>';
          if (!dates.length) {
            html += '<tr class="rpp-tr-first"><td class="rpp-tr-num">' + label + sub + '</td><td class="num">' + gbp(t.total) + '</td>' +
              '<td>' + t.dates.length + ' start dates (' + fmtDate(t.dates[0].date) + ' – ' + fmtDate(t.dates[t.dates.length - 1].date) + ')' +
              '<button type="button" class="rpp-linkbtn" data-act="tr" data-k="' + ti + '">Show dates</button></td></tr>';
            return;
          }
          dates.forEach(function (d, di) {
            html += '<tr' + (di === 0 ? ' class="rpp-tr-first"' : '') + '>' +
              (di === 0 ? '<td class="rpp-tr-num" rowspan="' + dates.length + '">' + label + sub +
                (collapsible ? '<button type="button" class="rpp-linkbtn" style="margin:6px 0 0" data-act="tr" data-k="' + ti + '">Hide dates</button>' : '') + '</td>' : '') +
              '<td class="num">' + gbp(d.total) + (many ? ' <span class="rpp-tr-sub" style="display:inline">(' + d.count + ')</span>' : '') + '</td>' +
              '<td>' + fmtDate(d.date) + '</td></tr>';
          });
        });
        html += '</tbody><tfoot><tr><td>Total</td><td class="num">' + gbp(grand) + '</td><td>' + n(grandC, 'investment') + '</td></tr></tfoot></table></div>';
        if (p.tranche_takeover_count) {
          html += '<div class="rpp-empty">Includes ' + n(p.tranche_takeover_count, 'Takeover investment') + ' (' + gbp(p.tranche_takeover_total) + '), which are left out of the headline figures.</div>';
        }
      }
      html += '</div>';

      if (p.warnings && p.warnings.length) {
        html += '<div class="rpp-warn"><strong>Data checks:</strong> ' + p.warnings.map(esc).join(' ') + '</div>';
      }
      html += '<div class="rpp-foot"><span>Investment projects: ' + (p.investment_projects.length ? p.investment_projects.map(esc).join(', ') : '—') +
        ' · Company: ' + esc(p.company_name || '—') + '</span><span>Raising &amp; Pipeline v' + esc(data.core_version) + '</span></div>';
      html += '</div>';
      root.innerHTML = html;
    }

    root.addEventListener('click', function (e) {
      var b = e.target.closest('[data-act]');
      if (!b || !root.contains(b)) return;
      var act = b.getAttribute('data-act'), k = b.getAttribute('data-k');
      if (act === 'mode') { state.mode = b.getAttribute('data-mode'); render(); }
      else if (act === 'stage') { state.open[k] = !state.open[k]; render(); }
      else if (act === 'kpi') { state.kpiOpen[k] = !state.kpiOpen[k]; render(); }
      else if (act === 'tr') { state.trOpen[k] = !state.trOpen[k]; render(); }
    });
    root.addEventListener('change', function (e) {
      if (e.target.getAttribute('data-act') === 'project') {
        state.idx = parseInt(e.target.value, 10) || 0;
        state.open = {}; state.trOpen = {}; render();
      }
    });
    render();
  }

  global.RaisingPipeline = { mount: mount };
})(window);

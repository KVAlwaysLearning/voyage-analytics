/* Voyage Analytics web app - talks to the Flask API (see config.js for its address). */
(() => {
  'use strict';

  // ---------- API address: ?api=... overrides config.js (remembered for this browser) ----------
  const params = new URLSearchParams(location.search);
  let API = (window.VOYAGE_API_URL || '').replace(/\/+$/, '');
  try {
    if (params.get('api')) { API = params.get('api').replace(/\/+$/, ''); localStorage.setItem('voyageApi', API); }
    else if (API.includes('YOUR-API-NAME') && localStorage.getItem('voyageApi')) { API = localStorage.getItem('voyageApi'); }
  } catch (_) { /* storage unavailable - fine */ }

  const $ = (id) => document.getElementById(id);
  const CITY_CODES = {
    'Aracaju (SE)': 'AJU', 'Brasilia (DF)': 'BSB', 'Campo Grande (MS)': 'CGR', 'Florianopolis (SC)': 'FLN',
    'Natal (RN)': 'NAT', 'Recife (PE)': 'REC', 'Rio de Janeiro (RJ)': 'RIO', 'Salvador (BH)': 'SSA', 'Sao Paulo (SP)': 'SAO',
  };
  const CLASS_LABELS = { economic: 'Economy', premium: 'Premium', firstClass: 'First class' };
  const cityName = (c) => c.replace(/\s*\(.*\)$/, '');
  const money = (v) => 'R$ ' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // ---------- tabs ----------
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  function showTab(tab, focus) {
    tabs.forEach((t) => {
      const on = t === tab;
      t.setAttribute('aria-selected', on);
      t.tabIndex = on ? 0 : -1;
      $(t.getAttribute('aria-controls')).hidden = !on;
    });
    if (focus) tab.focus();
    const name = tab.id.replace('tab-', '');
    if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
    if (name === 'insights') renderInsights();
  }
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => showTab(t));
    t.addEventListener('keydown', (e) => {
      const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (d) { e.preventDefault(); showTab(tabs[(i + d + tabs.length) % tabs.length], true); }
    });
  });
  const initial = tabs.find((t) => '#' + t.id.replace('tab-', '') === location.hash) || tabs[0];
  showTab(initial);

  // ---------- API helpers ----------
  async function call(path, body, timeoutMs = 20000) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(API + path, {
        method: body ? 'POST' : 'GET',
        headers: body ? { 'Content-Type': 'application/json' } : {},
        body: body ? JSON.stringify(body) : undefined,
        signal: ctrl.signal,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `The API answered with status ${res.status}.`);
      return data;
    } catch (e) {
      if (e.name === 'AbortError') throw new Error('The API took too long to answer. Try again in a moment.');
      if (e instanceof TypeError) throw new Error('Could not reach the API. Check that it is running and that config.js has the right address.');
      throw e;
    } finally { clearTimeout(timer); }
  }

  const statusBtn = $('apiStatus');
  function setStatus(state, text) {
    statusBtn.dataset.state = state;
    statusBtn.querySelector('.label').textContent = text;
    $('wakeNote').hidden = state !== 'waking';
  }

  let options = null;
  async function connect() {
    $('apiUrl').textContent = API || '(not set)';
    if (!API || API.includes('YOUR-API-NAME')) {
      setStatus('down', 'API address not set');
      ['fareError', 'hotelError', 'nameError'].forEach((id) => { $(id).textContent = 'Set your API address in config.js to use this form.'; });
      return;
    }
    setStatus('connecting', 'Connecting to the API…');
    const started = Date.now();
    while (Date.now() - started < 120000) {          // free hosting can take ~1 minute to wake up
      try {
        await call('/health', null, 15000);
        options = await call('/options');
        setStatus('live', 'API live');
        enableForms();
        return;
      } catch (e) {
        if (Date.now() - started > 4000) setStatus('waking', 'Waking the API…');
        await new Promise((r) => setTimeout(r, 4000));
      }
    }
    setStatus('down', 'API offline. Retry');
  }
  statusBtn.addEventListener('click', () => { if (statusBtn.dataset.state !== 'live') connect(); });

  function fillSelect(sel, values, { blank, labels } = {}) {
    sel.innerHTML = '';
    if (blank) sel.add(new Option(blank, ''));
    values.forEach((v) => sel.add(new Option(labels ? labels(v) : v, v)));
  }

  function enableForms() {
    document.querySelectorAll('form select, form input, form button').forEach((el) => { el.disabled = false; });
    ['fareError', 'hotelError', 'nameError'].forEach((id) => { $(id).textContent = ''; });
    const f = options.flight;
    fillSelect($('fareFrom'), f.cities);
    fillSelect($('fareTo'), f.cities);
    $('fareFrom').value = 'Recife (PE)';
    $('fareTo').value = 'Florianopolis (SC)';
    fillSelect($('fareAgency'), f.agencies);
    $('fareAgency').value = 'FlyingDrops';
    const seg = $('fareClass');
    seg.innerHTML = '';
    f.flight_types.slice().sort((a, b) => Object.keys(CLASS_LABELS).indexOf(a) - Object.keys(CLASS_LABELS).indexOf(b))
      .forEach((c) => {
        const l = document.createElement('label');
        l.innerHTML = `<input type="radio" name="flightType" value="${c}"><span>${CLASS_LABELS[c] || c}</span>`;
        seg.appendChild(l);
      });
    syncClasses();
    const cities = options.hotels.map((h) => h.place).sort();
    fillSelect($('hotelOrigin'), cities, { blank: 'Not specified' });
    $('hotelOrigin').value = 'Recife (PE)';
    fillSelect($('hotelDest'), cities, { blank: 'Any city' });
    fillSelect($('nameCompany'), options.gender.companies);
  }

  // ---------- fare form ----------
  function syncClasses() {
    const agency = $('fareAgency').value;
    const allowed = options.flight.agency_classes[agency] || [];
    const radios = [...document.querySelectorAll('#fareClass input')];
    radios.forEach((r) => { r.disabled = !allowed.includes(r.value); });
    if (!radios.some((r) => r.checked && !r.disabled)) {
      const first = radios.find((r) => !r.disabled);
      if (first) first.checked = true;
    }
    $('classHint').textContent = allowed.length < 3 ? `${agency} only sells ${allowed.map((c) => CLASS_LABELS[c]).join(', ').toLowerCase()} tickets.` : '';
  }
  $('fareAgency').addEventListener('change', syncClasses);
  $('swapCities').addEventListener('click', () => {
    const a = $('fareFrom').value; $('fareFrom').value = $('fareTo').value; $('fareTo').value = a;
  });

  $('fareForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.submitter || e.target.querySelector('button[type="submit"]');
    const body = {
      from: $('fareFrom').value, to: $('fareTo').value, agency: $('fareAgency').value,
      flightType: (document.querySelector('#fareClass input:checked') || {}).value,
    };
    $('fareError').textContent = '';
    if (body.from === body.to) { $('fareError').textContent = 'Choose two different cities.'; return; }
    btn.setAttribute('aria-busy', 'true'); btn.textContent = 'Estimating…';
    try {
      const r = await call('/predict/price', body);
      const pass = $('pass');
      $('passFromCode').textContent = CITY_CODES[r.from] || r.from.slice(0, 3).toUpperCase();
      $('passToCode').textContent = CITY_CODES[r.to] || r.to.slice(0, 3).toUpperCase();
      $('passFromCity').textContent = cityName(r.from);
      $('passToCity').textContent = cityName(r.to);
      $('passAgency').textContent = r.agency;
      $('passClass').textContent = CLASS_LABELS[r.flightType];
      $('passDistance').textContent = Math.round(r.distance_km) + ' km';
      $('passPrice').textContent = money(r.predicted_price);
      pass.dataset.empty = 'false';
      pass.classList.remove('printed'); void pass.offsetWidth; pass.classList.add('printed');
      $('passHint').hidden = true;
    } catch (err) {
      $('fareError').textContent = err.message;
    } finally { btn.removeAttribute('aria-busy'); btn.textContent = 'Estimate fare'; }
  });

  // ---------- hotel form ----------
  $('hotelNew').addEventListener('change', (e) => { $('hotelUser').disabled = e.target.checked; });
  $('hotelBudget').addEventListener('input', (e) => {
    const v = Number(e.target.value);
    $('budgetOut').textContent = v >= 350 ? 'any' : `up to R$ ${v}`;
  });
  $('hotelForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.submitter || e.target.querySelector('button[type="submit"]');
    $('hotelError').textContent = '';
    const isNew = $('hotelNew').checked;
    const user = isNew ? -1 : Number($('hotelUser').value);
    if (!isNew && (!Number.isInteger(user) || user < 0 || user > 1339)) { $('hotelError').textContent = 'Traveller ID must be a whole number from 0 to 1339, or tick New traveller.'; return; }
    const budget = Number($('hotelBudget').value);
    const body = { userCode: user, origin: $('hotelOrigin').value || null, destination: $('hotelDest').value || null,
                   max_price: budget >= 350 ? null : budget, k: Number($('hotelK').value) };
    btn.setAttribute('aria-busy', 'true'); btn.textContent = 'Finding hotels…';
    try {
      const r = await call('/recommend/hotels', body);
      const list = $('hotelList');
      list.innerHTML = '';
      $('hotelHint').hidden = r.recommendations.length > 0;
      if (!r.recommendations.length) { $('hotelHint').hidden = false; $('hotelHint').textContent = 'No hotel matches these filters. Raise the budget or clear the destination.'; }
      const who = r.known_user ? `Traveller ${r.userCode}`
        : r.userCode >= 0 ? `Traveller ${r.userCode} has no hotel stays yet, so these are the most popular hotels`
        : 'New traveller, so these are the most popular hotels';
      document.querySelectorAll('.hotel-meta').forEach((m) => m.remove());   // replace the previous summary line
      const meta = document.createElement('p');
      meta.className = 'hotel-meta';
      meta.textContent = who + (r.origin ? `, flying from ${cityName(r.origin)}` : '');
      list.before(meta);
      r.recommendations.forEach((h, i) => {
        const li = document.createElement('li');
        li.className = 'hotel';
        li.innerHTML = `<span class="rank">${i + 1}</span>
          <span class="name"></span>
          <span class="nightly">${money(h.price_per_night)}<small>per night</small></span>
          <span class="reason"></span>`;
        li.querySelector('.name').innerHTML = `${h.hotel}<small></small>`;
        li.querySelector('.name small').textContent = cityName(h.city);
        li.querySelector('.reason').textContent = h.reason.replace(/ 1 time\(s\)/, ' once').replace(/time\(s\)/, 'times');
        list.appendChild(li);
      });
    } catch (err) {
      $('hotelError').textContent = err.message;
    } finally { btn.removeAttribute('aria-busy'); btn.textContent = 'Suggest hotels'; }
  });

  // ---------- name form ----------
  $('nameForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.submitter || e.target.querySelector('button[type="submit"]');
    $('nameError').textContent = '';
    const name = $('nameInput').value.trim();
    if (!name) { $('nameError').textContent = 'Enter a name first.'; return; }
    btn.setAttribute('aria-busy', 'true'); btn.textContent = 'Checking…';
    try {
      const r = await call('/predict/gender', { name, age: Number($('nameAge').value), company: $('nameCompany').value });
      const box = $('nameBars');
      const labels = { female: 'Female', male: 'Male', none: 'Not disclosed' };
      const entries = Object.entries(r.probabilities).sort((a, b) => b[1] - a[1]);
      box.innerHTML = `<p class="verdict"></p>`;
      box.querySelector('.verdict').textContent = `Most likely: ${labels[r.predicted_gender] || r.predicted_gender}`;
      entries.forEach(([k, p], i) => {
        const row = document.createElement('div');
        row.className = 'bar-row' + (i === 0 ? ' top' : '');
        row.innerHTML = `<span>${labels[k] || k}</span><div class="bar-track"><div class="bar-fill"></div></div><span>${Math.round(p * 100)}%</span>`;
        box.appendChild(row);
        requestAnimationFrame(() => { row.querySelector('.bar-fill').style.width = (p * 100) + '%'; });
      });
      const note = document.createElement('p');
      note.className = 'note';
      note.textContent = 'An estimate from letter patterns only. Never use it to set or override what a person has told you.';
      box.appendChild(note);
      box.hidden = false; $('nameHint').hidden = true;
    } catch (err) {
      $('nameError').textContent = err.message;
    } finally { btn.removeAttribute('aria-busy'); btn.textContent = 'Check name'; }
  });

  // ---------- insights (static data from the EDA, no API needed) ----------
  let insightsDone = false;
  async function renderInsights() {
    if (insightsDone) return;
    insightsDone = true;
    let d;
    try { d = await (await fetch('data/insights.json')).json(); }
    catch (_) { $('insightsLede').textContent = 'The insights data could not be loaded.'; return; }
    const k = d.kpis;
    const facts = [['Flight legs', k.flight_legs], ['Round trips', k.trips], ['Hotel stays', k.hotel_stays], ['Travellers', k.users], ['Cities', k.cities]];
    $('facts').innerHTML = facts.map(([t, v]) => `<div><dt>${t}</dt><dd>${Number(v).toLocaleString('en-US')}</dd></div>`).join('');
    $('insightsLede').textContent = `Patterns from ${k.date_from.slice(0, 4)}–${k.date_to.slice(0, 4)} flights, hotels and users data behind the models.`;
    if (!window.Chart) return;

    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue('--ink').trim();
    const ipe = css.getPropertyValue('--ipe').trim();
    const text = css.getPropertyValue('--text').trim();
    const muted = css.getPropertyValue('--muted').trim();
    const line = css.getPropertyValue('--line').trim();
    const dark = matchMedia('(prefers-color-scheme: dark)').matches;
    const primary = dark ? ipe : ink;
    Chart.defaults.font.family = css.getPropertyValue('--font');
    Chart.defaults.color = muted;
    Chart.defaults.borderColor = line;
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
    const base = { responsive: true, maintainAspectRatio: false, animation: false };
    const fmtR = (v) => 'R$ ' + Math.round(v);

    new Chart($('chMonthly'), {
      type: 'line',
      data: { labels: d.monthly.labels, datasets: [
        { label: 'Trips per month', data: d.monthly.trips, borderColor: primary, backgroundColor: primary, yAxisID: 'y', tension: .25, pointRadius: 0, borderWidth: 2.5 },
        { label: 'Average outbound fare', data: d.monthly.avg_price, borderColor: muted, backgroundColor: muted, yAxisID: 'y1', borderDash: [5, 4], pointRadius: 0, borderWidth: 1.5 },
      ] },
      options: { ...base, interaction: { mode: 'index', intersect: false },
        scales: { y: { beginAtZero: true, title: { display: true, text: 'Trips' } },
                  y1: { position: 'right', min: 800, max: 1100, grid: { drawOnChartArea: false }, ticks: { callback: fmtR } },
                  x: { ticks: { maxTicksLimit: 8 } } } },
    });
    new Chart($('chClass'), {
      type: 'bar',
      data: { labels: d.price_by_class.labels, datasets: [{ data: d.price_by_class.values, backgroundColor: [line, muted, primary], borderRadius: 4 }] },
      options: { ...base, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmtR(c.raw) } } },
                 scales: { y: { beginAtZero: true, ticks: { callback: fmtR } } } },
    });
    new Chart($('chAgency'), {
      type: 'bar',
      data: { labels: d.agency_class.agencies, datasets: d.agency_class.classes.map((c, i) => ({
        label: c, data: d.agency_class.values.map((row) => row[i]), backgroundColor: [line, muted, primary][i], borderRadius: 3 })) },
      options: { ...base, scales: { x: { stacked: true }, y: { stacked: true, ticks: { callback: (v) => (v / 1000) + 'k' } } } },
    });
    new Chart($('chAttach'), {
      type: 'bar',
      data: { labels: d.hotel_attach.labels.map(cityName), datasets: [{ data: d.hotel_attach.rate, backgroundColor: primary, borderRadius: 3 }] },
      options: { ...base, indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => c.raw + ' stays per 100 trips' } } },
                 scales: { x: { min: 0, max: 100, ticks: { callback: (v) => v } } } },
    });
    new Chart($('chHotelPrice'), {
      type: 'bar',
      data: { labels: d.hotel_price.labels, datasets: [{ data: d.hotel_price.values, backgroundColor: d.hotel_price.values.map((v, i, a) => (i === a.length - 1 || i === 0) ? primary : muted), borderRadius: 3 }] },
      options: { ...base, indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmtR(c.raw) + ' per night' } } },
                 scales: { x: { beginAtZero: true, ticks: { callback: fmtR } }, y: { ticks: { color: text } } } },
    });

    // Models tab cards come from the same file
  }

  async function renderModels() {
    try {
      const d = await (await fetch('data/insights.json')).json();
      $('modelGrid').innerHTML = '';
      d.models.forEach((m) => {
        const card = document.createElement('article');
        card.className = 'model';
        card.innerHTML = `<h3></h3><p class="algo"></p><dl></dl><p class="registry">Registered as <code></code></p>`;
        card.querySelector('h3').textContent = m.task;
        card.querySelector('.algo').textContent = m.model;
        card.querySelector('code').textContent = m.registry;
        const dl = card.querySelector('dl');
        Object.entries(m.metrics).forEach(([k, v]) => {
          const row = document.createElement('div');
          row.innerHTML = '<dt></dt><dd></dd>';
          row.querySelector('dt').textContent = k; row.querySelector('dd').textContent = v;
          dl.appendChild(row);
        });
        $('modelGrid').appendChild(card);
      });
    } catch (_) { /* leave empty */ }
  }

  renderModels();
  connect();
})();

"""Page-side JavaScript snippets used by Playwright evaluate() calls."""

CLICK_RELATED_TAB_JS = """
(wanted) => {
  const a = [...document.querySelectorAll('ul.related-games-nav a')]
    .find(x => (x.innerText || '').trim() === wanted);
  if (!a) return { clicked: false, href: '' };
  a.click();
  return { clicked: true, href: a.getAttribute('href') || '' };
}
"""

FILL_GAME_SEARCH_JS = """
(wanted) => {
  const el = document.querySelector('#game-search');
  if (!el) return { ok: false, reason: 'no_game_search' };
  const plat = document.querySelector('#platforms-search');
  const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  proto.call(el, wanted);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
  el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
  return {
    ok: true,
    value: el.value,
    platformValue: plat ? (plat.value || '') : ''
  };
}
"""

SCRAPE_CARDS_JS = """
(parentSlug) => {
  const items = [];
  const seen = new Set();
  const root = document.querySelector('.related-games-container') || document;
  for (const a of root.querySelectorAll('.other-game.game a[href*="/games/"], a.ui-tooltip[href*="/games/"]')) {
    const href = a.getAttribute('href') || '';
    if (!href.includes('/games/')) continue;
    const slug = href.replace(/^.*\\/games\\//, '').split(/[?#]/)[0];
    if (!slug || slug === parentSlug || href.includes('/' + parentSlug + '/')) continue;
    if (seen.has(slug)) continue;
    seen.add(slug);
    const cover = a.querySelector('.game-cover');
    const tip = a.querySelector('.tooltip-item');
    const lab = a.querySelector('.label');
    const title = ((tip && tip.textContent) || (cover && cover.getAttribute('alt')) || slug).trim();
    const itemLabel = ((lab && lab.textContent) || '').trim();
    items.push({ title, slug, href, itemLabel });
  }
  return items;
}
"""

READ_MENUS_JS = """
() => {
  const labelFor = (el) => {
    if (!el) return '';
    if (el.id) {
      const lab = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (lab) return (lab.innerText || '').trim();
    }
    const wrap = el.closest('label, .form-group, .field, .form-item, .mb-3, .col');
    if (wrap) {
      const t = (wrap.innerText || '').trim().split('\\n')[0];
      if (t) return t.slice(0, 120);
    }
    return (el.getAttribute('aria-label') || el.name || el.id || '').trim();
  };
  const selects = [...document.querySelectorAll('select')].map(s => ({
    id: s.id || '',
    name: s.name || '',
    label: labelFor(s),
    options: [...s.options].map(o => ({
      value: o.value,
      text: (o.text || '').trim(),
      selected: !!o.selected
    }))
  }));
  const checkboxes = [...document.querySelectorAll('input[type=checkbox]')].map(c => {
    let text = labelFor(c);
    const sib = c.parentElement ? (c.parentElement.innerText || '').trim() : '';
    if (sib && sib.length < 160) text = sib;
    return {
      id: c.id || '',
      name: c.name || '',
      label: text.slice(0, 160),
      checked: !!c.checked,
      value: c.value || ''
    };
  });
  const headingBits = [...document.querySelectorAll('label, h2, h3, h4, legend, .form-label')]
    .map(el => (el.innerText || '').trim())
    .filter(t => /edition|dlc|expansion|addon|pack|additional|extra|content/i.test(t))
    .slice(0, 30);
  const dlcSelect = selects.find(s => (s.options || []).some(o => /Add DLC to your game/i.test(o.text || '')));
  const addonBoxes = checkboxes.filter(c => /^addon-\\d+$/i.test(c.id || ''));
  const body = document.body.innerText || '';
  const editionMatch = body.match(/GAME EDITION\\s+([^\\n]+)/i);
  const ownedMatch = body.match(/Owned DLC\\s*([\\s\\S]*?)ADDONS\\/PACKS/i);
  const ownedDlc = ownedMatch
    ? ownedMatch[1].split('\\n').map(l => l.trim()).filter(l => l && !/^(No Status|Not Started|Unfinished|Beaten|Completed|Continuous|Dropped)$/i.test(l))
    : [];
  return {
    selects,
    checkboxes,
    headingBits,
    dlcSelect: dlcSelect || null,
    addonBoxes,
    editionText: (editionMatch && editionMatch[1] || '').trim(),
    ownedDlc
  };
}
"""

FILL_ADD_FORM_JS = """
({ platformText, digital }) => {
  const onEdit = [...document.querySelectorAll('button')].some(b => (b.innerText || '').trim() === 'UPDATE GAME');
  if (onEdit) {
    return { skipped: 'parent_edit_form', clicked: null };
  }
  const path = (location.pathname || '');
  if (!path.includes('/games/add/')) {
    return { skipped: 'not_add_form', url: location.href, clicked: null };
  }
  const setSelect = (select, wantedList) => {
    if (!select) return null;
    const opts = [...select.options];
    if (opts.some(o => /Add DLC to your game/i.test(o.text || ''))) return null;
    for (const wanted of wantedList) {
      const hit = opts.find(o => (o.text || '').trim().toLowerCase() === wanted.toLowerCase())
        || opts.find(o => (o.text || '').toLowerCase().includes(wanted.toLowerCase()));
      if (hit) {
        const proto = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
        proto.call(select, hit.value);
        select.dispatchEvent(new Event('input', { bubbles: true }));
        select.dispatchEvent(new Event('change', { bubbles: true }));
        return (hit.text || '').trim();
      }
    }
    return null;
  };
  const skip = /acquisit|source|amount|note|price|cost|borrow|lent|condition|region/i;
  const report = { platform: null, ownership: null, status: null, digital: null, clicked: null };

  for (const sel of document.querySelectorAll('select')) {
    const meta = ((sel.id || '') + ' ' + (sel.name || '') + ' ' + ((sel.previousElementSibling && sel.previousElementSibling.innerText) || '')).toLowerCase();
    const labelEl = sel.id ? document.querySelector('label[for="' + sel.id + '"]') : null;
    const label = ((labelEl && labelEl.innerText) || meta).toLowerCase();
    if (skip.test(label + meta)) continue;
    if ([...sel.options].some(o => /Add DLC to your game/i.test(o.text || ''))) continue;
    if (/platform/.test(label + meta) || sel.id === 'platform-select' || sel.id === 'null-select') {
      if (platformText) report.platform = setSelect(sel, [platformText]);
    }
  }

  const wantedPlatform = String(platformText || '').trim();
  if (wantedPlatform && (report.platform || '').trim() !== wantedPlatform) {
    report.clicked = null;
    report.refused = 'platform_not_exact';
    return report;
  }

  const digitalBox = document.getElementById('digital')
    || [...document.querySelectorAll('input[type=checkbox]')].find(c => /digital/.test((c.id || '') + (c.name || '')));
  const physicalBox = document.getElementById('physical');
  if (digital === true && digitalBox && !digitalBox.checked) {
    digitalBox.click();
    digitalBox.dispatchEvent(new Event('change', { bubbles: true }));
  }
  if (digital === false && physicalBox && !physicalBox.checked) {
    physicalBox.click();
    physicalBox.dispatchEvent(new Event('change', { bubbles: true }));
  }
  report.digital = digitalBox ? !!digitalBox.checked : null;

  const btn = [...document.querySelectorAll('button')].find(b => {
    const t = (b.innerText || '').trim();
    if (/DELETE/i.test(t)) return false;
    return /^(ADD TO COLLECTION|ADD GAME|SAVE|ADD)$/i.test(t);
  });
  if (btn) {
    btn.click();
    report.clicked = (btn.innerText || '').trim();
  }
  return report;
}
"""

NAME_MATCH_JS = """
const ibNorm = (s, parentTitle) => {
  let t = (s || '').toLowerCase().replace(/\\u2019/g, "'").replace(/reticle/g, 'reticule');
  const prefixes = ['tomb raider:', 'tomb raider -', 'tomb raider '];
  if (parentTitle) {
    const pt = parentTitle.toLowerCase().trim();
    prefixes.push(pt + ':', pt + ' -', pt + ' ');
  }
  for (const p of prefixes) {
    if (t.startsWith(p)) { t = t.slice(p.length).trim(); break; }
  }
  t = t.replace(/[^a-z0-9]+/g, ' ');
  t = t.replace(/\\b(skin|pack|dlc|addon|add on|bonus content|bonus|content)\\b/g, ' ');
  return t.replace(/\\s+/g, ' ').trim();
};
const ibNamesMatch = (query, candidate, parentTitle) => {
  const q = ibNorm(query, parentTitle);
  const c = ibNorm(candidate, parentTitle);
  if (!q || !c) return false;
  if (q === c || q.includes(c) || c.includes(q)) return true;
  const qt = new Set(q.split(' ').filter(Boolean));
  const ct = new Set(c.split(' ').filter(Boolean));
  if (!qt.size || !ct.size) return false;
  const [shorter, longer] = qt.size <= ct.size ? [qt, ct] : [ct, qt];
  for (const w of shorter) if (!longer.has(w)) return false;
  return true;
};
"""

SELECT_DLC_OPTION_JS = """
({ wanted, parentTitle }) => {
""" + NAME_MATCH_JS + """
  const sel = [...document.querySelectorAll('select')].find(s =>
    [...s.options].some(o => /Add DLC to your game/i.test(o.text || ''))
  );
  if (!sel) return { error: 'no_dlc_select' };
  const hit = [...sel.options].find(o => o.value && ibNamesMatch(wanted, o.text || '', parentTitle));
  if (!hit) {
    return {
      error: 'not_in_dropdown',
      remaining: [...sel.options].map(o => (o.text || '').trim())
    };
  }
  const proto = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  proto.call(sel, hit.value);
  sel.dispatchEvent(new Event('input', { bubbles: true }));
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  return {
    picked: (hit.text || '').trim(),
    game_id: hit.value ? Number(hit.value) : null
  };
}
"""

TICK_ONE_ADDON_JS = """
({ wanted, parentTitle }) => {
""" + NAME_MATCH_JS + """
  for (const c of document.querySelectorAll('input[type=checkbox][id^="addon-"]')) {
    const lab = document.querySelector('label[for="' + CSS.escape(c.id) + '"]');
    const text = ((lab && lab.innerText) || (c.parentElement && c.parentElement.innerText) || '').trim();
    if (!ibNamesMatch(wanted, text, parentTitle)) continue;
    const gid = Number(String(c.id).replace(/^addon-/, '')) || null;
    if (c.checked) return { status: 'already', id: c.id, label: text, game_id: gid };
    c.click();
    if (!c.checked) {
      const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked').set;
      proto.call(c, true);
      c.dispatchEvent(new Event('input', { bubbles: true }));
      c.dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (!c.checked) return { error: 'not_checked', id: c.id, label: text, game_id: gid };
    return { status: 'clicked', id: c.id, label: text, game_id: gid };
  }
  return { error: 'no_addon_checkbox' };
}
"""

PARENT_FORM_SNAPSHOT_JS = """
() => {
  const body = document.body.innerText || '';
  const editionMatch = body.match(/GAME EDITION\\s+([^\\n]+)/i);
  const acq = document.getElementById('Acquisition-select');
  const ds = document.getElementById('Digital Service-select');
  return {
    digital: !!(document.getElementById('digital') && document.getElementById('digital').checked),
    physical: !!(document.getElementById('physical') && document.getElementById('physical').checked),
    played: !!(document.getElementById('progress-played') && document.getElementById('progress-played').checked),
    unplayed: !!(document.getElementById('progress-unplayed') && document.getElementById('progress-unplayed').checked),
    owned: !!(document.getElementById('ownership-owned') && document.getElementById('ownership-owned').checked),
    editionText: ((editionMatch && editionMatch[1]) || '').trim(),
    acquisition: acq && acq.options[acq.selectedIndex] ? (acq.options[acq.selectedIndex].text || '').trim() : '',
    digitalService: ds && ds.options[ds.selectedIndex] ? (ds.options[ds.selectedIndex].text || '').trim() : ''
  };
}
"""

CLICK_UPDATE_GAME_JS = """
() => {
  const btn = [...document.querySelectorAll('button')].find(b => (b.innerText || '').trim() === 'UPDATE GAME');
  if (!btn) return { clicked: false };
  btn.click();
  return { clicked: true };
}
"""

ADDON_BOX_STATE_JS = """
() => [...document.querySelectorAll('input[type=checkbox][id^="addon-"]')].map(c => ({
  id: c.id,
  checked: !!c.checked,
  label: ((c.nextElementSibling && c.nextElementSibling.innerText) || '').trim()
}))
"""

SNAPSHOT_PLATFORM_TABS_JS = """
() => {
  const plus = document.querySelector('button.extra-platform');
  const tabs = [...document.querySelectorAll('ul.nav-collection-game-platforms li')].map(li => ({
    text: (li.innerText || '').trim(),
    active: li.classList.contains('active')
  }));
  return {
    plus: !!plus,
    plus_selector: 'button.extra-platform',
    copies_tabs: tabs
  };
}
"""

SNAPSHOT_PROGRESS_JS = """
() => {
  const radios = [...document.querySelectorAll('input[type=radio]')].map(c => ({
    id: c.id || '',
    name: c.name || '',
    value: c.value || '',
    checked: !!c.checked,
    label: ((c.labels && c.labels[0] && c.labels[0].innerText) || '').trim()
  }));
  const status = radios.filter(r => r.name === 'status');
  const completion = radios.filter(r => r.name === 'completion');
  const notes = document.getElementById('progress-note');
  const slider = document.querySelector('.progress-bar .vue-slider-dot');
  return {
    status,
    completion,
    notes: notes ? (notes.value || '') : null,
    progress_bar: slider ? {
      now: slider.getAttribute('aria-valuenow'),
      min: slider.getAttribute('aria-valuemin'),
      max: slider.getAttribute('aria-valuemax'),
      text: slider.getAttribute('aria-valuetext')
    } : null
  };
}
"""

SNAPSHOT_ACQUISITION_JS = """
() => {
  const selText = (id) => {
    const s = document.getElementById(id);
    if (!s || !s.options[s.selectedIndex]) return null;
    return { id, value: s.value, text: (s.options[s.selectedIndex].text || '').trim() };
  };
  const byLabel = (re) => {
    const h = [...document.querySelectorAll('h6,label,legend')].find(e => re.test((e.innerText || '').trim()));
    if (!h) return null;
    const box = h.closest('.form-group, .col, .mb-3, div') || h.parentElement;
    const el = box && box.querySelector('input, textarea, select');
    if (!el) return null;
    return { id: el.id || '', value: el.value || '', placeholder: el.placeholder || '' };
  };
  const deleteBtns = [...document.querySelectorAll('button')].map(b => (b.innerText || '').trim()).filter(t => /DELETE/i.test(t));
  const playTab = document.querySelector('li.stats-link a, ul.nav-collection-game a[href*=\"/edit/stats\"]');
  const tags = [...document.querySelectorAll('h4')].some(h => /CUSTOM TAGS/i.test(h.innerText || ''));
  const unlockTags = [...document.querySelectorAll('button')].some(b => /UNLOCK CUSTOM TAGS/i.test(b.innerText || ''));
  return {
    acquisition: selText('Acquisition-select'),
    digital_service: selText('Digital Service-select'),
    source: byLabel(/Acquisition Source/i) || document.querySelector('input[placeholder*=\"GameStop\"]') && {
      id: (document.querySelector('input[placeholder*=\"GameStop\"]') || {}).id || '',
      value: (document.querySelector('input[placeholder*=\"GameStop\"]') || {}).value || '',
      placeholder: 'GameStop, Amazon, etc'
    },
    date: (() => { const el = document.getElementById('purchaseDate'); return el ? { id: 'purchaseDate', value: el.value || '' } : null; })(),
    amount: byLabel(/^Amount Paid/i),
    additional_cost: byLabel(/^Additional Cost/i),
    notes: (() => { const el = document.getElementById('acquisition-notes'); return el ? { id: 'acquisition-notes', value: el.value || '' } : null; })(),
    delete_buttons: deleteBtns,
    play_records_tab: playTab ? { href: playTab.getAttribute('href'), text: (playTab.innerText || '').trim() } : null,
    custom_tags: tags,
    unlock_custom_tags: unlockTags
  };
}
"""

SET_ACQUISITION_FORM_JS = """
({ acquisition, source, date, amount, additionalCost, notes, digitalService, subscription }) => {
  const report = {};
  const setSelect = (id, wanted) => {
    const sel = document.getElementById(id);
    if (!sel) return 'missing';
    if (wanted === '' || wanted === null) {
      const proto = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
      proto.call(sel, '');
      sel.dispatchEvent(new Event('input', { bubbles: true }));
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      return '';
    }
    const opts = [...sel.options];
    const hit = opts.find(o => (o.value || '') === wanted)
      || opts.find(o => (o.text || '').trim().toLowerCase() === String(wanted).toLowerCase())
      || opts.find(o => (o.text || '').toLowerCase().includes(String(wanted).toLowerCase()));
    if (!hit) return 'no_option';
    const proto = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
    proto.call(sel, hit.value);
    sel.dispatchEvent(new Event('input', { bubbles: true }));
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return (hit.text || '').trim();
  };
  const setInput = (el, value) => {
    if (!el) return false;
    const proto = Object.getOwnPropertyDescriptor(
      el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype,
      'value'
    ).set;
    proto.call(el, value == null ? '' : String(value));
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };
  const inputByLabel = (re) => {
    const h = [...document.querySelectorAll('h6,label,legend')].find(e => re.test((e.innerText || '').trim()));
    const box = h && (h.closest('.form-group, .col, .mb-3, div') || h.parentElement);
    return box && box.querySelector('input, textarea');
  };
  const walk = (vm) => {
    if (!vm) return null;
    if (vm.collectionGame && vm.collectionGame.id) return vm;
    for (const c of (vm.$children || [])) {
      const hit = walk(c);
      if (hit) return hit;
    }
    return null;
  };
  const root = document.querySelector('#app');
  const vm = walk(root && root.__vue__);
  const g = vm && vm.collectionGame;
  const setVue = (key, val) => {
    if (!g || !vm) return;
    vm.$set(g, key, val);
  };
  if (acquisition !== undefined) {
    report.acquisition = setSelect('Acquisition-select', acquisition);
    setVue('acquisition', acquisition === '' ? null : acquisition);
  }
  if (digitalService !== undefined) {
    report.digital_service = setSelect('Digital Service-select', digitalService);
    setVue('digital_store', digitalService === '' ? null : digitalService);
  }
  if (subscription !== undefined) {
    report.subscription = setSelect('Subscription-select', subscription);
    setVue('subscription', subscription === '' ? null : subscription);
  }
  if (source !== undefined) {
    const el = document.querySelector('input[placeholder*=\"GameStop\"]') || inputByLabel(/Acquisition Source/i);
    report.source = setInput(el, source);
    setVue('purchase_place_name', source === '' ? null : source);
  }
  if (date !== undefined) {
    report.date = setInput(document.getElementById('purchaseDate'), date);
    setVue('purchase_date', date === '' ? null : date);
  }
  if (amount !== undefined) {
    const n = amount === '' || amount === null ? '' : amount;
    report.amount = setInput(inputByLabel(/^Amount Paid/i), n === '' ? '' : String(n));
    const num = n === '' ? null : Number(n);
    setVue('purchase_price', n === '' ? null : (Number.isFinite(num) ? num : n));
  }
  if (additionalCost !== undefined) {
    report.additional_cost = setInput(inputByLabel(/^Additional Cost/i), additionalCost);
    setVue('additional_cost', additionalCost === '' ? null : additionalCost);
  }
  if (notes !== undefined) {
    report.notes = setInput(document.getElementById('acquisition-notes'), notes);
    setVue('acquisition_notes', notes === '' ? null : notes);
  }
  return report;
}
"""

SNAPSHOT_PLAY_RECORDS_JS = """
() => {
  const walk = (vm, pred, depth) => {
    if (!vm || depth > 25) return null;
    if (pred(vm)) return vm;
    for (const c of (vm.$children || [])) {
      const hit = walk(c, pred, depth + 1);
      if (hit) return hit;
    }
    return null;
  };
  const root = document.querySelector('#app');
  const page = walk(root && root.__vue__, (v) => typeof v.addCategory === 'function', 0);
  const gs = page && page.gameStats;
  const cats = (gs && gs.categories) || (page && page.visibleStats && page.visibleStats.categories) || [];
  const slimCat = (c) => ({
    id: c && c.id,
    name: c && c.name,
    type: c && c.type,
    columns: c && (c.columns || c.layout),
    order: c && c.order,
    data_len: c && Array.isArray(c.data) ? c.data.length : 0,
    children_len: c && Array.isArray(c.children) ? c.children.length : 0,
    data: c && Array.isArray(c.data) ? c.data.slice(0, 20) : []
  });
  const addBtn = [...document.querySelectorAll('button')].some(b => /ADD CATEGORY/i.test(b.innerText || ''));
  const modal = [...document.querySelectorAll('h2,h3,h4')].some(e => /ADD NEW CATEGORY|EDIT CATEGORY/i.test(e.innerText || ''));
  return {
    url: location.href,
    has_add: addBtn,
    add_row: [...document.querySelectorAll('button')].some(b => (b.innerText || '').trim() === 'Add row'),
    add_subcategory: [...document.querySelectorAll('button')].some(b => /Add subcategory/i.test(b.innerText || '')),
    modal_open: modal,
    gameStats_id: gs && gs.id,
    categories: Array.isArray(cats) ? cats.map(slimCat) : [],
    types: ['keyValue', 'checkbox', 'progress', 'table'],
    layout_columns: [1, 2],
    template: 'FIND TEMPLATE uses this game Steam/PSN/Xbox lists'
  };
}
"""

FILL_CATEGORY_MODAL_JS = """
({ name, typeId, columns, submit }) => {
  const report = {};
  const modalOpen = [...document.querySelectorAll('h2,h3,h4')].some(e => /ADD NEW CATEGORY|EDIT CATEGORY|ADD SUBCATEGORY/i.test(e.innerText || ''));
  if (!modalOpen) return { error: 'no_category_modal' };
  const nameEl = document.getElementById('name');
  if (name !== undefined && nameEl) {
    const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    proto.call(nameEl, name == null ? '' : String(name));
    nameEl.dispatchEvent(new Event('input', { bubbles: true }));
    nameEl.dispatchEvent(new Event('change', { bubbles: true }));
    report.name = nameEl.value;
  }
  if (typeId) {
    const el = document.getElementById(typeId);
    if (el) {
      const lab = document.querySelector('label[for=\"' + CSS.escape(typeId) + '\"]');
      if (lab) lab.click();
      else el.click();
      report.type = typeId;
    } else {
      report.type = 'missing';
    }
  }
  if (columns) {
    const id = String(columns) === '2' ? '2-column' : '1-column';
    const el = document.getElementById(id);
    if (el) {
      const lab = document.querySelector('label[for=\"' + CSS.escape(id) + '\"]');
      if (lab) lab.click();
      else el.click();
      report.columns = id;
    }
  }
  if (submit) {
    const submitBtn = [...document.querySelectorAll('button')].filter(b => {
      const t = (b.innerText || '').trim();
      return t === 'ADD CATEGORY' || t === 'UPDATE CATEGORY' || t === 'SAVE';
    }).pop();
    if (submitBtn) {
      submitBtn.click();
      report.submitted = (submitBtn.innerText || '').trim();
    } else {
      report.submitted = false;
    }
  }
  return report;
}
"""

CLICK_EXACT_BUTTON_JS = """
({ exact, forbid }) => {
  const wanted = (exact || '').trim();
  const btn = [...document.querySelectorAll('button')].find(b => {
    const t = (b.innerText || '').trim();
    if (t !== wanted) return false;
    if (forbid && new RegExp(forbid, 'i').test(t)) return false;
    return true;
  });
  if (!btn) return { clicked: false, text: null };
  btn.click();
  return { clicked: true, text: (btn.innerText || '').trim() };
}
"""

PLAY_RECORD_MUTATE_JS = """
({ action, categoryName, categoryId, rowIndex, row, confirmDelete }) => {
  const walk = (vm, pred, depth) => {
    if (!vm || depth > 25) return null;
    if (pred(vm)) return vm;
    for (const c of (vm.$children || [])) {
      const hit = walk(c, pred, depth + 1);
      if (hit) return hit;
    }
    return null;
  };
  const root = document.querySelector('#app');
  const page = walk(root && root.__vue__, (v) => typeof v.addCategory === 'function' || typeof v.getGameStats === 'function', 0);
  if (!page) return { error: 'no_stats_vm' };
  const gs = page.gameStats;
  const cats = (gs && gs.categories) || [];
  const wanted = (categoryName || '').toLowerCase();
  const cat = cats.find(c => String(c.id) === String(categoryId || ''))
    || cats.find(c => (c.name || '').toLowerCase() === wanted)
    || cats.find(c => (c.name || '').toLowerCase().includes(wanted));
  if (action === 'list') {
    return { gameStats_id: gs && gs.id, categories: cats.map(c => ({ id: c.id, name: c.name, type: c.type, data: c.data })) };
  }
  if (action === 'delete_category') {
    if (!confirmDelete) return { error: 'confirm_required' };
    if (!cat) return { error: 'category_not_found', names: cats.map(c => c.name) };
    if (typeof page.deleteCategory === 'function') page.deleteCategory(cat);
    else if (typeof page.confirmDeleteCategory === 'function') page.confirmDeleteCategory(cat);
    return { status: 'deleted_category', id: cat.id, name: cat.name };
  }
  if (!cat) return { error: 'category_not_found', names: cats.map(c => c.name) };
  const statVm = walk(root && root.__vue__, (v) => typeof v.addStats === 'function' && v.category && v.category.id === cat.id, 0)
    || walk(root && root.__vue__, (v) => typeof v.addStats === 'function', 0);
  const persist = (category) => {
    const updater = walk(root && root.__vue__, (v) => typeof v.updateCategory === 'function' && v.gameStats && typeof v.addStats === 'function', 0);
    if (updater) {
      try { updater.updateCategory(category); } catch (e) {}
    }
  };
  if (action === 'add_row') {
    if (statVm && typeof statVm.addStats === 'function') statVm.addStats(cat);
    const data = cat.data || [];
    const last = data[data.length - 1];
    if (last && row && typeof row === 'object') {
      for (const k of Object.keys(row)) last[k] = row[k];
    }
    persist(cat);
    return { status: 'row_added', category: cat.name, row: last, data_len: data.length };
  }
  if (action === 'update_row') {
    const data = cat.data || [];
    const idx = Number(rowIndex || 0);
    if (!data[idx]) return { error: 'row_not_found', len: data.length };
    if (row && typeof row === 'object') {
      for (const k of Object.keys(row)) data[idx][k] = row[k];
    }
    persist(cat);
    return { status: 'row_updated', category: cat.name, row: data[idx] };
  }
  if (action === 'remove_row') {
    const idx = Number(rowIndex || 0);
    if (statVm && typeof statVm.removeStat === 'function') statVm.removeStat(cat, idx);
    else if (cat.data) {
      cat.data.splice(idx, 1);
      persist(cat);
    }
    return { status: 'row_removed', category: cat.name, index: idx };
  }
  return { error: 'unknown_action', action };
}
"""

SNAPSHOT_RATINGS_JS = """
() => {
  const card = document.querySelector('.collection-rating');
  if (!card) {
    return {
      widgets: [],
      error: 'no_rating_card',
      hint: 'IB hides .collection-rating while status is Unplayed or No Status. Playing or Played mounts it.'
    };
  }
  return {
    widgets: [...card.querySelectorAll('.star-rating')].map(el => {
      const prev = el.previousElementSibling;
      const label = ((prev && prev.innerText) || '').trim().split('\\n')[0];
      const vue = el.__vue__;
      const stars = vue ? Number(vue.selectedRating || vue.currentRating || 0) : null;
      return {
        label,
        stars,
        score: stars == null ? null : stars * 2,
        increment: vue && vue.increment,
        maxRating: vue && vue.maxRating
      };
    })
  };
}
"""

REVEAL_RATING_CARD_JS = """
() => {
  if (document.querySelector('.collection-rating')) {
    return { revealed: false, already: true };
  }
  const walk = (vm) => {
    if (!vm) return null;
    if (vm.collectionGame && typeof vm.showCompletion === 'boolean') return vm;
    for (const c of (vm.$children || [])) {
      const hit = walk(c);
      if (hit) return hit;
    }
    return null;
  };
  const root = document.querySelector('#app');
  const vm = walk(root && root.__vue__);
  if (!vm || !vm.collectionGame) return { error: 'no_collection_game_vm' };
  const prev = vm.collectionGame.status;
  if (prev === 'playing' || prev === 'played') {
    return { revealed: false, status: prev, showCompletion: vm.showCompletion };
  }
  vm.$set(vm.collectionGame, 'status', 'playing');
  vm.$forceUpdate();
  return {
    revealed: true,
    previous_status: prev,
    showCompletion: vm.showCompletion
  };
}
"""

RESTORE_COLLECTION_STATUS_JS = """
({ status }) => {
  if (!status) return { restored: false };
  const walk = (vm) => {
    if (!vm) return null;
    if (vm.collectionGame && typeof vm.showCompletion === 'boolean') return vm;
    for (const c of (vm.$children || [])) {
      const hit = walk(c);
      if (hit) return hit;
    }
    return null;
  };
  const root = document.querySelector('#app');
  const vm = walk(root && root.__vue__);
  if (!vm || !vm.collectionGame) return { restored: false, error: 'no_collection_game_vm' };
  vm.$set(vm.collectionGame, 'status', status);
  vm.$forceUpdate();
  return { restored: true, status: vm.collectionGame.status };
}
"""

SET_STAR_RATING_JS = """
({ label, starId, position, clear }) => {
  const card = document.querySelector('.collection-rating');
  if (!card) return { error: 'no_rating_card' };
  const widgets = [...card.querySelectorAll('.star-rating')].map(el => {
    const prev = el.previousElementSibling;
    const text = ((prev && prev.innerText) || '').trim().split('\\n')[0];
    return { el, label: text, vue: el.__vue__ };
  });
  const wanted = (label || '').toLowerCase();
  const hit = widgets.find(x => (x.label || '').toLowerCase() === wanted)
    || widgets.find(x => (x.label || '').toLowerCase().includes(wanted));
  if (!hit || !hit.vue || typeof hit.vue.setRating !== 'function') {
    return { error: 'no_widget', label, found: widgets.map(x => x.label) };
  }
  const vue = hit.vue;
  if (clear) {
    const cur = Number(vue.selectedRating || vue.currentRating || 0);
    if (!cur) return { status: 'already_empty', label: hit.label };
    const id = Math.max(1, Math.ceil(cur - 1e-9));
    const frac = cur - (id - 1);
    const pos = Math.round(frac * 100) || 100;
    vue.setRating({ id: id, position: pos }, true);
    return { status: 'cleared', label: hit.label, previous_stars: cur };
  }
  vue.setRating({ id: starId, position: position }, true);
  return {
    status: 'set',
    label: hit.label,
    starId,
    position,
    current_stars: vue.currentRating
  };
}
"""

SET_PROGRESS_FORM_JS = """
({ statusId, completionId, notes, progress }) => {
  const report = { status: null, completion: null, notes: null, progress: null };
  const clickId = (id) => {
    const el = document.getElementById(id);
    if (!el) return false;
    const lab = document.querySelector('label[for="' + CSS.escape(id) + '"]');
    if (lab) lab.click();
    else el.click();
    return true;
  };
  if (statusId) {
    report.status = clickId('progress-' + statusId) ? statusId : 'missing';
  }
  if (completionId) {
    report.completion = clickId('completion-' + completionId) ? completionId : 'missing';
  }
  if (notes !== null && notes !== undefined) {
    const ta = document.getElementById('progress-note');
    if (ta) {
      const proto = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      proto.call(ta, notes);
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      ta.dispatchEvent(new Event('change', { bubbles: true }));
      report.notes = notes;
    } else {
      report.notes = 'missing';
    }
  }
  if (progress !== null && progress !== undefined) {
    const el = document.querySelector('.progress-bar .vue-slider');
    const findSet = (vm) => {
      if (!vm) return null;
      if (typeof vm.setValue === 'function') return vm;
      for (const c of (vm.$children || [])) {
        const hit = findSet(c);
        if (hit) return hit;
      }
      return null;
    };
    const slider = el && findSet(el.__vue__);
    if (slider) {
      slider.setValue(Number(progress));
      report.progress = Number(progress);
    } else {
      report.progress = 'no_slider';
    }
  }
  return report;
}
"""

LIST_PLATFORM_OPTIONS_JS = """
() => {
  const isPlaceholder = (text, value) => {
    const t = (text || '').trim();
    const v = String(value == null ? '' : value).trim();
    if (!t) return true;
    if (!v || v === '0' || v === 'null') return true;
    if (/^(select|choose|platform|none)$/i.test(t)) return true;
    return false;
  };
  const options = [];
  const seen = new Set();
  for (const sel of document.querySelectorAll('select')) {
    const meta = ((sel.id || '') + ' ' + (sel.name || '')).toLowerCase();
    const labelEl = sel.id ? document.querySelector('label[for="' + sel.id + '"]') : null;
    const label = ((labelEl && labelEl.innerText) || meta).toLowerCase();
    if (/edition|acquisit|service|language|completion/i.test(label + meta + (sel.id || ''))) continue;
    if ([...sel.options].some(o => /Add DLC to your game/i.test(o.text || ''))) continue;
    if (!(/platform/.test(label + meta) || sel.id === 'platform-select' || sel.id === 'null-select')) continue;
    for (const o of sel.options) {
      const text = (o.text || '').trim();
      if (isPlaceholder(text, o.value)) continue;
      const key = text.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      options.push(text);
    }
  }
  return options;
}
"""

FILL_PLATFORM_COPY_JS = """
({ platformText, digital }) => {
  const setSelect = (select, wantedList) => {
    if (!select) return null;
    if ([...select.options].some(o => /Add DLC to your game/i.test(o.text || ''))) return null;
    const opts = [...select.options];
    for (const wanted of wantedList) {
      const hit = opts.find(o => (o.text || '').trim().toLowerCase() === wanted.toLowerCase())
        || opts.find(o => (o.text || '').toLowerCase().includes(wanted.toLowerCase()));
      if (hit) {
        const proto = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
        proto.call(select, hit.value);
        select.dispatchEvent(new Event('input', { bubbles: true }));
        select.dispatchEvent(new Event('change', { bubbles: true }));
        return (hit.text || '').trim();
      }
    }
    return null;
  };
  const report = { platform: null, digital: null, ownership: null };
  for (const sel of document.querySelectorAll('select')) {
    const meta = ((sel.id || '') + ' ' + (sel.name || '')).toLowerCase();
    const labelEl = sel.id ? document.querySelector('label[for="' + sel.id + '"]') : null;
    const label = ((labelEl && labelEl.innerText) || meta).toLowerCase();
    if (/edition|acquisit|service|language|completion/i.test(label + meta + (sel.id || ''))) continue;
    if ([...sel.options].some(o => /Add DLC to your game/i.test(o.text || ''))) continue;
    if (/platform/.test(label + meta) || sel.id === 'platform-select' || sel.id === 'null-select') {
      if (platformText) report.platform = setSelect(sel, [platformText]);
    }
  }
  const digitalBox = document.getElementById('digital');
  const physicalBox = document.getElementById('physical');
  if (digital === true && digitalBox && !digitalBox.checked) digitalBox.click();
  if (digital === false && physicalBox && !physicalBox.checked) physicalBox.click();
  report.digital = digitalBox ? !!digitalBox.checked : null;
  return report;
}
"""

CLICK_NAMED_BUTTON_JS = """
({ names, forbid }) => {
  const wanted = (names || []).map(n => n.trim().toLowerCase());
  const btn = [...document.querySelectorAll('button')].find(b => {
    const t = (b.innerText || '').trim();
    if (!t) return false;
    if (forbid && new RegExp(forbid, 'i').test(t)) return false;
    return wanted.includes(t.toLowerCase());
  });
  if (!btn) return { clicked: false, text: null };
  btn.click();
  return { clicked: true, text: (btn.innerText || '').trim() };
}
"""

FILL_REVIEW_FORM_JS = """
({ body, title, spoilers, mature, feed, language, platform, completion }) => {
  const report = {};
  const walk = (vm, pred, depth) => {
    if (!vm || depth > 25) return null;
    if (pred(vm)) return vm;
    for (const c of (vm.$children || [])) {
      const hit = walk(c, pred, depth + 1);
      if (hit) return hit;
    }
    return null;
  };
  const root = document.querySelector('#app');
  const page = walk(root && root.__vue__, (v) => v.review && (typeof v.saveDraft === 'function' || typeof v.publish === 'function'), 0);
  const editorVm = walk(root && root.__vue__, (v) => v.editor && v.editor.commands, 0);
  const html = '<p>' + String(body || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g, '</p><p>') + '</p>';
  const setBox = (id, on) => {
    const el = document.getElementById(id);
    if (!el) return null;
    if (!!el.checked !== !!on) el.click();
    return !!el.checked;
  };
  report.spoilers = setBox('spoilers', !!spoilers);
  report.mature = setBox('mature-content', !!mature);
  report.feed = setBox('post-feed', !!feed);
  if (page && page.review) {
    if (typeof spoilers === 'boolean') page.$set(page.review, 'spoilers', !!spoilers);
    if (typeof mature === 'boolean') page.$set(page.review, 'mature_content', !!mature);
    if (typeof feed === 'boolean') page.$set(page.review, 'post_feed', !!feed);
    if (title !== null && title !== undefined) page.$set(page.review, 'title', title);
    if (body) page.$set(page.review, 'content', html);
    report.vue_model = true;
  }
  if (title !== null && title !== undefined) {
    const inp = document.getElementById('review-title');
    if (inp) {
      const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      proto.call(inp, title);
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
      report.title = title;
    }
  }
  if (editorVm && editorVm.editor && body) {
    if (typeof editorVm.editor.commands.setContent === 'function') {
      editorVm.editor.commands.setContent(html);
    } else if (typeof editorVm.editor.commands.insertContent === 'function') {
      editorVm.editor.commands.clearContent();
      editorVm.editor.commands.insertContent(html);
    }
    report.editor = 'tiptap';
    report.body_len = String(body).length;
  } else {
    const pm = document.querySelector('.ProseMirror');
    if (pm && body) {
      pm.focus();
      pm.innerHTML = html;
      pm.dispatchEvent(new Event('input', { bubbles: true }));
      report.body_len = String(body).length;
      report.editor = 'prosemirror_dom';
    } else {
      report.body_len = body ? String(body).length : 0;
      if (!document.querySelector('.ProseMirror')) report.prosemirror = 'missing';
    }
  }
  const setSelect = (id, wanted) => {
    if (!wanted) return null;
    const sel = document.getElementById(id);
    if (!sel) return null;
    const opts = [...sel.options];
    const hit = opts.find(o => (o.value || '') === wanted)
      || opts.find(o => (o.text || '').trim().toLowerCase() === wanted.toLowerCase())
      || opts.find(o => (o.text || '').toLowerCase().includes(wanted.toLowerCase()));
    if (!hit) return null;
    const proto = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
    proto.call(sel, hit.value);
    sel.dispatchEvent(new Event('input', { bubbles: true }));
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return (hit.text || '').trim();
  };
  report.language = setSelect('Language-select', language);
  report.platform = setSelect('Platform-select', platform);
  report.completion = setSelect('Completion-select', completion);
  return report;
}
"""

CALL_REVIEW_SAVE_JS = """
({ publish }) => {
  const walk = (vm, pred, depth) => {
    if (!vm || depth > 25) return null;
    if (pred(vm)) return vm;
    for (const c of (vm.$children || [])) {
      const hit = walk(c, pred, depth + 1);
      if (hit) return hit;
    }
    return null;
  };
  const root = document.querySelector('#app');
  const page = walk(root && root.__vue__, (v) => typeof v.saveDraft === 'function' || typeof v.publish === 'function', 0);
  if (!page) return { clicked: false, error: 'no_review_vm' };
  if (publish) {
    if (typeof page.publish === 'function') {
      page.publish();
      return { clicked: true, method: 'publish' };
    }
    return { clicked: false, error: 'no_publish' };
  }
  if (typeof page.saveDraft === 'function') {
    page.saveDraft();
    return { clicked: true, method: 'saveDraft' };
  }
  return { clicked: false, error: 'no_saveDraft' };
}
"""

FETCH_API_JS = """
async ({ path, method, body }) => {
  if (typeof path !== 'string' || !path.startsWith('/api')) {
    return { ok: false, status: 0, data: { error: 'invalid_api_path' } };
  }
  if (path.includes('://') || path.startsWith('//') || path.includes('\\\\') || path.includes('\\n')) {
    return { ok: false, status: 0, data: { error: 'invalid_api_path' } };
  }
  const opts = { method: method || 'GET', credentials: 'include', headers: {} };
  if (body !== null && body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
  return { ok: r.ok, status: r.status, data };
}
"""

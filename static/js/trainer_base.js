var IS_READONLY = window._IS_READONLY || false;

function speakText(text) {
  if (!text) return;
  var audio = new Audio('/api/tts?text=' + encodeURIComponent(text));
  audio.play().catch(function() {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    var u = new SpeechSynthesisUtterance(text);
    u.lang = 'ko-KR';
    u.rate = 0.85;
    window.speechSynthesis.speak(u);
  });
}

function randExcept(len, cur) {
  if (len <= 1) return 0;
  var i;
  do { i = Math.floor(Math.random() * len); } while (i === cur);
  return i;
}

var studentId = window._studentId || '';
var DRAFT_KEY = 'draft_trainer_' + studentId;
var HISTORY_KEY = 'history_' + studentId;

// ── PROGRESS TRACKING ──
var MODULE_NAME = document.body.dataset.module || 'unknown';
var sessionId = null;
var exercisesDone = 0;
var sessionStart = Date.now();

async function trackPing() {
  if (IS_READONLY || !studentId) return;
  try {
    var r = await fetch('/api/progress/ping', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ student_id: parseInt(studentId), module: MODULE_NAME })
    });
    var data = await r.json();
    if (data.ok) sessionId = data.session_id;
  } catch(e) {}
}

async function trackExercise() {
  if (IS_READONLY) return;
  exercisesDone++;
  if (!studentId) return;
  try {
    await fetch('/api/progress/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        student_id: parseInt(studentId),
        module: MODULE_NAME,
        session_id: sessionId,
        duration_sec: Math.round((Date.now() - sessionStart) / 1000)
      })
    });
  } catch(e) {}
}

trackPing();

// ── GLOBAL GRAMMAR SEARCH ──
(function() {
  var searchInput  = document.getElementById('g-search-input');
  var dropdown     = document.getElementById('g-search-dropdown');
  var overlay      = document.getElementById('g-modal-overlay');
  var modalTitle   = document.getElementById('g-modal-title');
  var modalFormula = document.getElementById('g-modal-formula');
  var modalBadge   = document.getElementById('g-modal-badge');
  var modalBody    = document.getElementById('g-modal-body');
  var modalClose   = document.getElementById('g-modal-close');

  if (!searchInput) return;

  var grammarIndex = [];
  window._grammarIndex = grammarIndex;

  fetch('/static/data/grammar.json')
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(data) {
      if (!data) return;
      Object.entries(data).forEach(function([level, items]) {
        (items || []).forEach(function(item) {
          if (item.id) grammarIndex.push(Object.assign({}, item, { level: level }));
        });
      });
    })
    .catch(function() {});

  // ── Search helpers ──
  function norm(str) {
    return str.toLowerCase().replace(/[-\/\(\)\[\]·•.,:;!?]/g,'').replace(/\s+/g,' ').trim();
  }
  function exSlash(str) {
    var ex = str.replace(/(\S+)\/(\S+)/g,'$1$2');
    return [norm(ex)].concat(str.split('/').map(function(s) { return norm(s.replace(/[-\s]/g,'')); }));
  }
  function score(item, q) {
    var qv = exSlash(q);
    var fields = [
      norm(item.title||''), norm(item.formula||''), norm(item.category||''),
    ].concat(exSlash(item.title||''), exSlash(item.formula||''));
    var s = 0;
    for (var vi = 0; vi < qv.length; vi++) {
      var v = qv[vi];
      if (!v) continue;
      for (var fi = 0; fi < fields.length; fi++) {
        var f = fields[fi];
        if (f === v) { s += 100; break; }
        if (f.startsWith(v)) { s += 60; break; }
        if (f.includes(v)) { s += 30; break; }
      }
    }
    return s;
  }
  function hl(text, q) {
    var esc = norm(q).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    if (!esc) return text;
    try { return text.replace(new RegExp('(' + esc + ')','gi'),'<mark>$1</mark>'); }
    catch(e) { return text; }
  }

  // ── Dropdown ──
  function runSearch(q) {
    dropdown.innerHTML = '';
    var hits = grammarIndex
      .map(function(item) { return { item: item, s: score(item, q) }; })
      .filter(function(x) { return x.s > 0; })
      .sort(function(a,b) { return b.s - a.s; })
      .slice(0, 10);

    if (!hits.length) {
      dropdown.innerHTML = '<div class="g-sd-noresult">Ничего не найдено по «' + q + '»</div>';
      dropdown.classList.add('open');
      return;
    }

    var hdr = document.createElement('div');
    hdr.className = 'g-sd-header';
    hdr.textContent = 'Найдено: ' + hits.length;
    dropdown.appendChild(hdr);

    hits.forEach(function(h) {
      var item = h.item;
      var el = document.createElement('div');
      el.className = 'g-sd-item';
      el.innerHTML =
        '<span class="g-sd-main">' + hl(item.title, q) + '</span>' +
        '<span class="g-sd-meta">' + item.level.toUpperCase().replace('TOPIK','TOPIK ') + ' · ' + (item.category||'') + '</span>';
      el.onclick = function() { closeDropdown(); openGrammarModal(item); };
      dropdown.appendChild(el);
    });
    dropdown.classList.add('open');
  }

  function closeDropdown() {
    dropdown.classList.remove('open');
    searchInput.value = '';
  }

  searchInput.addEventListener('input', function() {
    var q = searchInput.value.trim();
    q.length < 1 ? dropdown.classList.remove('open') : runSearch(q);
  });
  searchInput.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeDropdown();
  });
  document.addEventListener('click', function(e) {
    if (!e.target.closest('#g-search-wrap')) closeDropdown();
  });

  // ⌘K / Ctrl+K shortcut
  document.addEventListener('keydown', function(e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      searchInput.focus();
      searchInput.select();
    }
  });

  // ── Modal card carousel renderer (uses g-ex-* classes from trainer_base.css) ──
  var gCarN = 0;
  function renderExCards(items, label) {
    var id = 'g-car-' + (gCarN++);
    var pp = 3;
    var pages = [];
    for (var i = 0; i < items.length; i += pp) pages.push(items.slice(i, i + pp));

    var hl = GrammarHighlight.build(items, 'g-ex-hl');

    var h = '<div class="g-ex-carousel" data-gcar="' + id + '">';
    h += '<div class="g-ex-carousel-label">' + (label || 'Примеры') + '</div>';
    h += '<div class="g-ex-track-wrap"><div class="g-ex-track" id="' + id + '-t">';

    pages.forEach(function(page) {
      h += '<div class="g-ex-page">';
      page.forEach(function(ex) {
        h += '<div class="g-ex-card">' +
          '<div class="g-ex-card-head">' +
            '<span class="g-ex-card-base">' + ex.base + '</span>' +
            '<span class="g-ex-card-type">' + ex.type + '</span>' +
            '<span class="g-ex-card-arrow">→</span>' +
            '<span class="g-ex-card-applied">' + hl.hlApplied(ex) + '</span>' +
          '</div>' +
          '<div class="g-ex-card-sents">';
        ex.sentences.forEach(function(s, i) {
          h += '<div class="g-ex-card-sent">' +
            '<div class="g-ex-card-kor">' + hl.hlSentence(s) + '</div>' +
            '<div class="g-ex-card-rus">' + ex.translations[i] + '</div>' +
          '</div>';
        });
        h += '</div></div>';
      });
      h += '</div>';
    });
    h += '</div></div>';

    if (pages.length > 1) {
      h += '<div class="g-ex-nav">' +
        '<button class="g-ex-nav-btn" data-gdir="-1" data-gt="' + id + '">◂</button>' +
        '<span class="g-ex-nav-pg" id="' + id + '-pg">1 / ' + pages.length + '</span>' +
        '<button class="g-ex-nav-btn" data-gdir="1" data-gt="' + id + '">▸</button>' +
      '</div>';
    }
    h += '</div>';
    return h;
  }

  // ── Modal ──
  function renderGlobalBlocks(blocks) {
    var html = '<div style="margin-bottom:20px;padding-bottom:18px;border-bottom:1px solid var(--border-light);">';
    var rules = [];
    function flush() {
      if (!rules.length) return '';
      var h = '<table style="width:100%;border-collapse:collapse;font-size:12px;margin:6px 0 10px;">';
      h += '<tr style="background:var(--bg-app);"><th style="padding:6px 10px;text-align:left;font-size:10px;font-weight:600;color:var(--text-tertiary);border-bottom:1px solid var(--border-color);">Условие</th><th style="padding:6px 10px;text-align:left;font-size:10px;font-weight:600;color:var(--text-tertiary);border-bottom:1px solid var(--border-color);">Окончание</th><th style="padding:6px 10px;text-align:left;font-size:10px;font-weight:600;color:var(--text-tertiary);border-bottom:1px solid var(--border-color);">Пример</th></tr>';
      rules.forEach(function(r) {
        h += '<tr><td style="padding:6px 10px;border-bottom:1px solid var(--border-light);">' + r.condition + '</td><td style="padding:6px 10px;border-bottom:1px solid var(--border-light);font-weight:600;color:var(--primary);font-family:var(--font-mono);">' + r.result + '</td><td style="padding:6px 10px;border-bottom:1px solid var(--border-light);color:var(--text-secondary);font-size:11px;">' + (r.example||'') + '</td></tr>';
      });
      h += '</table>';
      rules = [];
      return h;
    }
    blocks.forEach(function(b) {
      if (b.type === 'rule') { rules.push(b); return; }
      html += flush();
      if (b.type === 'heading') html += '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-tertiary);margin:14px 0 6px;">' + b.text + '</div>';
      else if (b.type === 'text') html += '<div style="font-size:13px;color:var(--text-secondary);margin:6px 0;line-height:1.7;">' + b.text + '</div>';
      else if (b.type === 'note') html += '<div style="padding:8px 12px;background:#fff8e1;border-left:3px solid #ffc107;border-radius:0 4px 4px 0;font-size:12px;color:#6d5800;margin:8px 0;line-height:1.6;">' + b.text + '</div>';
      else if (b.type === 'warning') html += '<div style="padding:8px 12px;background:#fef2f2;border-left:3px solid #ef4444;border-radius:0 4px 4px 0;font-size:12px;color:#7f1d1d;margin:8px 0;line-height:1.6;">' + b.text + '</div>';
      else if (b.type === 'tip') html += '<div style="padding:8px 12px;background:#f0f9ff;border-left:3px solid #3b82f6;border-radius:0 4px 4px 0;font-size:12px;color:#1e3a5f;margin:8px 0;line-height:1.6;">' + b.text + '</div>';
      else if (b.type === 'examples') html += renderExCards(b.items, b.label);
    });
    html += flush();
    html += '</div>';
    return html;
  }

  function openGrammarModal(item) {
    gCarN = 0;
    modalTitle.textContent = item.title;
    modalFormula.textContent = item.formula;
    modalBadge.textContent = item.level.toUpperCase().replace('TOPIK','TOPIK ') + (item.category ? ' · ' + item.category : '');

    document.getElementById('g-modal-goto').href = window._grammarUrl + '?open=' + encodeURIComponent(item.id);

    var hasBlocks = item.details && item.details.blocks && item.details.blocks.length;
    var blocksHaveExamples = hasBlocks && item.details.blocks.some(function(b) { return b.type === 'examples'; });

    var detailsHTML = '';
    if (hasBlocks) {
      detailsHTML = renderGlobalBlocks(item.details.blocks);
    } else if (item.details && item.details.content) {
      detailsHTML = '<div class="g-modal-desc">' + item.details.content + '</div>';
    }

    var bottomExamples = '';
    if (!blocksHaveExamples && item.examples && item.examples.length) {
      bottomExamples = renderExCards(item.examples, 'Примеры');
    }

    modalBody.innerHTML = detailsHTML + bottomExamples;

    // Init global modal carousels
    var gCarState = {};
    modalBody.querySelectorAll('[data-gcar]').forEach(function(el) {
      var cid = el.dataset.gcar;
      var track = document.getElementById(cid + '-t');
      if (!track) return;
      var total = track.querySelectorAll('.g-ex-page').length;
      gCarState[cid] = { cur: 0, total: total, track: track };
    });

    function updateGCar(cid, s) {
      s.track.style.transform = 'translateX(-' + (s.cur * 100) + '%)';
      var pg = document.getElementById(cid + '-pg');
      if (pg) pg.textContent = (s.cur + 1) + ' / ' + s.total;
    }

    modalBody.addEventListener('click', function(e) {
      var btn = e.target.closest('[data-gdir]');
      if (!btn) return;
      var cid = btn.dataset.gt;
      var dir = parseInt(btn.dataset.gdir);
      var s = gCarState[cid];
      if (!s) return;
      s.cur = Math.max(0, Math.min(s.total - 1, s.cur + dir));
      updateGCar(cid, s);
    });

    // Touch swipe for global modal carousels
    modalBody.querySelectorAll('.g-ex-track-wrap').forEach(function(wrap) {
      var startX = 0, moved = false;
      var carousel = wrap.closest('[data-gcar]');
      if (!carousel) return;
      var cid = carousel.dataset.gcar;

      wrap.addEventListener('touchstart', function(e) {
        startX = e.touches[0].clientX;
        moved = false;
      }, { passive: true });

      wrap.addEventListener('touchmove', function(e) {
        var dx = Math.abs(e.touches[0].clientX - startX);
        if (dx > 10) moved = true;
      }, { passive: true });

      wrap.addEventListener('touchend', function(e) {
        if (!moved) return;
        var endX = e.changedTouches[0].clientX;
        var diff = startX - endX;
        var s = gCarState[cid];
        if (!s) return;
        if (diff > 40 && s.cur < s.total - 1) { s.cur++; updateGCar(cid, s); }
        if (diff < -40 && s.cur > 0) { s.cur--; updateGCar(cid, s); }
      }, { passive: true });
    });

    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeGrammarModal() {
    overlay.classList.remove('open');
    document.body.style.overflow = '';
  }

  modalClose.addEventListener('click', closeGrammarModal);
  overlay.addEventListener('click', function(e) { if (e.target === overlay) closeGrammarModal(); });
  document.addEventListener('keydown', function(e) { if (e.key === 'Escape' && overlay.classList.contains('open')) closeGrammarModal(); });

  window.openGrammarModal = openGrammarModal;
  window._grammarSearch = runSearch;
  window._grammarScore = score;
})();

// ── NOTES ──
var IS_TEACHER = window._isTeacher || false;
var noteFab = document.getElementById('note-fab');
var noteOverlay = document.getElementById('note-overlay');
var noteArea = document.getElementById('note-area');
var noteSaveBtn = document.getElementById('note-save-btn');

if (noteFab && noteOverlay && noteArea) {

if (!IS_TEACHER) {
  if (noteSaveBtn) noteSaveBtn.style.display = 'none';
  noteArea.readOnly = true;
  noteArea.placeholder = 'Заметки учителя (только чтение)';
}

noteArea.value = localStorage.getItem(DRAFT_KEY) || '';
noteArea.addEventListener('input', function() { localStorage.setItem(DRAFT_KEY, noteArea.value); });

noteArea.addEventListener('keydown', function(e) { e.stopPropagation(); });
noteArea.addEventListener('keyup', function(e) { e.stopPropagation(); });
noteArea.addEventListener('keypress', function(e) { e.stopPropagation(); });

window.noteActive = false;
noteFab.addEventListener('click', function() {
  noteOverlay.classList.add('active');
  window.noteActive = true;
  if (IS_TEACHER) noteArea.focus();
});
document.getElementById('note-close-btn').addEventListener('click', function() {
  noteOverlay.classList.remove('active');
  window.noteActive = false;
});

noteSaveBtn.addEventListener('click', async function() {
  var text = noteArea.value.trim();
  if (!text || !IS_TEACHER) return;
  var now = new Date();
  var fullTime = now.toLocaleString('ru-RU') + ' (Тренажер)';
  try {
    await fetch('/api/notes/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        student_id: parseInt(studentId),
        text: text,
        date: fullTime
      })
    });
    var msg = document.getElementById('note-saved-msg');
    msg.style.opacity = 1;
    setTimeout(function() { msg.style.opacity = 0; }, 1500);
  } catch(e) { console.error('Note save error', e); }
});

}

// ── REPETITION COUNTER ──
(function() {
  var counter   = document.getElementById('rep-counter');
  var curEl     = document.getElementById('rep-current');
  var goalEl    = document.getElementById('rep-goal');
  var barEl     = document.getElementById('rep-bar');
  var btnPlus   = document.getElementById('rep-plus');
  var btnReset  = document.getElementById('rep-reset');
  if (!counter) return;

  var REP_KEY = 'rep_counter_' + studentId;

  var state = { current: 0, goal: 10 };
  try {
    var saved = JSON.parse(localStorage.getItem(REP_KEY));
    if (saved && typeof saved.current === 'number') state = saved;
  } catch(e) {}

  function save() {
    localStorage.setItem(REP_KEY, JSON.stringify(state));
  }

  function render() {
    curEl.textContent = state.current;
    goalEl.textContent = state.goal;
    var pct = Math.min(100, Math.round((state.current / state.goal) * 100));
    if (barEl) barEl.style.setProperty('--pct', pct);
    var done = state.current >= state.goal;
    counter.classList.toggle('done', done);
  }

  btnPlus.addEventListener('click', function() {
    state.current++;
    save();
    render();
    curEl.classList.remove('pulse');
    void curEl.offsetWidth;
    curEl.classList.add('pulse');
    if (state.current === state.goal) {
      counter.classList.add('celebrate');
      setTimeout(function() { counter.classList.remove('celebrate'); }, 500);
    }
  });

  btnReset.addEventListener('click', function() {
    if (state.current === 0) return;
    state.current = 0;
    save();
    render();
    counter.classList.remove('done');
  });

  var picker = document.getElementById('rep-goal-picker');

  function positionPicker() {
    var goalRect = goalEl.getBoundingClientRect();
    picker.style.left = goalRect.left + 'px';
    if (goalRect.top > window.innerHeight / 2) {
      picker.style.bottom = (window.innerHeight - goalRect.top + 8) + 'px';
      picker.style.top = '';
    } else {
      picker.style.top = (goalRect.bottom + 8) + 'px';
      picker.style.bottom = '';
    }
  }

  function openPicker() {
    picker.querySelectorAll('.rep-goal-opt').forEach(function(o) {
      o.classList.toggle('active', parseInt(o.dataset.val) === state.goal);
    });
    positionPicker();
    picker.classList.add('open');
  }

  function closePicker() {
    picker.classList.remove('open');
  }

  goalEl.addEventListener('click', function(e) {
    e.stopPropagation();
    picker.classList.contains('open') ? closePicker() : openPicker();
  });

  picker.addEventListener('click', function(e) {
    var opt = e.target.closest('.rep-goal-opt');
    if (!opt) return;
    state.goal = parseInt(opt.dataset.val);
    save();
    render();
    closePicker();
  });

  document.addEventListener('click', function(e) {
    if (!e.target.closest('.rep-goal-picker, .rep-goal')) closePicker();
  });

  // ── DRAG ──
  var POS_KEY = 'rep_pos_' + studentId;
  var dragging = false, dragMoved = false, startX, startY, origLeft, origTop;

  function initPosition() {
    try {
      var pos = JSON.parse(localStorage.getItem(POS_KEY));
      if (pos && typeof pos.left === 'number') {
        counter.style.left = Math.min(pos.left, window.innerWidth - 60) + 'px';
        counter.style.top = Math.min(pos.top, window.innerHeight - 60) + 'px';
        return;
      }
    } catch(e) {}
    counter.style.left = '24px';
    counter.style.top = (window.innerHeight - counter.offsetHeight - 24) + 'px';
  }

  function savePosition() {
    localStorage.setItem(POS_KEY, JSON.stringify({
      left: parseInt(counter.style.left),
      top: parseInt(counter.style.top)
    }));
  }

  function clamp() {
    var l = parseInt(counter.style.left);
    var t = parseInt(counter.style.top);
    var w = counter.offsetWidth, h = counter.offsetHeight;
    l = Math.max(0, Math.min(l, window.innerWidth - w));
    t = Math.max(0, Math.min(t, window.innerHeight - h));
    counter.style.left = l + 'px';
    counter.style.top = t + 'px';
  }

  function onDragStart(x, y) {
    dragging = true;
    dragMoved = false;
    startX = x;
    startY = y;
    origLeft = parseInt(counter.style.left) || 0;
    origTop = parseInt(counter.style.top) || 0;
    counter.classList.add('dragging');
  }

  function onDragMove(x, y) {
    if (!dragging) return;
    var dx = x - startX, dy = y - startY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragMoved = true;
    counter.style.left = (origLeft + dx) + 'px';
    counter.style.top = (origTop + dy) + 'px';
  }

  function onDragEnd() {
    if (!dragging) return;
    dragging = false;
    counter.classList.remove('dragging');
    clamp();
    if (dragMoved) savePosition();
  }

  counter.addEventListener('mousedown', function(e) {
    if (e.target.closest('.rep-btn, .rep-react, .rep-goal, .rep-goal-picker')) return;
    e.preventDefault();
    onDragStart(e.clientX, e.clientY);
  });
  document.addEventListener('mousemove', function(e) { onDragMove(e.clientX, e.clientY); });
  document.addEventListener('mouseup', onDragEnd);

  counter.addEventListener('touchstart', function(e) {
    if (e.target.closest('.rep-btn, .rep-react, .rep-goal, .rep-goal-picker')) return;
    var t = e.touches[0];
    onDragStart(t.clientX, t.clientY);
  }, { passive: true });
  document.addEventListener('touchmove', function(e) {
    if (!dragging) return;
    var t = e.touches[0];
    onDragMove(t.clientX, t.clientY);
  }, { passive: true });
  document.addEventListener('touchend', onDragEnd);

  window.addEventListener('resize', function() { clamp(); savePosition(); });

  // ── REACTION FOUNTAIN ──
  var fountain = document.getElementById('rep-fountain');

  function spawnFountain(emoji, originEl) {
    var rect = originEl.getBoundingClientRect();
    var cx = rect.left + rect.width / 2;
    var cy = rect.top;
    var count = 10 + Math.floor(Math.random() * 6);

    for (var i = 0; i < count; i++) {
      var p = document.createElement('div');
      p.className = 'rep-particle';
      p.textContent = emoji;
      p.style.fontSize = (18 + Math.random() * 16) + 'px';
      p.style.left = cx + 'px';
      p.style.top = cy + 'px';
      fountain.appendChild(p);

      var vx = (Math.random() - 0.5) * 3.5;
      var vy = -(6 + Math.random() * 5);
      var gravity = 0.18;
      var rot = (Math.random() - 0.5) * 4;
      var x = 0, y = 0, r = 0, opacity = 1;
      var frame = 0;
      var maxFrames = 50 + Math.floor(Math.random() * 20);
      var delay = Math.floor(Math.random() * 6);

      (function(p, vx, vy, gravity, rot, maxFrames, delay) {
        var x = 0, y = 0, r = 0, opacity = 1, frame = 0, started = false;
        function tick() {
          frame++;
          if (frame <= delay) { requestAnimationFrame(tick); return; }
          if (!started) { started = true; p.style.opacity = '1'; }
          vy += gravity;
          x += vx; y += vy; r += rot;
          opacity = Math.max(0, 1 - (frame - delay) / maxFrames);
          p.style.transform = 'translate(' + x + 'px, ' + y + 'px) rotate(' + r + 'deg) scale(' + (0.6 + opacity * 0.4) + ')';
          p.style.opacity = opacity;
          if (frame - delay < maxFrames && opacity > 0) {
            requestAnimationFrame(tick);
          } else {
            p.remove();
          }
        }
        p.style.opacity = '0';
        requestAnimationFrame(tick);
      })(p, vx, vy, gravity, rot, maxFrames, delay);
    }
  }

  counter.querySelectorAll('.rep-react').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      spawnFountain(btn.dataset.emoji, btn);
    });
  });

  initPosition();
  render();
})();

// ── SELECTION CONTEXT MENU ──
(function() {
  var popup     = document.getElementById('sel-popup');
  var btnSearch = document.getElementById('sel-search');
  var btnHub    = document.getElementById('sel-hub');
  var btnNote   = document.getElementById('sel-note');
  if (!popup) return;

  var selectedText = '';

  function getSelectedText() {
    var sel = window.getSelection();
    return sel ? sel.toString().trim() : '';
  }

  function showPopup() {
    var sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    var range = sel.getRangeAt(0);
    var selRect = range.getBoundingClientRect();
    if (!selRect.width) return;

    popup.classList.add('open');
    popup.style.left = '0'; popup.style.top = '0';
    var pw = popup.offsetWidth, ph = popup.offsetHeight;

    var left = selRect.left + selRect.width / 2 - pw / 2 + window.scrollX;
    var top = selRect.bottom + 8 + window.scrollY;

    if (selRect.bottom + 8 + ph > window.innerHeight) {
      top = selRect.top - ph - 8 + window.scrollY;
    }
    left = Math.max(8, Math.min(left, window.innerWidth - pw - 8 + window.scrollX));

    popup.style.left = left + 'px';
    popup.style.top  = top + 'px';
  }

  function hidePopup() {
    popup.classList.remove('open');
    selectedText = '';
  }

  document.addEventListener('mouseup', function(e) {
    if (e.target.closest('.sel-popup, .g-modal, .note-modal, .g-search-wrap, textarea, input')) return;
    setTimeout(function() {
      var txt = getSelectedText();
      if (txt.length >= 1) {
        selectedText = txt;
        showPopup();
      } else {
        hidePopup();
      }
    }, 10);
  });

  var touchTimer = null;
  document.addEventListener('selectionchange', function() {
    if (!('ontouchstart' in window)) return;
    clearTimeout(touchTimer);
    touchTimer = setTimeout(function() {
      var txt = getSelectedText();
      if (txt.length >= 1) {
        selectedText = txt;
        showPopup();
      }
    }, 300);
  });

  document.addEventListener('mousedown', function(e) {
    if (!e.target.closest('.sel-popup')) hidePopup();
  });

  // ── Search button ──
  btnSearch.addEventListener('click', function(e) {
    e.preventDefault(); e.stopPropagation();
    var q = selectedText;
    if (!q) return;

    var gi = window._grammarIndex || [];
    var scoreF = window._grammarScore;
    if (gi.length && scoreF) {
      var hits = gi
        .map(function(item) { return { item: item, s: scoreF(item, q) }; })
        .filter(function(x) { return x.s > 0; })
        .sort(function(a, b) { return b.s - a.s; });

      if (hits.length === 1) {
        hidePopup();
        window.getSelection().removeAllRanges();
        window.openGrammarModal(hits[0].item);
        return;
      }
      if (hits.length > 1) {
        var si = document.getElementById('g-search-input');
        if (si && window._grammarSearch) {
          hidePopup();
          window.getSelection().removeAllRanges();
          si.value = q;
          si.focus();
          window._grammarSearch(q);
          return;
        }
      }
    }

    var si2 = document.getElementById('g-search-input');
    if (si2) {
      hidePopup();
      window.getSelection().removeAllRanges();
      si2.value = q;
      si2.focus();
      if (window._grammarSearch) window._grammarSearch(q);
    }
  });

  // ── Note button ──
  btnNote.addEventListener('click', function(e) {
    e.preventDefault(); e.stopPropagation();
    var txt = selectedText;
    if (!txt) return;

    var na = document.getElementById('note-area');
    if (!na) return;

    var cur = na.value;
    var sep = cur.trim() ? '\n' : '';
    na.value = cur + sep + txt;
    na.dispatchEvent(new Event('input'));

    btnSearch.style.display = 'none';
    btnHub.style.display = 'none';
    btnNote.style.display = 'none';
    var toast = popup.querySelector('.sel-toast');
    if (!toast) {
      toast = document.createElement('span');
      toast.className = 'sel-toast';
      popup.appendChild(toast);
    }
    toast.textContent = '✓ Добавлено в заметки';
    toast.style.display = '';
    window.getSelection().removeAllRanges();
    setTimeout(function() {
      toast.style.display = 'none';
      btnSearch.style.display = '';
      btnHub.style.display = '';
      btnNote.style.display = '';
      hidePopup();
    }, 900);
  });

  // ── Hub button ──
  var HUB_QUEUE_KEY = 'hub_queue_' + studentId;

  function getHubQueue() {
    try { return JSON.parse(localStorage.getItem(HUB_QUEUE_KEY)) || []; }
    catch(e) { return []; }
  }
  function saveHubQueue(q) { localStorage.setItem(HUB_QUEUE_KEY, JSON.stringify(q)); }

  function processHubQueue() {
    var queue = getHubQueue();
    if (!queue.length) return;
    var item = queue[0];

    fetch('/api/hub/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ student_id: parseInt(studentId), word: item })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.ok || (data.error && data.error !== 'ai_failed')) {
        var q = getHubQueue();
        q.shift();
        saveHubQueue(q);
        if (q.length) setTimeout(processHubQueue, 500);
      }
    })
    .catch(function() {
      setTimeout(processHubQueue, 10000);
    });
  }

  function addToHub(word) {
    var queue = getHubQueue();
    if (queue.includes(word)) return;
    queue.push(word);
    saveHubQueue(queue);
    processHubQueue();
  }

  setTimeout(processHubQueue, 2000);

  btnHub.addEventListener('click', function(e) {
    e.preventDefault(); e.stopPropagation();
    var txt = selectedText;
    if (!txt) return;

    btnSearch.style.display = 'none';
    btnHub.style.display = 'none';
    btnNote.style.display = 'none';
    var toast = popup.querySelector('.sel-toast');
    if (!toast) {
      toast = document.createElement('span');
      toast.className = 'sel-toast';
      popup.appendChild(toast);
    }
    toast.textContent = '✓ Добавлено в словарь';
    toast.style.display = '';
    window.getSelection().removeAllRanges();

    addToHub(txt);

    setTimeout(function() {
      toast.style.display = 'none';
      btnSearch.style.display = '';
      btnHub.style.display = '';
      btnNote.style.display = '';
      hidePopup();
    }, 900);
  });
})();

// ── VOCAB ADD MODAL ──
(function() {
  var vocabFab     = document.getElementById('vocab-fab');
  var vocabOverlay = document.getElementById('vocab-overlay');
  var vocabClose   = document.getElementById('vocab-close-btn');
  var vocabInput   = document.getElementById('vocab-input');
  var vocabAddBtn  = document.getElementById('vocab-add-btn');
  var vocabStatus  = document.getElementById('vocab-status');
  var vocabResults = document.getElementById('vocab-results');
  if (!vocabFab || !vocabOverlay) return;

  function openVocab() {
    vocabOverlay.classList.add('open');
    vocabInput.value = '';
    vocabStatus.textContent = '';
    vocabResults.innerHTML = '';
    setTimeout(function() { vocabInput.focus(); }, 100);
  }

  function closeVocab() {
    vocabOverlay.classList.remove('open');
  }

  vocabFab.addEventListener('click', openVocab);
  vocabClose.addEventListener('click', closeVocab);
  vocabOverlay.addEventListener('click', function(e) {
    if (e.target === vocabOverlay) closeVocab();
  });

  vocabAddBtn.addEventListener('click', function() {
    var text = vocabInput.value.trim();
    if (!text) return;

    vocabAddBtn.disabled = true;
    vocabAddBtn.textContent = 'Добавляю...';
    vocabStatus.textContent = '';
    vocabResults.innerHTML = '';

    fetch('/api/hub/add-batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        student_id: parseInt(window._studentId),
        text: text
      })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      vocabAddBtn.disabled = false;
      vocabAddBtn.textContent = 'Добавить';

      if (!data.ok) {
        vocabStatus.textContent = '❌ Ошибка: ' + (data.error || 'unknown');
        vocabStatus.className = 'vocab-status error';
        return;
      }

      var s = data.summary;
      vocabStatus.textContent = '✅ Добавлено: ' + s.added + '  •  Дубликаты: ' + s.duplicates + (s.failed ? '  •  Не удалось: ' + s.failed : '');
      vocabStatus.className = 'vocab-status success';

      // Render results
      var html = '';
      if (data.added && data.added.length) {
        html += '<div class="vocab-res-section"><div class="vocab-res-label">✅ Добавлено</div>';
        data.added.forEach(function(w) {
          html += '<div class="vocab-res-row added"><span class="vocab-res-kor">' + w.word_kor + '</span><span class="vocab-res-rus">' + w.word_rus + '</span><span class="vocab-res-pos">' + (w.pos || '') + '</span></div>';
        });
        html += '</div>';
      }
      if (data.duplicates && data.duplicates.length) {
        html += '<div class="vocab-res-section"><div class="vocab-res-label">⏭ Уже есть</div>';
        data.duplicates.forEach(function(w) {
          html += '<div class="vocab-res-row dup"><span class="vocab-res-kor">' + w.word_kor + '</span><span class="vocab-res-rus">' + w.word_rus + '</span></div>';
        });
        html += '</div>';
      }
      vocabResults.innerHTML = html;
      vocabInput.value = '';
    })
    .catch(function(err) {
      vocabAddBtn.disabled = false;
      vocabAddBtn.textContent = 'Добавить';
      vocabStatus.textContent = '❌ Ошибка сети';
      vocabStatus.className = 'vocab-status error';
    });
  });

  // Enter = add (Shift+Enter = new line)
  vocabInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      vocabAddBtn.click();
    }
  });
})();

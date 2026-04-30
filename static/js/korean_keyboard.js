/* Korean Virtual Keyboard (한글) — 두벌식 layout with full Hangul composer.
   Public API: window.KKB.{open,close,toggle,feed,backspace,flush}
   Привязывается к любому сфокусированному <input>/<textarea> через делегирование. */
(function () {
  'use strict';

  // ── Hangul tables ────────────────────────────────────────────────────────
  const CHO  = ['ㄱ','ㄲ','ㄴ','ㄷ','ㄸ','ㄹ','ㅁ','ㅂ','ㅃ','ㅅ','ㅆ','ㅇ','ㅈ','ㅉ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ'];
  const JUNG = ['ㅏ','ㅐ','ㅑ','ㅒ','ㅓ','ㅔ','ㅕ','ㅖ','ㅗ','ㅘ','ㅙ','ㅚ','ㅛ','ㅜ','ㅝ','ㅞ','ㅟ','ㅠ','ㅡ','ㅢ','ㅣ'];
  const JONG = ['','ㄱ','ㄲ','ㄳ','ㄴ','ㄵ','ㄶ','ㄷ','ㄹ','ㄺ','ㄻ','ㄼ','ㄽ','ㄾ','ㄿ','ㅀ','ㅁ','ㅂ','ㅄ','ㅅ','ㅆ','ㅇ','ㅈ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ'];

  const choIdx  = Object.fromEntries(CHO.map((j, i) => [j, i]));
  const jungIdx = Object.fromEntries(JUNG.map((j, i) => [j, i]));
  const jongIdx = {};
  JONG.forEach((j, i) => { if (j) jongIdx[j] = i; });

  const VOWEL_COMBINE = {
    'ㅗㅏ':'ㅘ','ㅗㅐ':'ㅙ','ㅗㅣ':'ㅚ',
    'ㅜㅓ':'ㅝ','ㅜㅔ':'ㅞ','ㅜㅣ':'ㅟ',
    'ㅡㅣ':'ㅢ'
  };
  const JONG_COMBINE = {
    'ㄱㅅ':'ㄳ',
    'ㄴㅈ':'ㄵ','ㄴㅎ':'ㄶ',
    'ㄹㄱ':'ㄺ','ㄹㅁ':'ㄻ','ㄹㅂ':'ㄼ','ㄹㅅ':'ㄽ','ㄹㅌ':'ㄾ','ㄹㅍ':'ㄿ','ㄹㅎ':'ㅀ',
    'ㅂㅅ':'ㅄ'
  };
  const JONG_SPLIT = {};
  Object.entries(JONG_COMBINE).forEach(([k, v]) => { JONG_SPLIT[v] = [k[0], k[1]]; });

  const isVowel = (j) => jungIdx[j] !== undefined;

  // ── Composer state ───────────────────────────────────────────────────────
  const S = { cho: null, jung: null, jong: null, target: null, pendingLen: 0 };
  let _internal = 0; // suppress recursive input-event handling

  function reset() { S.cho = S.jung = S.jong = null; S.pendingLen = 0; }

  function setTarget(el) {
    if (S.target !== el) { reset(); S.target = el; }
  }

  function render() {
    if (S.cho == null && S.jung == null) return '';
    if (S.cho != null && S.jung == null) return CHO[S.cho];
    if (S.cho == null && S.jung != null) return JUNG[S.jung];
    return String.fromCharCode(0xAC00 + S.cho * 588 + S.jung * 28 + (S.jong ?? 0));
  }

  function write(s, replacePending) {
    const t = S.target;
    if (!t) return;
    const cursor = t.selectionStart;
    const start = replacePending ? cursor - S.pendingLen : cursor;
    _internal++;
    try {
      t.setRangeText(s, start, cursor, 'end');
    } catch (e) {
      // setRangeText not supported on this input type — fallback
      const before = t.value.slice(0, start);
      const after = t.value.slice(cursor);
      t.value = before + s + after;
      const pos = before.length + s.length;
      try { t.setSelectionRange(pos, pos); } catch (_) {}
    }
    // Manually dispatch in case the browser doesn't auto-fire (some textareas)
    t.dispatchEvent(new Event('input', { bubbles: true }));
    Promise.resolve().then(() => { _internal--; });
  }

  function apply(s) {
    write(s, true);
    S.pendingLen = s.length;
  }

  function insertRaw(s) {
    reset();
    write(s, false);
  }

  function feed(jamo) {
    const t = S.target;
    if (!t) return;

    if (isVowel(jamo)) {
      const v = jungIdx[jamo];

      if (S.cho == null && S.jung == null) {
        // Standalone vowel — write as plain jamo, no pending state.
        reset();
        write(jamo, false);
        return;
      }
      if (S.cho != null && S.jung == null) {
        S.jung = v;
        apply(render());
        return;
      }
      if (S.cho != null && S.jung != null && S.jong == null) {
        const combined = VOWEL_COMBINE[JUNG[S.jung] + jamo];
        if (combined !== undefined) {
          S.jung = jungIdx[combined];
          apply(render());
        } else {
          reset();
          write(jamo, false);
        }
        return;
      }
      if (S.cho != null && S.jung != null && S.jong != null) {
        // Recombination: jong becomes cho of new syllable
        const jongJamo = JONG[S.jong];
        const split = JONG_SPLIT[jongJamo];
        let extracted, leftover;
        if (split) { leftover = jongIdx[split[0]]; extracted = split[1]; }
        else       { leftover = 0;                  extracted = jongJamo; }
        const newCho = choIdx[extracted];
        if (newCho === undefined) { reset(); return; }
        const prevSyl = String.fromCharCode(0xAC00 + S.cho * 588 + S.jung * 28 + leftover);
        const newSyl  = String.fromCharCode(0xAC00 + newCho * 588 + v * 28);
        apply(prevSyl + newSyl);
        S.cho = newCho; S.jung = v; S.jong = null; S.pendingLen = 1;
        return;
      }
    } else {
      const c = choIdx[jamo];
      const j = jongIdx[jamo];

      if (S.cho == null && S.jung == null) {
        S.cho = c; apply(render()); return;
      }
      if (S.cho != null && S.jung == null) {
        // Bare cho + new consonant → settle old, start new.
        reset(); S.cho = c; apply(render()); return;
      }
      if (S.cho != null && S.jung != null && S.jong == null) {
        if (j !== undefined) { S.jong = j; apply(render()); }
        else                 { reset(); S.cho = c; apply(render()); }
        return;
      }
      if (S.cho != null && S.jung != null && S.jong != null) {
        const combined = JONG_COMBINE[JONG[S.jong] + jamo];
        if (combined !== undefined && jongIdx[combined] !== undefined) {
          S.jong = jongIdx[combined]; apply(render());
        } else {
          reset(); S.cho = c; apply(render());
        }
        return;
      }
    }
  }

  function backspace() {
    const t = S.target;
    if (!t) return;

    if (S.pendingLen > 0) {
      if (S.jong != null) {
        const split = JONG_SPLIT[JONG[S.jong]];
        S.jong = split ? jongIdx[split[0]] : null;
        apply(render());
      } else if (S.jung != null) {
        S.jung = null;
        if (S.cho != null) apply(render());
        else { apply(''); S.pendingLen = 0; }
      } else if (S.cho != null) {
        S.cho = null;
        apply(''); S.pendingLen = 0;
      }
    } else {
      const cur = t.selectionStart;
      const end = t.selectionEnd;
      _internal++;
      try {
        if (cur !== end) t.setRangeText('', cur, end, 'end');
        else if (cur > 0) t.setRangeText('', cur - 1, cur, 'end');
      } catch (_) {}
      t.dispatchEvent(new Event('input', { bubbles: true }));
      Promise.resolve().then(() => { _internal--; });
    }
  }

  // ── UI ───────────────────────────────────────────────────────────────────
  const ROW1       = ['ㅂ','ㅈ','ㄷ','ㄱ','ㅅ','ㅛ','ㅕ','ㅑ','ㅐ','ㅔ'];
  const ROW1_SHIFT = ['ㅃ','ㅉ','ㄸ','ㄲ','ㅆ','ㅛ','ㅕ','ㅑ','ㅒ','ㅖ'];
  const ROW2 = ['ㅁ','ㄴ','ㅇ','ㄹ','ㅎ','ㅗ','ㅓ','ㅏ','ㅣ'];
  const ROW3 = ['ㅋ','ㅌ','ㅊ','ㅍ','ㅠ','ㅜ','ㅡ'];

  let panel = null;
  let shiftActive = false;
  let shiftLocked = false;
  let lastShiftClick = 0;

  function makeKey(jamo, shiftJamo) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'kkb-key kkb-key-jamo';
    b.textContent = jamo;
    b.dataset.jamo = jamo;
    if (shiftJamo && shiftJamo !== jamo) b.dataset.shift = shiftJamo;
    return b;
  }

  function makeCtrl(role, label, extraClass) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'kkb-key kkb-key-ctrl ' + (extraClass || '');
    b.textContent = label;
    b.dataset.role = role;
    return b;
  }

  function buildPanel() {
    panel = document.createElement('div');
    panel.id = 'kkb-panel';
    panel.className = 'kkb-panel';
    panel.setAttribute('role', 'group');
    panel.setAttribute('aria-label', 'Корейская клавиатура');

    const r1 = document.createElement('div'); r1.className = 'kkb-row';
    ROW1.forEach((j, i) => r1.appendChild(makeKey(j, ROW1_SHIFT[i])));
    panel.appendChild(r1);

    const r2 = document.createElement('div'); r2.className = 'kkb-row kkb-row-9';
    ROW2.forEach(j => r2.appendChild(makeKey(j)));
    panel.appendChild(r2);

    const r3 = document.createElement('div'); r3.className = 'kkb-row kkb-row-7';
    ROW3.forEach(j => r3.appendChild(makeKey(j)));
    panel.appendChild(r3);

    const rb = document.createElement('div'); rb.className = 'kkb-row kkb-row-bottom';
    rb.appendChild(makeCtrl('shift', 'Shift', 'kkb-key-shift'));
    rb.appendChild(makeCtrl('space', 'Пробел', 'kkb-key-space'));
    rb.appendChild(makeCtrl('enter', '↵', 'kkb-key-enter'));
    rb.appendChild(makeCtrl('bs', '⌫', 'kkb-key-bs'));
    rb.appendChild(makeCtrl('close', '✕', 'kkb-key-close'));
    panel.appendChild(rb);

    document.body.appendChild(panel);

    // Prevent focus loss when tapping keys
    const stopFocusLoss = (e) => {
      if (e.target.closest('.kkb-key')) e.preventDefault();
    };
    panel.addEventListener('mousedown', stopFocusLoss);
    panel.addEventListener('touchstart', stopFocusLoss, { passive: false });

    panel.addEventListener('click', (e) => {
      const btn = e.target.closest('.kkb-key');
      if (!btn) return;
      e.preventDefault();
      handleKey(btn);
    });
  }

  function handleKey(btn) {
    const role = btn.dataset.role;
    if (role === 'shift') {
      const now = Date.now();
      if ((now - lastShiftClick) < 400) {
        shiftLocked = !shiftLocked;
        shiftActive = shiftLocked;
      } else {
        shiftActive = !shiftActive;
        if (!shiftActive) shiftLocked = false;
      }
      lastShiftClick = now;
      updateShiftUi();
      return;
    }
    if (role === 'space') { insertRaw(' '); afterTap(); return; }
    if (role === 'enter') {
      const t = S.target;
      if (t && t.tagName === 'TEXTAREA') insertRaw('\n');
      else reset();
      afterTap();
      return;
    }
    if (role === 'bs')    { backspace(); afterTap(); return; }
    if (role === 'close') { close(); return; }

    let jamo = btn.dataset.jamo;
    if (shiftActive && btn.dataset.shift) jamo = btn.dataset.shift;
    feed(jamo);
    afterTap();
  }

  function afterTap() {
    if (shiftActive && !shiftLocked) {
      shiftActive = false;
      updateShiftUi();
    }
  }

  function updateShiftUi() {
    if (!panel) return;
    panel.classList.toggle('shift-on', shiftActive);
    panel.classList.toggle('shift-locked', shiftLocked);
    panel.querySelectorAll('.kkb-key-jamo').forEach(b => {
      b.textContent = (shiftActive && b.dataset.shift) ? b.dataset.shift : b.dataset.jamo;
    });
  }

  function open() {
    if (!panel) buildPanel();
    panel.classList.add('open');
    document.body.classList.add('kkb-open');
    const fab = document.getElementById('kkb-fab');
    if (fab) fab.classList.add('active');
  }

  function close() {
    reset();
    if (panel) panel.classList.remove('open');
    document.body.classList.remove('kkb-open');
    const fab = document.getElementById('kkb-fab');
    if (fab) fab.classList.remove('active');
  }

  function toggle() {
    if (panel && panel.classList.contains('open')) close();
    else open();
  }

  // ── Active target tracking ───────────────────────────────────────────────
  function isTextField(el) {
    if (!el) return false;
    if (el.disabled || el.readOnly) return false;
    if (el.tagName === 'TEXTAREA') return true;
    if (el.tagName === 'INPUT') {
      const t = (el.type || 'text').toLowerCase();
      return ['text','search','url','email','tel',''].includes(t);
    }
    return false;
  }

  document.addEventListener('focusin', (e) => {
    if (isTextField(e.target)) setTarget(e.target);
  });

  document.addEventListener('focusout', (e) => {
    if (e.target === S.target) reset();
  });

  // External (physical) input → flush composer state
  document.addEventListener('input', (e) => {
    if (_internal > 0) return;
    if (e.target !== S.target) return;
    reset();
  }, true);

  // Selection moved (click in middle, arrow keys) → flush
  document.addEventListener('selectionchange', () => {
    const t = S.target;
    if (!t || S.pendingLen === 0) return;
    // Pending tail must end at the caret. If selection moved away — flush.
    if (t.selectionStart !== t.selectionEnd) reset();
  });

  // ── Init ─────────────────────────────────────────────────────────────────
  function init() {
    const fab = document.getElementById('kkb-fab');
    if (fab) {
      fab.addEventListener('click', (e) => { e.preventDefault(); toggle(); });
      // Don't steal focus from active input
      fab.addEventListener('mousedown', (e) => e.preventDefault());
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.KKB = { open, close, toggle, feed, backspace, flush: reset };
})();

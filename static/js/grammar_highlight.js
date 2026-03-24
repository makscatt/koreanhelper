/**
 * grammar_highlight.js
 * Highlights grammar suffixes in Korean example sentences.
 * Used by both trainer_grammar.html and trainer_base.js renderers.
 */
(function() {

  function escRe(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function commonTail(strings) {
    if (!strings.length) return '';
    var rev = strings.map(function(s) { return s.split('').reverse().join(''); });
    var tail = '';
    var minLen = Math.min.apply(null, rev.map(function(s) { return s.length; }));
    for (var i = 0; i < minLen; i++) {
      var ch = rev[0][i];
      var same = true;
      for (var j = 1; j < rev.length; j++) {
        if (rev[j][i] !== ch) { same = false; break; }
      }
      if (same) tail = ch + tail;
      else break;
    }
    return tail;
  }

  /**
   * Build highlight function for a set of example items.
   * @param {Array} items - array of {base, applied, ...}
   * @param {string} hlClass - CSS class for <b> tag (e.g. 'gr-ex-hl' or 'g-ex-hl')
   * @returns {Object} { hlSentence(txt), hlApplied(ex) }
   */
  function buildHighlighter(items, hlClass) {
    // 1. Collect suffixes from all items
    var allSuffixes = [];
    items.forEach(function(ex) {
      var stem = ex.base.replace(/다$/, '');
      var prefix = '';
      for (var ci = 0; ci < Math.min(stem.length, ex.applied.length); ci++) {
        if (stem[ci] === ex.applied[ci]) prefix += stem[ci];
        else break;
      }
      var suffix = ex.applied.slice(prefix.length);
      if (suffix && allSuffixes.indexOf(suffix) === -1) allSuffixes.push(suffix);
    });

    if (!allSuffixes.length) {
      return {
        hlSentence: function(txt) { return txt; },
        hlApplied: function(ex) { return ex.applied; }
      };
    }

    // 2. Compute common tail
    var ct = commonTail(allSuffixes);

    // 3. Build regex based on common tail type
    var hlRe = null;
    var hlGrouped = false; // true = use $1<hl>$2</hl>, false = use $1<hl>$2</hl> differently

    if (ct.indexOf(' ') >= 0 && ct.length >= 2) {
      // Multi-word core (e.g. "것 같아요")
      // Match: (Korean chars before last)(last Korean char + space + core)
      var ctEsc = escRe(ct);
      hlRe = new RegExp('([가-힣]*?)([가-힣]\\s+' + ctEsc + ')(?=[^가-힣]|$)', 'g');
      hlGrouped = true;
    } else if (ct.length >= 2) {
      // Single-word tail, >= 2 chars (e.g. "까요?")
      // Match: word ending with tail, highlight only tail
      var ctEsc = escRe(ct);
      hlRe = new RegExp('([가-힣]*?)(' + ctEsc + ')(?=[^가-힣]|$)', 'g');
      hlGrouped = true;
    } else if (ct.length === 1) {
      // Single char tail (e.g. "데")
      // Highlight tail + 1 preceding Korean char
      var ctEsc = escRe(ct);
      hlRe = new RegExp('([가-힣]*?)([가-힣]' + ctEsc + ')(?=[^가-힣]|$)', 'g');
      hlGrouped = true;
    } else {
      // No common tail (e.g. "이" vs "가")
      // Match each suffix individually as word ending
      allSuffixes.sort(function(a, b) { return b.length - a.length; });
      var patterns = allSuffixes.map(function(s) { return escRe(s); });
      hlRe = new RegExp('([가-힣]+?)(' + patterns.join('|') + ')(?=[^가-힣]|$)', 'g');
      hlGrouped = true;
    }

    function hlSentence(txt) {
      if (!hlRe) return txt;
      hlRe.lastIndex = 0;
      if (hlGrouped) {
        return txt.replace(hlRe, '$1<b class="' + hlClass + '">$2</b>');
      }
      return txt;
    }

    function hlApplied(ex) {
      var stem = ex.base.replace(/다$/, '');
      var prefix = '';
      for (var ci = 0; ci < Math.min(stem.length, ex.applied.length); ci++) {
        if (stem[ci] === ex.applied[ci]) prefix += stem[ci];
        else break;
      }
      var suffix = ex.applied.slice(prefix.length);
      return suffix ? (prefix + '<b class="' + hlClass + '">' + suffix + '</b>') : ex.applied;
    }

    return { hlSentence: hlSentence, hlApplied: hlApplied };
  }

  // Export globally
  window.GrammarHighlight = { build: buildHighlighter };

})();

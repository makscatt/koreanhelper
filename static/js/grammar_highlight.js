/**
 * grammar_highlight.js
 * Placeholder — no highlighting. Will be implemented later.
 */
(function() {
  function buildHighlighter(items, hlClass) {
    return {
      hlSentence: function(txt) { return txt; },
      hlApplied: function(ex) { return ex.applied; }
    };
  }
  window.GrammarHighlight = { build: buildHighlighter };
})();

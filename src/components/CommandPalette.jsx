import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { listSessions } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import { sessionTypeLabel } from "../utils/format";

// Small hand-rolled fuzzy scorer (substring match scores higher than an
// in-order subsequence match) rather than a library -- the result set is a
// season's worth of sessions at most, not thousands of rows, and this
// keeps the same "hand-roll it" precedent as RadialGauge/AnimatedNumber
// instead of adding a dependency for something this contained.
function fuzzyScore(query, target) {
  const q = query.trim().toLowerCase();
  if (!q) return 1;
  const t = target.toLowerCase();
  if (t.includes(q)) return 100 - t.indexOf(q);

  let qi = 0;
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) qi++;
  }
  return qi === q.length ? 10 : 0;
}

function CommandPalette({ onSelectSession, onClose }) {
  const { data: sessions } = useAsync(() => listSessions(), []);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const results = useMemo(() => {
    if (!sessions) return [];
    return sessions
      .map((s) => ({
        session: s,
        score: fuzzyScore(query, `${s.event_name} ${sessionTypeLabel(s.session_type)} ${s.season}`),
      }))
      .filter((r) => r.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 8)
      .map((r) => r.session);
  }, [sessions, query]);

  function handleQueryChange(event) {
    setQuery(event.target.value);
    setActiveIndex(0);
  }

  function handleKeyDown(event) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter" && results[activeIndex]) {
      onSelectSession(results[activeIndex].id);
    }
  }

  return createPortal(
    <div className="palette-overlay" onClick={onClose}>
      <div className="palette-panel" onClick={(event) => event.stopPropagation()}>
        <input
          autoFocus
          className="palette-input"
          value={query}
          onChange={handleQueryChange}
          onKeyDown={handleKeyDown}
          placeholder="Jump to a session…"
        />
        <ul className="palette-results">
          {results.map((s, index) => (
            <li
              key={s.id}
              className={index === activeIndex ? "palette-result active" : "palette-result"}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => onSelectSession(s.id)}
            >
              <strong>{s.event_name}</strong>
              <span>{sessionTypeLabel(s.session_type)}</span>
            </li>
          ))}
          {sessions && results.length === 0 && <li className="palette-empty">No matching sessions</li>}
        </ul>
      </div>
    </div>,
    document.body
  );
}

export default CommandPalette;

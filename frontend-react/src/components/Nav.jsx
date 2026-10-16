import { useEffect, useRef, useState } from "react";

import { DATA_RELATIONSHIP_VALIDATION, DATA_RELATIONSHIP_TAB_ID } from "../featureNames.js";

const TABS = [
  { id: "dashboard", label: "Dashboard", icon: "\u25A6" },
  { id: "profiling", label: "Profiling", icon: "\u{1F50E}" },
  { id: "human-review", label: "Human Review", icon: "\u{1F91D}" },
  { id: "synthetic-data", label: "Synthetic Data Generation", icon: "\u2699" },
  { id: DATA_RELATIONSHIP_TAB_ID, label: DATA_RELATIONSHIP_VALIDATION, icon: "\u{1F517}" },
  { id: "masking", label: "Masking", icon: "\u{1F512}" },
  { id: "knowledge-base", label: "Knowledge Base", icon: "\u{1F4D6}" },
  { id: "query-agent", label: "Query Agent", icon: "\u{1F4AC}" },
  { id: "logs", label: "Logs", icon: "\u{1F4DC}" },
];
// Only admins see this tab (the API enforces it too).
const USERS_TAB = { id: "users", label: "Users", icon: "\u{1F465}" };

const EDGE = 4; // px tolerance before we call a scroll edge "reached"

export default function Nav({ activeTab, onSelectTab }) {
  const tabs = TABS;
  const trackRef = useRef(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  function updateArrows() {
    const el = trackRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > EDGE);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - EDGE);
  }

  useEffect(() => {
    updateArrows();
    const el = trackRef.current;
    if (!el) return;
    const onResize = () => updateArrows();
    window.addEventListener("resize", onResize);
    // Let a normal vertical mouse-wheel scroll the row sideways too - most
    // pointing devices only send vertical wheel deltas, and few people know
    // Shift+scroll is what moves a horizontal list.
    const onWheel = (e) => {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        el.scrollLeft += e.deltaY;
        e.preventDefault();
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      window.removeEventListener("resize", onResize);
      el.removeEventListener("wheel", onWheel);
    };
  }, []);

  function scrollBy(amount) {
    const el = trackRef.current;
    if (el) el.scrollBy({ left: amount, behavior: "smooth" });
  }

  return (
    <nav className="topnav">
      <div className="brand">
        <span className="brandMark">TDM</span>
        <span className="brandName">TDM Platform</span>
      </div>

      <button
        className="tabsArrow left"
        aria-label="Scroll tabs left"
        onClick={() => scrollBy(-160)}
        style={{ visibility: canScrollLeft ? "visible" : "hidden" }}
      >
        &#8249;
      </button>

      <div className="tabs" ref={trackRef} onScroll={updateArrows}>
        {tabs.map((t) => (
          <button
            key={t.id}
            className={`tabBtn ${activeTab === t.id ? "active" : ""}`}
            onClick={() => onSelectTab(t.id)}
          >
            <span className="tabIcon">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      <button
        className="tabsArrow right"
        aria-label="Scroll tabs right"
        onClick={() => scrollBy(160)}
        style={{ visibility: canScrollRight ? "visible" : "hidden" }}
      >
        &#8250;
      </button>

    </nav>
  );
}

export { TABS };

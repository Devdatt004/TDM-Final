import { useEffect, useRef, useState } from "react";

// Smoothly counts from the previous numeric value to the next one whenever
// `value` changes, instead of snapping instantly. Falls back to rendering
// non-numeric values (like "-") as-is.
export default function AnimatedNumber({ value, duration = 600 }) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef(null);

  useEffect(() => {
    const from = typeof fromRef.current === "number" ? fromRef.current : 0;
    const to = value;

    if (typeof to !== "number" || typeof from !== "number" || from === to) {
      setDisplay(to);
      fromRef.current = to;
      return;
    }

    const start = performance.now();
    cancelAnimationFrame(rafRef.current);

    function tick(now) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      const current = Math.round(from + (to - from) * eased);
      setDisplay(current);
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = to;
      }
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [value, duration]);

  return <>{display}</>;
}

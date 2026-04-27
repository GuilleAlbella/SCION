"use client";

import { useState, useEffect, useRef } from "react";

interface AnimatedCounterProps {
  value: number;
  duration?: number;
  className?: string;
  style?: React.CSSProperties;
  prefix?: string;
  suffix?: string;
  decimals?: number;
}

/**
 * AnimatedCounter — smoothly tweens between the previous value and the new
 * `value` prop using requestAnimationFrame and an ease-out-cubic curve.
 * Used for KPI cards so numbers feel alive instead of snapping.
 */
export default function AnimatedCounter({
  value,
  duration = 800,
  className = "",
  style,
  prefix = "",
  suffix = "",
  decimals = 0,
}: AnimatedCounterProps) {
  const [display, setDisplay] = useState(0);
  // Holds the last animated-to value so each new tween starts from where
  // we left off (not from 0). Stored in a ref to avoid re-renders.
  const prevValue = useRef(0);
  // Active requestAnimationFrame handle so we can cancel on cleanup.
  const rafRef = useRef<number>(0);

  useEffect(() => {
    // Snapshot the start and end values outside the raf callback so the
    // animation keeps running smoothly even if `value` changes mid-flight
    // (cleanup will cancel this raf and a fresh effect will restart).
    const start = prevValue.current;
    const end = value;
    const startTime = performance.now();

    function animate(now: number) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = start + (end - start) * eased;
      setDisplay(current);

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate);
      } else {
        setDisplay(end);
        prevValue.current = end;
      }
    }

    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [value, duration]);

  const formatted = decimals > 0
    ? display.toFixed(decimals)
    : Math.round(display).toLocaleString();

  return (
    <span className={`animate-count-up ${className}`} style={style}>
      {prefix}{formatted}{suffix}
    </span>
  );
}

"use client";

import { useEffect, useState } from "react";

// Current time in epoch seconds, refreshed once a second while `active`.
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now() / 1000);

  useEffect(() => {
    if (!active) return;
    setNow(Date.now() / 1000);
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [active]);

  return now;
}

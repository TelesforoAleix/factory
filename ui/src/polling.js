// One request at a time. Hidden tabs own no timer; becoming visible refreshes now.
export function visiblePolling(poll, milliseconds) {
  let stopped = false, running = false, timer;
  async function tick() {
    if (stopped || document.hidden || running) return;
    running = true;
    try {await poll();} finally {
      running = false;
      if (!stopped && !document.hidden) timer = setTimeout(tick, milliseconds);
    }
  }
  function visibility() {clearTimeout(timer); if (!document.hidden) tick();}
  document.addEventListener('visibilitychange', visibility);
  tick();
  return () => {stopped = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visibility);};
}

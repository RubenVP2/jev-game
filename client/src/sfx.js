// Effets sonores synthétisés (Web Audio), partagent l'AudioContext de la voix.
export function createSfx(getCtx) {
  const tone = (freq, dur, type = 'sine', vol = 0.15, delay = 0) => {
    const ctx = getCtx();
    if (!ctx) return;
    const t = ctx.currentTime + delay;
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(ctx.destination);
    o.start(t);
    o.stop(t + dur);
  };
  return {
    success() { tone(660, 0.12, 'triangle'); tone(990, 0.2, 'triangle', 0.15, 0.1); },
    neutral() { tone(300, 0.2, 'sine', 0.1); },
    alarm() { for (let i = 0; i < 6; i++) tone(i % 2 ? 520 : 880, 0.22, 'square', 0.08, i * 0.24); },
    fatal() { tone(90, 1.6, 'sawtooth', 0.25); tone(60, 1.8, 'square', 0.15, 0.1); },
    caught() { tone(140, 0.5, 'sawtooth', 0.2); tone(70, 0.7, 'square', 0.15, 0.15); },
    heartbeat(vol) { tone(55, 0.12, 'sine', vol); tone(50, 0.12, 'sine', vol * 0.8, 0.18); },
    open() { tone(440, 0.15, 'triangle'); tone(550, 0.15, 'triangle', 0.15, 0.15); tone(880, 0.3, 'triangle', 0.15, 0.3); },
  };
}

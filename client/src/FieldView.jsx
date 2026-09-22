import { useEffect, useRef, useState } from 'react';
import { angleDiff } from './geometry.js';
import { drawMap, drawPlayer, drawMonster } from './render.js';
import { TopBar, LogPanel, VotePanel } from './Hud.jsx';

const SPEED = 4;
const FOV = Math.PI / 4; // demi-angle : cône de 90°
const INTERACT = 1.6;
const ACTIVE = ['CLUE', 'FIELD', 'EXTRACTION'];

export default function FieldView({ state, me, net, voice, geo, map, stateRef, correctionRef, sfx }) {
  const canvasRef = useRef(null);
  const pos = useRef({ x: me?.x ?? 20, y: me?.y ?? 13, a: me?.a ?? 0 });
  const keys = useRef(new Set());
  const joy = useRef({ x: 0, y: 0 });
  const promptRef = useRef(null);
  const [prompt, setPrompt] = useState(null);

  const interact = () => {
    const p = promptRef.current;
    if (p) net.send({ t: 'validate', id: p.id });
  };

  useEffect(() => {
    const down = (e) => {
      if (e.target.tagName === 'INPUT') return;
      const k = e.key.toLowerCase();
      if (k === ' ' || k === 'e') { e.preventDefault(); if (!e.repeat) interact(); return; }
      if (k.startsWith('arrow')) e.preventDefault();
      keys.current.add(k);
    };
    const up = (e) => keys.current.delete(e.key.toLowerCase());
    const blur = () => keys.current.clear();
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    window.addEventListener('blur', blur);
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); window.removeEventListener('blur', blur); };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const fog = document.createElement('canvas');
    const fctx = fog.getContext('2d');
    const disp = new Map();
    let raf, last = performance.now(), lastSend = 0, lastCorr = correctionRef.current.seq, beatAt = 0, sent = '';

    const resize = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = fog.width = canvas.clientWidth * dpr;
      canvas.height = fog.height = canvas.clientHeight * dpr;
    };
    resize();
    window.addEventListener('resize', resize);

    const frame = (now) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const s = stateRef.current;
      if (!s) return;
      const self = s.players.find((p) => p.id === s.you.id);
      const P = pos.current;
      if (correctionRef.current.seq !== lastCorr) {
        lastCorr = correctionRef.current.seq;
        P.x = correctionRef.current.x; P.y = correctionRef.current.y;
      }
      const alive = s.you.alive && ACTIVE.includes(s.phase);

      // ── Déplacement (ZQSD / WASD / flèches / joystick)
      if (alive) {
        const k = keys.current;
        let dx = joy.current.x, dy = joy.current.y;
        if (k.has('z') || k.has('w') || k.has('arrowup')) dy -= 1;
        if (k.has('s') || k.has('arrowdown')) dy += 1;
        if (k.has('q') || k.has('a') || k.has('arrowleft')) dx -= 1;
        if (k.has('d') || k.has('arrowright')) dx += 1;
        const len = Math.hypot(dx, dy);
        if (len > 0.1) {
          if (len > 1) { dx /= len; dy /= len; }
          const nx = P.x + dx * SPEED * dt, ny = P.y + dy * SPEED * dt;
          if (geo.circleFree(nx, P.y)) P.x = nx;
          if (geo.circleFree(P.x, ny)) P.y = ny;
          P.a = Math.atan2(dy, dx);
        }
        const key = `${P.x.toFixed(2)},${P.y.toFixed(2)},${P.a.toFixed(2)}`;
        if (now - lastSend > 66 && key !== sent) {
          net.send({ t: 'pos', x: P.x, y: P.y, a: P.a });
          lastSend = now; sent = key;
        }
      } else if (self) { P.x = self.x; P.y = self.y; }

      // ── Interpolation des autres joueurs
      for (const p of s.players) {
        if (p.id === s.you.id) continue;
        const d = disp.get(p.id) || { x: p.x, y: p.y };
        const f = Math.min(1, dt * 12);
        d.x += (p.x - d.x) * f; d.y += (p.y - d.y) * f;
        disp.set(p.id, d);
      }

      // ── Rendu
      const W = canvas.width, H = canvas.height;
      const S = Math.min(W, H) / 13;
      const ox = W / 2 - P.x * S, oy = H / 2 - P.y * S;
      ctx.fillStyle = '#05070a';
      ctx.fillRect(0, 0, W, H);
      const bounds = [Math.floor(-ox / S) - 1, Math.floor(-oy / S) - 1, Math.ceil((W - ox) / S) + 1, Math.ceil((H - oy) / S) + 1];
      const range = 9 - (s.crisis - 1) * 0.9;
      const spectator = !alive;
      const visible = (x, y) => {
        if (spectator) return true;
        const d = Math.hypot(x - P.x, y - P.y);
        if (d < 1.4) return true;
        return d < range && angleDiff(Math.atan2(y - P.y, x - P.x), P.a) <= FOV && geo.los(P.x, P.y, x, y);
      };

      drawMap(ctx, { map, board: s.board, phase: s.phase, S, ox, oy, labels: true, labelVisible: visible, bounds });

      for (const p of s.players) {
        if (p.publicRole !== 'field' || p.id === s.you.id || (!p.alive && !spectator)) continue;
        const d = disp.get(p.id);
        if (visible(d.x, d.y)) drawPlayer(ctx, { ...p, x: d.x, y: d.y }, d.x * S + ox, d.y * S + oy, S);
      }
      const m = s.monster;
      if (m && visible(m.x, m.y)) drawMonster(ctx, m.x * S + ox, m.y * S + oy, S, now);
      if (self && ACTIVE.includes(s.phase)) drawPlayer(ctx, { ...self, x: P.x, y: P.y, a: P.a }, W / 2, H / 2, S, { name: false });

      // ── Brouillard de guerre : torche directionnelle 90° avec ombres portées
      if (!spectator) {
        fctx.globalCompositeOperation = 'source-over';
        fctx.clearRect(0, 0, W, H);
        fctx.fillStyle = `rgba(0,0,0,${0.955 + s.crisis * 0.008})`;
        fctx.fillRect(0, 0, W, H);
        fctx.globalCompositeOperation = 'destination-out';
        const cx = W / 2, cy = H / 2;
        const grad = fctx.createRadialGradient(cx, cy, 0, cx, cy, range * S);
        grad.addColorStop(0, 'rgba(0,0,0,1)');
        grad.addColorStop(0.65, 'rgba(0,0,0,0.9)');
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        fctx.fillStyle = grad;
        fctx.beginPath();
        fctx.moveTo(cx, cy);
        const N = 48;
        for (let i = 0; i <= N; i++) {
          const ang = P.a - FOV + (2 * FOV * i) / N;
          const d = geo.ray(P.x, P.y, ang, range) + 0.35;
          fctx.lineTo(cx + Math.cos(ang) * d * S, cy + Math.sin(ang) * d * S);
        }
        fctx.closePath();
        fctx.fill();
        const aura = fctx.createRadialGradient(cx, cy, 0, cx, cy, 1.6 * S);
        aura.addColorStop(0, 'rgba(0,0,0,0.85)');
        aura.addColorStop(1, 'rgba(0,0,0,0)');
        fctx.fillStyle = aura;
        fctx.beginPath(); fctx.arc(cx, cy, 1.6 * S, 0, Math.PI * 2); fctx.fill();
        ctx.drawImage(fog, 0, 0);
      }

      // ── La Taupe voit la menace à travers les murs
      if (m && s.you.role === 'mole') {
        const sx = m.x * S + ox, sy = m.y * S + oy;
        if (sx > 0 && sy > 0 && sx < W && sy < H) drawMonster(ctx, sx, sy, S, now, true);
        else {
          const ang = Math.atan2(sy - H / 2, sx - W / 2);
          const r = Math.min(W, H) / 2 - 30;
          ctx.save();
          ctx.translate(W / 2 + Math.cos(ang) * r, H / 2 + Math.sin(ang) * r);
          ctx.rotate(ang);
          ctx.fillStyle = '#ff2b4a';
          ctx.beginPath(); ctx.moveTo(14, 0); ctx.lineTo(-8, -9); ctx.lineTo(-8, 9); ctx.fill();
          ctx.restore();
        }
      }

      // ── Vignette de crise
      if (s.crisis > 1) {
        const a = (s.crisis - 1) * 0.07 * (0.7 + 0.3 * Math.sin(now / (300 - s.crisis * 40)));
        const v = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.3, W / 2, H / 2, Math.max(W, H) * 0.7);
        v.addColorStop(0, 'rgba(255,0,30,0)');
        v.addColorStop(1, `rgba(255,0,30,${a})`);
        ctx.fillStyle = v;
        ctx.fillRect(0, 0, W, H);
      }

      // ── Battements de cœur quand le Patrouilleur approche
      if (alive && m) {
        const d = Math.hypot(m.x - P.x, m.y - P.y);
        if (d < 9 && now > beatAt) { sfx.heartbeat(0.25 * (1 - d / 9) + 0.05); beatAt = now + 350 + d * 110; }
      }

      // ── Terminal à portée
      let best = null;
      if (alive && s.phase === 'FIELD' && s.board) {
        for (const t of map.terminals) {
          const cell = s.board[t.id];
          const d = Math.hypot(t.x + 0.5 - P.x, t.y + 0.5 - P.y);
          if (cell.state === 'hidden' && d < INTERACT && (!best || d < best.d)) best = { id: t.id, word: cell.word, d };
        }
      }
      if ((best?.id ?? null) !== (promptRef.current?.id ?? null)) { promptRef.current = best; setPrompt(best); }

      voice.update({ state: s, me: self, pos: P, geo });
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize); };
  }, [map, geo]);

  const role = state.you.role;
  return (
    <div className="game">
      <canvas ref={canvasRef} className="stage" />
      <TopBar state={state} voice={voice} />
      {role === 'mole' && state.you.alive && <div className="hint mole">Vous êtes LA TAUPE — le Patrouilleur vous est visible. Semez le doute.</div>}
      {!state.you.alive && state.phase !== 'OVER' && <div className="hint dead">CONFINÉ — liaison radio coupée. Mode spectateur.</div>}
      {state.phase === 'CLUE' && state.you.alive && <div className="hint">L’Opérateur prépare son indice… dispersez-vous.</div>}
      {prompt && (
        <button className="prompt" onClick={interact}>
          <kbd>ESPACE</kbd> Valider « {prompt.word} »
        </button>
      )}
      <LogPanel log={state.log} />
      <VotePanel state={state} net={net} />
      <Joystick joy={joy} />
      <button className="action-btn" onClick={interact} disabled={!prompt}>⚡</button>
    </div>
  );
}

function Joystick({ joy }) {
  const [knob, setKnob] = useState(null);
  const R = 55;
  const move = (e, k) => {
    let dx = e.clientX - k.ox, dy = e.clientY - k.oy;
    const d = Math.hypot(dx, dy);
    if (d > R) { dx = (dx / d) * R; dy = (dy / d) * R; }
    joy.current = { x: dx / R, y: dy / R };
    setKnob({ ...k, kx: dx, ky: dy });
  };
  return (
    <div
      className="joy-zone"
      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); setKnob({ ox: e.clientX, oy: e.clientY, kx: 0, ky: 0 }); }}
      onPointerMove={(e) => knob && move(e, knob)}
      onPointerUp={() => { joy.current = { x: 0, y: 0 }; setKnob(null); }}
      onPointerCancel={() => { joy.current = { x: 0, y: 0 }; setKnob(null); }}
    >
      {knob && (
        <div className="joy-base" style={{ left: knob.ox - R, top: knob.oy - R, width: R * 2, height: R * 2 }}>
          <div className="joy-knob" style={{ transform: `translate(${knob.kx}px, ${knob.ky}px)` }} />
        </div>
      )}
    </div>
  );
}

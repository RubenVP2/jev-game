// Rendu 2D Canvas partagé (vue terrain et minicarte de l'Opérateur).
import { colorFor } from './geometry.js';

export const ALIGN_COLORS = { TARGET: '#2ecc71', NEUTRAL: '#8a96a3', TRAP: '#ff8c1a', FATAL: '#ff2b4a' };
const STATE_COLORS = { found: '#2ecc71', lost: '#9b59b6' };

export function terminalColor(cell) {
  if (!cell) return '#00e5ff';
  if (cell.state === 'hidden') return '#00e5ff';
  return STATE_COLORS[cell.state] || ALIGN_COLORS[cell.align] || '#8a96a3';
}

// Dessine la carte : S = pixels par mètre, (ox, oy) = décalage écran.
export function drawMap(ctx, { map, board, phase, S, ox, oy, labels = false, labelVisible = null, showAlign = false, bounds }) {
  const { w, h, tiles } = map;
  const [x0, y0, x1, y1] = bounds || [0, 0, w - 1, h - 1];
  const open = phase === 'EXTRACTION';
  for (let y = Math.max(0, y0); y <= Math.min(h - 1, y1); y++) {
    for (let x = Math.max(0, x0); x <= Math.min(w - 1, x1); x++) {
      const c = tiles[y][x], px = x * S + ox, py = y * S + oy;
      if (c === '#') {
        ctx.fillStyle = '#26303b';
        ctx.fillRect(px, py, S + 0.5, S + 0.5);
        ctx.fillStyle = '#323e4b';
        ctx.fillRect(px, py, S + 0.5, S * 0.15);
        continue;
      }
      ctx.fillStyle = c === 'E' ? (open ? '#1d6b3e' : '#1a2a22') : (x + y) % 2 ? '#10151b' : '#121820';
      ctx.fillRect(px, py, S + 0.5, S + 0.5);
      if (c === 'V') {
        ctx.strokeStyle = '#3b4a58';
        ctx.lineWidth = Math.max(1, S * 0.06);
        for (let i = 1; i < 4; i++) {
          ctx.beginPath(); ctx.moveTo(px + S * 0.15, py + (S * i) / 4); ctx.lineTo(px + S * 0.85, py + (S * i) / 4); ctx.stroke();
        }
      }
    }
  }
  const el = map.elevator;
  ctx.strokeStyle = open ? '#2ecc71' : '#2f5a40';
  ctx.lineWidth = Math.max(1, S * 0.08);
  ctx.strokeRect(el.x0 * S + ox, el.y0 * S + oy, (el.x1 - el.x0 + 1) * S, (el.y1 - el.y0 + 1) * S);
  if (labels) {
    ctx.fillStyle = open ? '#7dffb0' : '#3f6b50';
    ctx.font = `bold ${S * 0.45}px ui-monospace, monospace`;
    ctx.textAlign = 'center';
    ctx.fillText(open ? 'ASCENSEUR OUVERT' : 'ASCENSEUR', ((el.x0 + el.x1 + 1) / 2) * S + ox, ((el.y0 + el.y1 + 1) / 2) * S + oy);
  }
  for (const t of map.terminals) {
    const cell = board?.[t.id];
    const px = t.x * S + ox, py = t.y * S + oy;
    ctx.fillStyle = '#0b1a20';
    ctx.fillRect(px + S * 0.1, py + S * 0.1, S * 0.8, S * 0.8);
    ctx.fillStyle = terminalColor(cell);
    ctx.fillRect(px + S * 0.22, py + S * 0.22, S * 0.56, S * 0.4);
    if (showAlign && cell) {
      ctx.strokeStyle = ALIGN_COLORS[cell.align];
      ctx.lineWidth = Math.max(1.5, S * 0.12);
      ctx.strokeRect(px + S * 0.06, py + S * 0.06, S * 0.88, S * 0.88);
    }
    if (labels && cell && (!labelVisible || labelVisible(t.x + 0.5, t.y + 0.5))) {
      const fs = S * 0.34;
      ctx.font = `bold ${fs}px ui-monospace, monospace`;
      ctx.textAlign = 'center';
      const tw = ctx.measureText(cell.word).width;
      const cx = px + S / 2, cy = py - S * 0.2;
      ctx.fillStyle = 'rgba(5,8,12,0.85)';
      ctx.fillRect(cx - tw / 2 - 4, cy - fs, tw + 8, fs * 1.3);
      ctx.fillStyle = cell.state === 'hidden' ? '#d6f7ff' : terminalColor(cell);
      ctx.fillText(cell.word, cx, cy);
      if (cell.state !== 'hidden') {
        ctx.strokeStyle = ctx.fillStyle;
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(cx - tw / 2, cy - fs * 0.35); ctx.lineTo(cx + tw / 2, cy - fs * 0.35); ctx.stroke();
      }
    }
  }
}

export function drawPlayer(ctx, p, sx, sy, S, { name = true } = {}) {
  const r = S * 0.3;
  if (p.vol > 0.1) {
    ctx.strokeStyle = 'rgba(0,229,255,0.6)';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(sx, sy, r + S * 0.1 + p.vol * S * 0.3, 0, Math.PI * 2); ctx.stroke();
  }
  ctx.fillStyle = p.alive ? colorFor(p.id) : '#555';
  ctx.beginPath(); ctx.arc(sx, sy, r, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = '#000';
  ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(sx + Math.cos(p.a) * r * 1.4, sy + Math.sin(p.a) * r * 1.4); ctx.stroke();
  if (name) {
    ctx.fillStyle = '#e8f1f8';
    ctx.font = `${Math.max(10, S * 0.3)}px ui-monospace, monospace`;
    ctx.textAlign = 'center';
    ctx.fillText(p.name + (p.alive ? '' : ' ☠'), sx, sy + r + S * 0.4);
  }
}

export function drawMonster(ctx, sx, sy, S, t, outline = false) {
  const r = S * (0.42 + Math.sin(t / 120) * 0.04);
  const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, r * 2.2);
  g.addColorStop(0, 'rgba(255,40,60,0.55)');
  g.addColorStop(1, 'rgba(255,40,60,0)');
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(sx, sy, r * 2.2, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#1a0004';
  ctx.beginPath(); ctx.arc(sx, sy, r, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#ff2b4a';
  ctx.beginPath(); ctx.arc(sx - r * 0.3, sy - r * 0.1, r * 0.14, 0, Math.PI * 2); ctx.arc(sx + r * 0.3, sy - r * 0.1, r * 0.14, 0, Math.PI * 2); ctx.fill();
  if (outline) {
    ctx.strokeStyle = '#ff2b4a';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(sx, sy, r * 1.5, 0, Math.PI * 2); ctx.stroke();
    ctx.setLineDash([]);
  }
}

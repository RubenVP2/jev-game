import { useEffect, useRef, useState } from 'react';
import { drawMap, drawPlayer, drawMonster, ALIGN_COLORS } from './render.js';
import { TopBar, LogPanel, VotePanel } from './Hud.jsx';

const ALIGN_LABEL = { TARGET: 'Cible', NEUTRAL: 'Neutre', TRAP: 'Piège', FATAL: 'FATAL' };
const STATE_LABEL = { found: '✓ extraite', revealed: '✗ validée', lost: '⚠ corrompue' };

export default function OperatorView({ state, net, voice, map, clueError, clearClueError }) {
  const [word, setWord] = useState('');
  const [count, setCount] = useState(2);
  const canvasRef = useRef(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    const canvas = canvasRef.current, ctx = canvas.getContext('2d');
    let raf;
    const frame = (now) => {
      raf = requestAnimationFrame(frame);
      const s = stateRef.current;
      const dpr = Math.min(2, devicePixelRatio || 1);
      if (canvas.width !== canvas.clientWidth * dpr) { canvas.width = canvas.clientWidth * dpr; canvas.height = canvas.clientHeight * dpr; }
      const S = Math.min(canvas.width / map.w, canvas.height / map.h);
      const ox = (canvas.width - map.w * S) / 2, oy = (canvas.height - map.h * S) / 2;
      ctx.fillStyle = '#05070a';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      drawMap(ctx, { map, board: s.board, phase: s.phase, S, ox, oy, showAlign: true });
      for (const p of s.players) if (p.publicRole === 'field' && !p.ejected) drawPlayer(ctx, p, p.x * S + ox, p.y * S + oy, S * 1.4);
      if (s.monster) drawMonster(ctx, s.monster.x * S + ox, s.monster.y * S + oy, S * 1.3, now);
      voice.update({ state: s, me: null, pos: { x: 0, y: 0, a: 0 }, geo: null });
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [map]);

  const submit = (e) => {
    e.preventDefault();
    clearClueError();
    net.send({ t: 'clue', word: word.trim(), count });
  };
  useEffect(() => { if (state.phase === 'FIELD') setWord(''); }, [state.phase]);

  return (
    <div className="op-view">
      <TopBar state={state} voice={voice} />
      <div className="op-body">
        <section className="panel op-grid-wrap">
          <h3>Grille maîtresse</h3>
          <div className="op-grid">
            {state.board?.map((c, i) => (
              <div key={i} className={`card ${c.state}`} style={{ '--c': ALIGN_COLORS[c.align] }}>
                <span className="word">{c.word}</span>
                <span className="align">{ALIGN_LABEL[c.align]}</span>
                {c.state !== 'hidden' && <span className="state">{STATE_LABEL[c.state]}</span>}
              </div>
            ))}
          </div>
          <form className="clue-form" onSubmit={submit}>
            <input value={word} onChange={(e) => setWord(e.target.value)} placeholder="Mot de code" maxLength={24}
              disabled={state.phase !== 'CLUE' || state.cluePending} />
            <select value={count} onChange={(e) => setCount(Number(e.target.value))} disabled={state.phase !== 'CLUE'}>
              {[1, 2, 3, 4].map((n) => <option key={n}>{n}</option>)}
            </select>
            <button className="primary" disabled={state.phase !== 'CLUE' || state.cluePending || !word.trim()}>
              {state.cluePending ? 'Kev…' : 'Transmettre'}
            </button>
          </form>
          {clueError && <p className="error">Kev : {clueError}</p>}
          {state.clue && <p className="muted">Indice actif : « {state.clue.word} » {state.clue.count} — validé en {state.clue.ms} ms ({state.clue.source}{state.clue.kevP != null && `, Kev p(légal) = ${state.clue.kevP.toFixed(2)}`}).</p>}
        </section>
        <section className="panel op-map-wrap">
          <h3>Caméras du complexe</h3>
          <canvas ref={canvasRef} className="op-map" />
          <p className="muted">Radio unidirectionnelle : vous entendez l’équipe, elle ne vous entend pas.</p>
        </section>
      </div>
      <LogPanel log={state.log} />
      <VotePanel state={state} net={net} />
    </div>
  );
}

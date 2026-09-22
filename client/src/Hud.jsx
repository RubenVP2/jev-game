import { useState } from 'react';
import { colorFor } from './geometry.js';

const ROLE_LABEL = { operator: 'OPÉRATEUR', infiltrator: 'INFILTRÉ', mole: 'LA TAUPE' };
export const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

export function MicButton({ voice }) {
  const [status, setStatus] = useState(voice.local ? (voice.muted ? 'muted' : 'on') : 'off');
  const click = async () => {
    if (status === 'off') {
      try { await voice.enableMic(); setStatus('on'); } catch { setStatus('denied'); }
    } else {
      voice.setMuted(status === 'on');
      setStatus(status === 'on' ? 'muted' : 'on');
    }
  };
  const label = { off: '🎙 Activer le micro', on: '🎙 Micro actif', muted: '🔇 Micro coupé', denied: '⚠ Micro refusé (HTTPS requis)' }[status];
  return <button className={`mic ${status}`} onClick={click} disabled={status === 'denied'}>{label}</button>;
}

export function TopBar({ state, voice }) {
  const { data, clue } = state;
  return (
    <div className="topbar">
      <span className={`role ${state.you.role}`}>{ROLE_LABEL[state.you.role]}</span>
      <span>Manche {state.round}/{state.rounds}</span>
      <span className={state.timer < 30 ? 'danger' : ''}>⏱ {fmt(state.timer)}</span>
      <span title="Banques récupérées / objectif">💾 {data.found}/{data.need}{data.lost ? <em className="danger"> −{data.lost}</em> : null}</span>
      <span className="crisis" title="Niveau de crise (Kev)">
        {[1, 2, 3, 4, 5].map((i) => <i key={i} className={i <= state.crisis ? 'on' : ''} />)}
      </span>
      <span className="clue-chip">
        {state.phase === 'EXTRACTION' ? `🛗 EXTRACTION ${state.extractionTimer}s`
          : clue ? <>« {clue.word} » {clue.count} <small>({state.guessesLeft} restants)</small></>
          : state.cluePending ? 'Kev analyse l’indice…' : 'En attente de l’indice…'}
      </span>
      <MicButton voice={voice} />
    </div>
  );
}

export function LogPanel({ log }) {
  return (
    <div className="log">
      {log.slice(-6).map((e) => <div key={e.id} className={`log-${e.kind}`}>{e.msg}</div>)}
    </div>
  );
}

export function VotePanel({ state, net }) {
  if (state.phase !== 'EXTRACTION') return null;
  const me = state.you;
  const canVote = me.role === 'operator' || me.alive;
  const suspects = state.players.filter((p) => p.publicRole === 'field' && !p.ejected && p.id !== me.id);
  return (
    <div className="panel vote">
      <h3>Vote flash d’exclusion — {state.extractionTimer}s</h3>
      <p className="muted">Rejoignez l’ascenseur et verrouillez la Taupe.</p>
      <div className="vote-grid">
        {suspects.map((p) => (
          <button key={p.id} disabled={!canVote} className={me.vote === p.id ? 'selected' : ''} onClick={() => net.send({ t: 'vote', target: p.id })}>
            <span className="dot" style={{ background: colorFor(p.id) }} />{p.name}
            {!p.alive && ' ☠'} {state.votes[p.id] ? <b>×{state.votes[p.id]}</b> : null}
          </button>
        ))}
        <button disabled={!canVote} className={me.vote === 'skip' ? 'selected' : ''} onClick={() => net.send({ t: 'vote', target: 'skip' })}>
          S’abstenir {state.votes.skip ? <b>×{state.votes.skip}</b> : null}
        </button>
      </div>
    </div>
  );
}

export function GameOver({ state, me, net, onLeave }) {
  const w = state.winner;
  if (!w) return null;
  return (
    <div className="overlay">
      <div className={`panel gameover ${w.side}`}>
        <h1>{w.side === 'team' ? 'EXTRACTION RÉUSSIE' : 'VICTOIRE DE LA TAUPE'}</h1>
        <p>{w.reason}</p>
        <p className="muted">Banques récupérées : {state.data.found}/{state.data.total} (objectif {state.data.need})</p>
        <ul className="player-list">
          {state.players.map((p) => (
            <li key={p.id}>
              <span className="dot" style={{ background: colorFor(p.id) }} />
              {p.name} — <b className={`role ${p.role}`}>{ROLE_LABEL[p.role] || '—'}</b>
              {p.ejected && ' (éjecté)'}
            </li>
          ))}
        </ul>
        {me?.host ? <button className="primary" onClick={() => net.send({ t: 'lobby' })}>Retour au salon</button>
          : <p className="muted">L’hôte peut relancer une partie.</p>}
        <button className="ghost" onClick={onLeave}>Quitter</button>
      </div>
    </div>
  );
}

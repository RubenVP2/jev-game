import { useState } from 'react';
import { colorFor } from './geometry.js';
import { MicButton } from './Hud.jsx';

export default function Lobby({ state, me, net, voice, onLeave, error }) {
  const [copied, setCopied] = useState(false);
  const players = state.players.filter((p) => p.connected);
  const link = `${location.origin}/?room=${state.code}`;
  const canStart = me?.host && players.length >= state.minPlayers;

  const copy = async () => {
    try { await navigator.clipboard.writeText(link); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch {}
  };

  return (
    <div className="home">
      <div className="panel home-card">
        <h2>Salon <span className="code">{state.code}</span></h2>
        <button className="ghost" onClick={copy}>{copied ? 'Lien copié ✓' : 'Copier le lien d’invitation'}</button>
        <ul className="player-list">
          {players.map((p) => (
            <li key={p.id}>
              <span className="dot" style={{ background: colorFor(p.id) }} />
              {p.name}{p.id === me?.id && ' (vous)'}
              {p.host && <span className="badge">hôte</span>}
              {p.wantsOperator && <span className="badge op">opérateur ?</span>}
              {p.vol > 0.1 && <span className="speaking">◉</span>}
            </li>
          ))}
        </ul>
        <p className="muted">{players.length}/{state.maxPlayers} joueurs — minimum {state.minPlayers}.</p>
        <label className="check">
          <input type="checkbox" checked={!!me?.wantsOperator} onChange={(e) => net.send({ t: 'prefs', operator: e.target.checked })} />
          Je me porte volontaire pour être l’Opérateur
        </label>
        <MicButton voice={voice} />
        {me?.host
          ? <button className="primary" disabled={!canStart} onClick={() => net.send({ t: 'start' })}>Lancer le protocole</button>
          : <p className="muted">En attente de l’hôte…</p>}
        {error && <p className="error">{error}</p>}
        <button className="ghost" onClick={onLeave}>Quitter</button>
      </div>
    </div>
  );
}

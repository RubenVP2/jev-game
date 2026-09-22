import { useEffect, useMemo, useRef, useState } from 'react';
import { createNet } from './net.js';
import { Voice } from './voice.js';
import { createSfx } from './sfx.js';
import { makeGeo } from './geometry.js';
import Home from './Home.jsx';
import Lobby from './Lobby.jsx';
import FieldView from './FieldView.jsx';
import OperatorView from './OperatorView.jsx';
import { GameOver } from './Hud.jsx';

export default function App() {
  const [joined, setJoined] = useState(null);
  const [state, setState] = useState(null);
  const [error, setError] = useState('');
  const [online, setOnline] = useState(true);
  const [clueError, setClueError] = useState('');
  const stateRef = useRef(null);
  const correctionRef = useRef({ seq: 0 });
  const lastLogRef = useRef(0);

  const net = useMemo(() => createNet({
    onStatus: (s) => setOnline(s === 'online'),
    onMessage: (msg) => handlers.current(msg),
  }), []);
  const voice = useMemo(() => new Voice((m) => net.send(m)), [net]);
  const sfx = useMemo(() => createSfx(() => voice.ctx), [voice]);
  const geo = useMemo(() => (joined ? makeGeo(joined.map) : null), [joined]);

  const handlers = useRef(null);
  handlers.current = (msg) => {
    switch (msg.t) {
      case 'joined':
        setJoined(msg);
        setError('');
        history.replaceState(null, '', `?room=${msg.room}`);
        break;
      case 'error': setError(msg.msg); break;
      case 'state': {
        stateRef.current = msg;
        setState(msg);
        const ids = msg.players.filter((p) => p.connected).map((p) => p.id);
        if (!voice.helloSent) { voice.helloSent = true; voice.me = msg.you.id; voice.hello(ids); }
        voice.sync(msg.you.id, ids);
        for (const e of msg.log) {
          if (e.id <= lastLogRef.current) continue;
          if (lastLogRef.current) {
            if (e.kind === 'trap') sfx.alarm();
            else if (e.kind === 'fatal') sfx.fatal();
            else if (e.kind === 'caught') sfx.caught();
            else if (e.kind === 'success') sfx.success();
            else if (e.kind === 'neutral') sfx.neutral();
            else if (e.kind === 'alert' && msg.phase === 'EXTRACTION') sfx.open();
          }
          lastLogRef.current = e.id;
        }
        break;
      }
      case 'correct': correctionRef.current = { seq: correctionRef.current.seq + 1, x: msg.x, y: msg.y }; break;
      case 'clueRejected': setClueError(msg.reason); break;
      case 'rtc': voice.onSignal(msg.from, msg.data); break;
      case 'peer-left': voice.drop(msg.id); break;
    }
  };

  useEffect(() => () => { net.close(); voice.closeAll(); }, [net, voice]);

  const join = (room, name) => {
    voice.ensureCtx();
    localStorage.setItem('sp-name', name);
    net.join(room, name);
  };

  const leave = () => {
    net.close();
    voice.closeAll();
    voice.helloSent = false;
    setJoined(null);
    setState(null);
    history.replaceState(null, '', '/');
  };

  if (!joined || !state) return <Home onJoin={join} error={error} />;

  const me = state.players.find((p) => p.id === state.you.id);
  const common = { state, me, net, voice, geo, map: joined.map, online };
  let view;
  if (state.phase === 'LOBBY') view = <Lobby {...common} onLeave={leave} error={error} />;
  else if (state.you.role === 'operator')
    view = <OperatorView {...common} clueError={clueError} clearClueError={() => setClueError('')} />;
  else view = <FieldView {...common} stateRef={stateRef} correctionRef={correctionRef} sfx={sfx} />;

  return (
    <>
      {view}
      {state.phase === 'OVER' && <GameOver state={state} me={me} net={net} onLeave={leave} />}
      {!online && <div className="offline">Connexion perdue… reconnexion en cours</div>}
    </>
  );
}

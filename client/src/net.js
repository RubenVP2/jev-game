// Connexion WebSocket avec reconnexion automatique au même salon.
export function getClientId() {
  let id = sessionStorage.getItem('sp-client-id');
  if (!id) {
    id = crypto.randomUUID?.() || String(Math.random()).slice(2);
    sessionStorage.setItem('sp-client-id', id);
  }
  return id;
}

export function createNet({ onMessage, onStatus }) {
  let ws = null, session = null, closedByUser = false, retry = null;

  function open() {
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    ws.onopen = () => {
      onStatus?.('online');
      ws.send(JSON.stringify({ t: 'join', room: session.room, name: session.name, clientId: getClientId() }));
    };
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.t === 'joined') session.room = msg.room;
      if (msg.t === 'error' && !session.joined) closedByUser = true;
      if (msg.t === 'joined') session.joined = true;
      onMessage(msg);
    };
    ws.onclose = () => {
      onStatus?.('offline');
      if (!closedByUser && session?.joined) retry = setTimeout(open, 1500);
    };
  }

  return {
    join(room, name) {
      closedByUser = false;
      session = { room, name, joined: false };
      clearTimeout(retry);
      ws?.close();
      open();
    },
    send(msg) { if (ws?.readyState === 1) ws.send(JSON.stringify(msg)); },
    close() { closedByUser = true; clearTimeout(retry); ws?.close(); },
  };
}

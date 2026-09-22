import express from 'express';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';
import { Room, MAP_PAYLOAD, CONFIG } from './room.js';
import { kev, warmupKev } from './kev.js';

const PORT = Number(process.env.PORT || 3000);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.resolve(__dirname, '../dist');

const iceServers = [{ urls: (process.env.STUN_URLS || 'stun:stun.l.google.com:19302').split(',') }];
if (process.env.TURN_URL)
  iceServers.push({ urls: process.env.TURN_URL.split(','), username: process.env.TURN_USERNAME, credential: process.env.TURN_CREDENTIAL });

const app = express();
app.get('/health', (_req, res) => res.json({ ok: true, rooms: rooms.size, kev: kev.enabled ? kev.model : 'fallback' }));
app.get('/config', (_req, res) => res.json({ iceServers }));
app.use(express.static(DIST, { maxAge: '1h', index: false }));
app.get('*', (_req, res) => res.sendFile(path.join(DIST, 'index.html'), { headers: { 'cache-control': 'no-cache' } }));

const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/ws', maxPayload: 64 * 1024 });
const rooms = new Map();

const newCode = () => {
  const A = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
  let c;
  do c = Array.from({ length: 4 }, () => A[Math.floor(Math.random() * A.length)]).join('');
  while (rooms.has(c));
  return c;
};

wss.on('connection', (ws) => {
  let room = null, player = null;
  ws.isAlive = true;
  ws.on('pong', () => (ws.isAlive = true));
  ws.on('message', (raw) => {
    let msg;
    try { msg = JSON.parse(raw); } catch { return; }
    if (!player) {
      if (msg.t !== 'join') return;
      const code = String(msg.room || '').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 4);
      const name = String(msg.name || '').trim().slice(0, 16);
      const clientId = String(msg.clientId || '').slice(0, 64);
      if (code) {
        room = rooms.get(code);
        if (!room) return ws.send(JSON.stringify({ t: 'error', msg: `Salon ${code} introuvable.` }));
      } else {
        const c = newCode();
        room = new Room(c, (r) => { r.destroy(); rooms.delete(r.code); });
        rooms.set(c, room);
      }
      const res = room.join(ws, name, clientId);
      if (res.error) { room = null; return ws.send(JSON.stringify({ t: 'error', msg: res.error })); }
      player = res.player;
      ws.send(JSON.stringify({ t: 'joined', you: player.id, room: room.code, map: MAP_PAYLOAD, config: CONFIG }));
      return;
    }
    room.handle(player, msg);
  });
  ws.on('close', () => { if (room && player && player.ws === ws) room.leave(player); });
});

setInterval(() => {
  for (const ws of wss.clients) {
    if (!ws.isAlive) { ws.terminate(); continue; }
    ws.isAlive = false;
    ws.ping();
  }
}, 15000);

server.listen(PORT, () => {
  console.log(`Subterfuge Protocol en écoute sur :${PORT} (kev: ${kev.enabled ? kev.model : 'repli déterministe'})`);
  warmupKev();
});

for (const sig of ['SIGTERM', 'SIGINT']) process.on(sig, () => { server.close(); process.exit(0); });

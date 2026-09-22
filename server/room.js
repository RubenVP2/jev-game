import {
  MAP_PAYLOAD, TERMINALS, VENTS, SPAWN, MONSTER_SPAWN, FLOOR_TILES,
  sectorAt, circleFree, findPath, inElevator,
} from './map.js';
import { WORDS } from './words.js';
import { validateOperatorClue, directMonsterBehavior, evaluateMistakeSeverity } from './arbiter.js';

export const CONFIG = {
  ROUNDS: 3,
  ROUND_SECONDS: Number(process.env.ROUND_SECONDS || 180),
  EXTRACTION_SECONDS: Number(process.env.EXTRACTION_SECONDS || 30),
  DIRECTOR_INTERVAL: Number(process.env.DIRECTOR_INTERVAL || 7),
  MIN_PLAYERS: Math.max(3, Number(process.env.MIN_PLAYERS || 4)),
  MAX_PLAYERS: 8,
  TARGETS_PER_ROUND: 4,
  PLAYER_SPEED: 4,
  CATCH_RADIUS: 0.75,
  INTERACT_RADIUS: 1.7,
};
const TOTAL_BANKS = CONFIG.ROUNDS * CONFIG.TARGETS_PER_ROUND;
const NEED_BANKS = Math.ceil(TOTAL_BANKS * 0.75);
const TICK_MS = 66;
const MONSTER_SPEED = { PATROL_DEFAULT: 2.2, INVESTIGATE_SECTOR: 3.0, HUNT_LOUDEST: 3.9, LOCKDOWN_VENT: 0 };
const ALIGNMENTS = [
  ...Array(6).fill('NEUTRAL'), ...Array(4).fill('TARGET'), ...Array(5).fill('TRAP'), 'FATAL',
];

const shuffle = (a) => {
  const r = [...a];
  for (let i = r.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [r[i], r[j]] = [r[j], r[i]];
  }
  return r;
};
const pick = (a) => a[Math.floor(Math.random() * a.length)];
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const SECTOR_TILES = {};
for (const t of FLOOR_TILES) (SECTOR_TILES[sectorAt(t.x, t.y)] ||= []).push(t);

let nextId = 1;

export class Room {
  constructor(code, onEmpty) {
    this.code = code;
    this.onEmpty = onEmpty;
    this.players = new Map();
    this.phase = 'LOBBY';
    this.log = [];
    this.logId = 0;
    this.gameId = 0;
    this.winner = null;
    this.emptySince = null;
    this.interval = setInterval(() => this.tick(), TICK_MS);
  }

  destroy() { clearInterval(this.interval); }

  // ───────────── Connexions ─────────────
  join(ws, name, clientId) {
    const existing = [...this.players.values()].find((p) => clientId && p.clientId === clientId);
    if (existing) {
      if (existing.ws && existing.ws !== ws) existing.ws.close();
      existing.ws = ws;
      existing.connected = true;
      if (name) existing.name = name;
      return { player: existing };
    }
    if (this.phase !== 'LOBBY') return { error: 'Partie déjà en cours dans ce salon.' };
    if (this.players.size >= CONFIG.MAX_PLAYERS) return { error: 'Salon complet (8 joueurs max).' };
    const player = {
      id: `p${nextId++}`, clientId, name: name || 'Agent', ws, connected: true,
      host: this.players.size === 0, wantsOperator: false,
      role: null, x: SPAWN.x + 0.5, y: SPAWN.y + 0.5, a: 0, alive: true, ejected: false,
      vol: 0, lastPosAt: Date.now(), vote: null,
    };
    this.players.set(player.id, player);
    this.addLog(`${player.name} a rejoint le salon.`);
    return { player };
  }

  leave(player) {
    player.connected = false;
    player.ws = null;
    player.vol = 0;
    if (this.phase === 'LOBBY') {
      this.players.delete(player.id);
      this.addLog(`${player.name} a quitté le salon.`);
    }
    if (player.host) {
      player.host = false;
      const next = [...this.players.values()].find((p) => p.connected);
      if (next) next.host = true;
    }
    for (const p of this.players.values()) this.send(p, { t: 'peer-left', id: player.id });
  }

  send(p, msg) {
    if (p.ws && p.ws.readyState === 1) p.ws.send(JSON.stringify(msg));
  }

  addLog(msg, kind = 'info') {
    this.log.push({ id: ++this.logId, msg, kind });
    if (this.log.length > 12) this.log.shift();
  }

  fieldPlayers() { return [...this.players.values()].filter((p) => p.role && p.role !== 'operator'); }

  // ───────────── Messages ─────────────
  handle(player, msg) {
    switch (msg.t) {
      case 'prefs': if (this.phase === 'LOBBY') player.wantsOperator = !!msg.operator; break;
      case 'start': this.start(player); break;
      case 'lobby': if (player.host && this.phase === 'OVER') this.backToLobby(); break;
      case 'clue': this.submitClue(player, msg.word, msg.count); break;
      case 'pos': this.updatePos(player, msg); break;
      case 'vol': player.vol = Math.max(0, Math.min(1, Number(msg.v) || 0)); break;
      case 'validate': this.validate(player, Number(msg.id)); break;
      case 'vote': this.vote(player, msg.target); break;
      case 'rtc': {
        const to = this.players.get(msg.to);
        if (to) this.send(to, { t: 'rtc', from: player.id, data: msg.data });
        break;
      }
    }
  }

  start(player) {
    if (!player.host || (this.phase !== 'LOBBY' && this.phase !== 'OVER')) return;
    const list = [...this.players.values()].filter((p) => p.connected);
    if (list.length < CONFIG.MIN_PLAYERS)
      return this.send(player, { t: 'error', msg: `Il faut au moins ${CONFIG.MIN_PLAYERS} joueurs.` });
    for (const p of this.players.values()) if (!p.connected) this.players.delete(p.id);
    const volunteers = list.filter((p) => p.wantsOperator);
    const operator = pick(volunteers.length ? volunteers : list);
    const field = shuffle(list.filter((p) => p !== operator));
    for (const p of list) Object.assign(p, { role: 'infiltrator', ejected: false, alive: true, vote: null });
    operator.role = 'operator';
    field[0].role = 'mole';
    this.gameId++;
    this.found = 0;
    this.lost = 0;
    this.winner = null;
    this.log = [];
    this.addLog('Protocole Subterfuge engagé. Bonne chance, agents.', 'alert');
    this.startRound(1);
  }

  backToLobby() {
    this.phase = 'LOBBY';
    this.winner = null;
    for (const p of this.players.values()) Object.assign(p, { role: null, alive: true, ejected: false, vote: null });
  }

  startRound(n) {
    this.round = n;
    this.phase = 'CLUE';
    this.roundTimer = CONFIG.ROUND_SECONDS;
    const words = shuffle(WORDS).slice(0, 16);
    const aligns = shuffle(ALIGNMENTS);
    this.board = words.map((word, i) => ({ word, align: aligns[i], state: 'hidden' }));
    this.clue = null;
    this.guessesLeft = 0;
    this.cluePending = false;
    this.crisis = 1;
    this.crisisClock = 0;
    this.lastTerminalStatus = 'NEUTRAL';
    this.activeSector = sectorAt(SPAWN.x, SPAWN.y);
    this.directorClock = 0;
    this.directorPending = false;
    this.monster = {
      x: MONSTER_SPAWN.x + 0.5, y: MONSTER_SPAWN.y + 0.5, behavior: 'PATROL_DEFAULT',
      path: [], retarget: 0, stunUntil: Date.now() + 8000,
    };
    const field = this.fieldPlayers().filter((p) => !p.ejected);
    field.forEach((p, i) => {
      p.alive = true;
      p.vote = null;
      p.x = SPAWN.x + 0.5 + (i - (field.length - 1) / 2) * 1.2;
      p.y = SPAWN.y + 0.5;
      p.lastPosAt = Date.now();
      this.send(p, { t: 'correct', x: p.x, y: p.y });
    });
    this.addLog(`Manche ${n}/${CONFIG.ROUNDS} — l'Opérateur analyse la grille.`, 'round');
  }

  async submitClue(player, word, count) {
    if (this.phase !== 'CLUE' || player.role !== 'operator' || this.cluePending) return;
    count = Math.floor(Number(count));
    if (!(count >= 1 && count <= 4)) return this.send(player, { t: 'clueRejected', reason: 'Nombre entre 1 et 4.' });
    const gameId = this.gameId, round = this.round;
    this.cluePending = true;
    const t0 = Date.now();
    const res = await validateOperatorClue(String(word || ''), this.board.map((b) => b.word));
    this.cluePending = false;
    if (gameId !== this.gameId || round !== this.round || this.phase !== 'CLUE') return;
    if (!res.valid) return this.send(player, { t: 'clueRejected', reason: res.reason });
    this.clue = { word: String(word).trim().toUpperCase(), count, ms: Date.now() - t0, source: res.source, kevP: res.probability };
    this.guessesLeft = count + 1;
    this.phase = 'FIELD';
    this.addLog(`Indice transmis : « ${this.clue.word} » ${count}`, 'clue');
  }

  updatePos(p, { x, y, a }) {
    if (!['CLUE', 'FIELD', 'EXTRACTION'].includes(this.phase)) return;
    if (p.role === 'operator' || !p.alive || !Number.isFinite(x) || !Number.isFinite(y)) return;
    const now = Date.now();
    const dt = Math.min(1, (now - p.lastPosAt) / 1000);
    const maxD = CONFIG.PLAYER_SPEED * dt * 1.6 + 0.35;
    if (Math.hypot(x - p.x, y - p.y) <= maxD && circleFree(x, y)) {
      p.x = x; p.y = y;
      if (Number.isFinite(a)) p.a = a;
      p.lastPosAt = now;
    } else {
      this.send(p, { t: 'correct', x: p.x, y: p.y });
    }
  }

  validate(p, id) {
    if (this.phase !== 'FIELD' || p.role === 'operator' || !p.alive) return;
    const term = TERMINALS[id], cell = this.board?.[id];
    if (!term || !cell || cell.state !== 'hidden') return;
    if (Math.hypot(p.x - (term.x + 0.5), p.y - (term.y + 0.5)) > CONFIG.INTERACT_RADIUS) return;
    this.activeSector = sectorAt(term.x, term.y);
    const who = p.name;
    switch (cell.align) {
      case 'TARGET': {
        cell.state = 'found';
        this.found++;
        this.guessesLeft--;
        this.lastTerminalStatus = 'SUCCESS';
        this.addLog(`${who} a extrait « ${cell.word} » : Données Cibles récupérées.`, 'success');
        if (!this.board.some((b) => b.align === 'TARGET' && b.state === 'hidden')) return this.startExtraction();
        if (this.guessesLeft <= 0) this.endClue('Quota de validations atteint.');
        return;
      }
      case 'NEUTRAL':
        cell.state = 'revealed';
        this.lastTerminalStatus = 'NEUTRAL';
        this.addLog(`${who} a validé « ${cell.word} » : donnée neutre.`, 'neutral');
        this.assessMistake(cell);
        return this.endClue('Nœud neutre, retour à l’Opérateur.');
      case 'TRAP': {
        cell.state = 'revealed';
        this.lastTerminalStatus = 'TRAP';
        const victim = pick(this.board.filter((b) => b.align === 'TARGET' && b.state === 'hidden'));
        if (victim) { victim.state = 'lost'; this.lost++; }
        this.addLog(`ALARME ! « ${cell.word} » était un Piège de Sécurité. Une banque de données est corrompue.`, 'trap');
        this.assessMistake(cell);
        this.runDirector();
        if (this.lost > TOTAL_BANKS - NEED_BANKS)
          return this.end('mole', 'Trop de banques corrompues : 75 % impossible à atteindre.');
        if (!this.board.some((b) => b.align === 'TARGET' && b.state === 'hidden')) return this.startExtraction();
        return this.endClue('Piège déclenché.');
      }
      case 'FATAL':
        cell.state = 'revealed';
        this.addLog(`« ${cell.word} » était le PROTOCOLE FATAL.`, 'fatal');
        return this.end('mole', 'Protocole Fatal validé par ' + who + '.');
    }
  }

  endClue(reason) {
    this.phase = 'CLUE';
    this.clue = null;
    this.guessesLeft = 0;
    this.addLog(reason);
  }

  async assessMistake(cell) {
    const gameId = this.gameId;
    const score = await evaluateMistakeSeverity(cell.word, this.clue?.word || '?', cell.align);
    if (gameId !== this.gameId) return;
    this.crisis = Math.max(this.crisis, score);
    this.crisisClock = 0;
    this.addLog(`Kev évalue l'erreur « ${cell.word} » : crise ${score}/5.`, 'kev');
  }

  startExtraction() {
    this.phase = 'EXTRACTION';
    this.clue = null;
    this.extractionTimer = CONFIG.EXTRACTION_SECONDS;
    for (const p of this.players.values()) p.vote = null;
    this.addLog('Ascenseur d’extraction OUVERT ! 30 s pour l’atteindre et voter l’éjection d’un suspect.', 'alert');
  }

  vote(p, target) {
    if (this.phase !== 'EXTRACTION' || p.ejected || (p.role !== 'operator' && !p.alive)) return;
    if (target === 'skip') { p.vote = 'skip'; return; }
    const t = this.players.get(target);
    if (t && t.role !== 'operator' && !t.ejected && t !== p) p.vote = target;
  }

  resolveExtraction() {
    const tally = {};
    for (const p of this.players.values()) if (p.vote && p.vote !== 'skip') tally[p.vote] = (tally[p.vote] || 0) + 1;
    const sorted = Object.entries(tally).sort((a, b) => b[1] - a[1]);
    if (sorted.length && (sorted.length === 1 || sorted[0][1] > sorted[1][1])) {
      const ej = this.players.get(sorted[0][0]);
      if (ej.role === 'mole') return this.end('team', `${ej.name} était la Taupe : verrouillée par le vote.`);
      ej.ejected = true;
      ej.alive = false;
      this.addLog(`${ej.name} a été éjecté… c'était un Infiltré.`, 'trap');
    } else {
      this.addLog('Vote sans majorité : personne n’est éjecté.');
    }
    const extracted = this.fieldPlayers().filter((p) => p.role === 'infiltrator' && p.alive && inElevator(p.x, p.y));
    if (!extracted.length) return this.end('mole', 'Aucun Infiltré ne s’est extrait vivant.');
    this.addLog(`${extracted.length} Infiltré(s) extrait(s). Banques : ${this.found}/${TOTAL_BANKS}.`, 'success');
    if (this.round >= CONFIG.ROUNDS) {
      return this.found >= NEED_BANKS
        ? this.end('team', `Extraction réussie avec ${this.found}/${TOTAL_BANKS} banques de données.`)
        : this.end('mole', `Seulement ${this.found}/${TOTAL_BANKS} banques : objectif de 75 % manqué.`);
    }
    this.startRound(this.round + 1);
  }

  end(side, reason) {
    this.phase = 'OVER';
    this.winner = { side, reason };
    this.addLog(side === 'team' ? `VICTOIRE DE L'ÉQUIPE — ${reason}` : `VICTOIRE DE LA TAUPE — ${reason}`, 'alert');
  }

  // ───────────── Directeur d'IA & Patrouilleur ─────────────
  loudest() {
    const alive = this.fieldPlayers().filter((p) => p.alive);
    return alive.sort((a, b) => b.vol - a.vol || dist(a, this.monster) - dist(b, this.monster))[0];
  }

  async runDirector() {
    if (this.directorPending) return;
    this.directorPending = true;
    this.directorClock = 0;
    const gameId = this.gameId;
    const loud = this.loudest();
    if (loud && loud.vol > 0.2 && this.lastTerminalStatus !== 'TRAP') this.activeSector = sectorAt(loud.x, loud.y);
    const context = {
      ambientVolume: Math.round(Math.max(0, ...this.fieldPlayers().filter((p) => p.alive).map((p) => p.vol)) * 100) / 100,
      lastTerminalStatus: this.lastTerminalStatus,
      activeSector: this.activeSector,
    };
    this.lastTerminalStatus = 'NEUTRAL';
    const behavior = await directMonsterBehavior(context);
    this.directorPending = false;
    if (gameId !== this.gameId || !this.monster) return;
    this.setBehavior(behavior);
  }

  setBehavior(b) {
    const m = this.monster;
    if (m.behavior !== b) this.addLog(`Directeur Kev : Patrouilleur → ${b}`, 'kev');
    m.behavior = b;
    m.path = [];
    m.retarget = 0;
    if (b === 'LOCKDOWN_VENT') {
      const vent = VENTS.find((v) => sectorAt(v.x, v.y) === this.activeSector) || pick(VENTS);
      m.x = vent.x + 0.5;
      m.y = vent.y + 0.5;
    }
  }

  updateMonster(dt) {
    const m = this.monster;
    const now = Date.now();
    if (now >= m.stunUntil) {
      m.retarget -= dt;
      if (m.behavior === 'HUNT_LOUDEST' && m.retarget <= 0) {
        const target = this.loudest();
        if (target) m.path = findPath(m.x, m.y, target.x, target.y);
        m.retarget = 0.5;
      } else if ((m.behavior === 'PATROL_DEFAULT' || m.behavior === 'INVESTIGATE_SECTOR') && !m.path.length) {
        const pool = m.behavior === 'PATROL_DEFAULT' ? FLOOR_TILES : SECTOR_TILES[this.activeSector] || FLOOR_TILES;
        const dest = pick(pool);
        m.path = findPath(m.x, m.y, dest.x, dest.y);
      }
      let step = MONSTER_SPEED[m.behavior] * (1 + 0.06 * (this.crisis - 1)) * dt;
      while (step > 0 && m.path.length) {
        const n = m.path[0];
        const tx = n.x + 0.5, ty = n.y + 0.5;
        const d = Math.hypot(tx - m.x, ty - m.y);
        if (d <= step) { m.x = tx; m.y = ty; step -= d; m.path.shift(); }
        else { m.x += ((tx - m.x) / d) * step; m.y += ((ty - m.y) / d) * step; step = 0; }
      }
    }
    for (const p of this.fieldPlayers()) {
      if (!p.alive || dist(p, m) > CONFIG.CATCH_RADIUS) continue;
      p.alive = false;
      p.vol = 0;
      m.stunUntil = now + 3000;
      m.behavior = 'PATROL_DEFAULT';
      m.path = [];
      this.addLog(`${p.name} a été capturé par le Patrouilleur. Liaison radio coupée.`, 'caught');
    }
    const infiltrators = this.fieldPlayers().filter((p) => p.role === 'infiltrator' && !p.ejected);
    if (infiltrators.length && infiltrators.every((p) => !p.alive))
      this.end('mole', 'Tous les Infiltrés ont été neutralisés.');
  }

  // ───────────── Boucle ─────────────
  tick() {
    const dt = TICK_MS / 1000;
    const connected = [...this.players.values()].some((p) => p.connected);
    if (!connected) {
      this.emptySince ??= Date.now();
      if (Date.now() - this.emptySince > 60000) this.onEmpty(this);
      return;
    }
    this.emptySince = null;
    if (this.phase === 'CLUE' || this.phase === 'FIELD') {
      this.roundTimer -= dt;
      if (this.roundTimer <= 0) this.end('mole', 'Le compte à rebours a expiré.');
    } else if (this.phase === 'EXTRACTION') {
      this.extractionTimer -= dt;
      if (this.extractionTimer <= 0) this.resolveExtraction();
    }
    if (['CLUE', 'FIELD', 'EXTRACTION'].includes(this.phase)) {
      this.directorClock += dt;
      if (this.directorClock >= CONFIG.DIRECTOR_INTERVAL) this.runDirector();
      this.crisisClock += dt;
      if (this.crisisClock > 20 && this.crisis > 1) { this.crisis--; this.crisisClock = 0; }
      this.updateMonster(dt);
    }
    this.broadcast();
  }

  broadcast() {
    const over = this.phase === 'OVER';
    const inGame = this.phase !== 'LOBBY';
    const players = [...this.players.values()].map((p) => ({
      id: p.id, name: p.name, host: p.host, connected: p.connected, wantsOperator: p.wantsOperator,
      publicRole: p.role === 'operator' ? 'operator' : p.role ? 'field' : null,
      role: over ? p.role : undefined,
      x: p.x, y: p.y, a: p.a, alive: p.alive, ejected: p.ejected,
      vol: Math.round(p.vol * 20) / 20, voted: !!p.vote,
    }));
    const votes = {};
    if (this.phase === 'EXTRACTION')
      for (const p of this.players.values()) if (p.vote) votes[p.vote] = (votes[p.vote] || 0) + 1;
    const base = {
      t: 'state', code: this.code, phase: this.phase, round: this.round || 0, rounds: CONFIG.ROUNDS,
      timer: inGame ? Math.max(0, Math.ceil(this.roundTimer)) : 0,
      extractionTimer: this.phase === 'EXTRACTION' ? Math.ceil(this.extractionTimer) : 0,
      players, clue: this.clue, guessesLeft: this.guessesLeft, cluePending: this.cluePending,
      data: { found: this.found || 0, lost: this.lost || 0, total: TOTAL_BANKS, need: NEED_BANKS },
      crisis: this.crisis || 1, votes, winner: this.winner, log: this.log,
      minPlayers: CONFIG.MIN_PLAYERS, maxPlayers: CONFIG.MAX_PLAYERS,
    };
    for (const p of this.players.values()) {
      if (!p.ws) continue;
      const seesAll = over || p.role === 'operator';
      const m = this.monster;
      let monster = null;
      if (inGame && m && (seesAll || p.role === 'mole' || !p.alive || dist(p, m) < 12))
        monster = { x: m.x, y: m.y, behavior: seesAll || p.role === 'mole' ? m.behavior : undefined };
      this.send(p, {
        ...base,
        you: { id: p.id, role: p.role, alive: p.alive, vote: p.vote },
        board: inGame && this.board
          ? this.board.map((b) => ({ word: b.word, state: b.state, align: seesAll || b.state !== 'hidden' ? b.align : undefined }))
          : null,
        monster,
      });
    }
  }
}

export { MAP_PAYLOAD };

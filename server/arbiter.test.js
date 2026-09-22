import test from 'node:test';
import assert from 'node:assert/strict';
import { lexicalClueCheck, fallbackBehavior, validateOperatorClue } from './arbiter.js';
import { findPath, TERMINALS, SPAWN, ELEVATOR, isSolid } from './map.js';

const board = ['RIVIÈRE', 'CHAT', 'MONTAGNE', 'SOLEIL'];

test('rejette mots identiques, racines, composés et quasi-homophones', () => {
  assert.equal(lexicalClueCheck('riviere', board).ok, false);
  assert.equal(lexicalClueCheck('Montagnard', board).ok, false);
  assert.equal(lexicalClueCheck('Chaton', board).ok, false);
  assert.equal(lexicalClueCheck('Tournesoleil', board).ok, false);
  assert.equal(lexicalClueCheck('chats', board).ok, false);
  assert.equal(lexicalClueCheck('deux mots', board).ok, false);
});

test('accepte un indice sémantique propre', () => {
  assert.equal(lexicalClueCheck('Eau', board).ok, true);
  assert.equal(lexicalClueCheck('Félin', board).ok, true);
});

test('validateOperatorClue fonctionne sans Kev (repli)', async () => {
  assert.equal((await validateOperatorClue('Félin', board)).valid, true);
  assert.equal((await validateOperatorClue('Chaton', board)).valid, false);
});

test('le repli du directeur traque après un piège', () => {
  assert.equal(fallbackBehavior({ ambientVolume: 0, lastTerminalStatus: 'TRAP' }), 'HUNT_LOUDEST');
  assert.equal(fallbackBehavior({ ambientVolume: 0.4, lastTerminalStatus: 'NEUTRAL' }), 'INVESTIGATE_SECTOR');
});

test('tous les terminaux et l’ascenseur sont accessibles depuis le spawn', () => {
  const near = [[1, 0], [-1, 0], [0, 1], [0, -1]];
  for (const t of TERMINALS) {
    const ok = near.some(([dx, dy]) => !isSolid(t.x + dx, t.y + dy) && findPath(SPAWN.x, SPAWN.y, t.x + dx, t.y + dy).length);
    assert.ok(ok, `terminal ${t.id} inaccessible`);
  }
  assert.ok(findPath(SPAWN.x, SPAWN.y, ELEVATOR.x0, ELEVATOR.y0).length);
});

test('le client kev parle le contrat /v1/systemone', async () => {
  const http = await import('node:http');
  let seen;
  const srv = http.createServer((req, res) => {
    let b = '';
    req.on('data', (c) => (b += c));
    req.on('end', () => {
      seen = JSON.parse(b);
      const q = seen.questions.q;
      const a = q.type === 'noul' ? { type: 'noul', noul: 0.2 }
        : q.type === 'choice' ? { type: 'choice', choice: Object.keys(q.criteria)[2], confidence: 0.7, probabilities: {} }
        : { type: 'score', score: 3.4, legend: {}, probabilities: {}, confidence: 0.6 };
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ model: 'kev-latest', answers: { q: a }, usage: {}, latency_ms: 1 }));
    });
  });
  await new Promise((r) => srv.listen(0, r));
  process.env.KEV_URL = `http://127.0.0.1:${srv.address().port}`;
  const { kev } = await import(`./kev.js?t=${Date.now()}`);
  assert.deepEqual(await kev.bool({ input: { a: 1 }, instruction: 'x' }), { value: false, probability: 0.2 });
  assert.equal(seen.model, 'kev-latest');
  assert.deepEqual(seen.state, { a: 1 });
  assert.equal((await kev.choice({ input: 's', instruction: 'x', choices: ['A', 'B', 'C'] })).choice, 'C');
  assert.deepEqual(seen.questions.q.criteria, { A: '', B: '', C: '' });
  const s = await kev.score({ input: 's', instruction: 'x', min: 1, max: 5 });
  assert.equal(s.score, 4);
  assert.equal(seen.questions.q.criteria.length, 5);
  srv.close();
});

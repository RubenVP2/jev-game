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

test('validateOperatorClue fonctionne sans Ollama (repli)', async () => {
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

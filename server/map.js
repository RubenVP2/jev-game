// Carte du complexe : 1 tuile = 1 mètre virtuel.
// '#' mur, '.' sol, 'T' terminal (solide), 'E' zone ascenseur, 'V' conduit d'aération.
export const W = 40;
export const H = 27;

const grid = Array.from({ length: H }, () => Array(W).fill('#'));
const rect = (x0, y0, x1, y1, c) => {
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) grid[y][x] = c;
};

// Six salles (3 colonnes x 2 rangées) + couloir central.
rect(1, 1, 12, 11, '.'); rect(14, 1, 25, 11, '.'); rect(27, 1, 38, 11, '.');
rect(1, 15, 12, 25, '.'); rect(14, 15, 25, 25, '.'); rect(27, 15, 38, 25, '.');
rect(1, 13, 38, 13, '.');
// Portes entre salles et vers le couloir.
for (const [x, y] of [[13, 5], [13, 6], [26, 5], [26, 6], [13, 20], [13, 21], [26, 20], [26, 21]]) grid[y][x] = '.';
for (const x of [6, 7, 19, 20, 32, 33]) { grid[12][x] = '.'; grid[14][x] = '.'; }
// Obstacles intérieurs (baies de serveurs, caisses).
rect(5, 5, 7, 6, '#'); rect(18, 5, 21, 5, '#'); rect(31, 6, 33, 8, '#');
rect(6, 18, 8, 19, '#'); rect(15, 19, 16, 20, '#'); rect(31, 19, 34, 19, '#');
// Ascenseur d'extraction (salle E, en bas au centre).
rect(17, 22, 22, 25, 'E');

export const TERMINALS = [
  [3, 2], [10, 2], [3, 10],
  [16, 2], [23, 2], [19, 9],
  [29, 2], [36, 2], [36, 10],
  [3, 16], [10, 24], [3, 24],
  [16, 16], [23, 16],
  [29, 16], [36, 24],
].map(([x, y], id) => ({ id, x, y }));
for (const t of TERMINALS) grid[t.y][t.x] = 'T';

export const VENTS = [[10, 9], [24, 9], [29, 9], [10, 17], [24, 24], [29, 23]].map(([x, y]) => ({ x, y }));
for (const v of VENTS) grid[v.y][v.x] = 'V';

export const TILES = grid.map((r) => r.join(''));
export const ELEVATOR = { x0: 17, y0: 22, x1: 22, y1: 25 };
export const SPAWN = { x: 20, y: 13 };
export const MONSTER_SPAWN = { x: 35, y: 4 };

export const SECTORS = ['Serveurs', 'Archives', 'Réacteur', 'Laboratoire', 'Ascenseur', 'Maintenance'];
export function sectorAt(x, y) {
  const col = x < 13 ? 0 : x < 26 ? 1 : 2;
  const row = y < 13 ? 0 : 1;
  return SECTORS[row * 3 + col];
}

export const isSolid = (tx, ty) => {
  if (tx < 0 || ty < 0 || tx >= W || ty >= H) return true;
  const c = TILES[ty][tx];
  return c === '#' || c === 'T';
};

export const inElevator = (x, y) =>
  x >= ELEVATOR.x0 && x < ELEVATOR.x1 + 1 && y >= ELEVATOR.y0 && y < ELEVATOR.y1 + 1;

// Cercle de rayon r centré en (x,y) libre de murs ?
export function circleFree(x, y, r = 0.3) {
  for (const [dx, dy] of [[-r, -r], [r, -r], [-r, r], [r, r]]) {
    if (isSolid(Math.floor(x + dx), Math.floor(y + dy))) return false;
  }
  return true;
}

export function hasLineOfSight(ax, ay, bx, by) {
  const d = Math.hypot(bx - ax, by - ay);
  const steps = Math.ceil(d / 0.2);
  for (let i = 1; i < steps; i++) {
    const t = i / steps;
    const c = TILES[Math.floor(ay + (by - ay) * t)]?.[Math.floor(ax + (bx - ax) * t)];
    if (c === '#') return false;
  }
  return true;
}

export const FLOOR_TILES = [];
for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (!isSolid(x, y)) FLOOR_TILES.push({ x, y });

// BFS sur la grille (4-connexe) ; renvoie la liste des tuiles jusqu'à la cible.
export function findPath(sx, sy, tx, ty) {
  sx = Math.floor(sx); sy = Math.floor(sy); tx = Math.floor(tx); ty = Math.floor(ty);
  if (isSolid(tx, ty)) return [];
  const prev = new Int32Array(W * H).fill(-1);
  const start = sy * W + sx, goal = ty * W + tx;
  prev[start] = start;
  const q = [start];
  for (let i = 0; i < q.length; i++) {
    const cur = q[i];
    if (cur === goal) break;
    const cx = cur % W, cy = (cur / W) | 0;
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const nx = cx + dx, ny = cy + dy, n = ny * W + nx;
      if (!isSolid(nx, ny) && prev[n] === -1) { prev[n] = cur; q.push(n); }
    }
  }
  if (prev[goal] === -1) return [];
  const path = [];
  for (let c = goal; c !== start; c = prev[c]) path.push({ x: c % W, y: (c / W) | 0 });
  return path.reverse();
}

export const MAP_PAYLOAD = { w: W, h: H, tiles: TILES, terminals: TERMINALS, elevator: ELEVATOR, vents: VENTS };

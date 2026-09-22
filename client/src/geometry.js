// Utilitaires de géométrie côté client (miroir de server/map.js).
export function makeGeo(map) {
  const { w, h, tiles, elevator } = map;
  const tile = (x, y) => (x < 0 || y < 0 || x >= w || y >= h ? '#' : tiles[y][x]);
  const solid = (x, y) => { const c = tile(x, y); return c === '#' || c === 'T'; };
  const wall = (x, y) => tile(Math.floor(x), Math.floor(y)) === '#';
  return {
    tile, solid, wall,
    circleFree(x, y, r = 0.3) {
      return [[-r, -r], [r, -r], [-r, r], [r, r]].every(([dx, dy]) => !solid(Math.floor(x + dx), Math.floor(y + dy)));
    },
    los(ax, ay, bx, by) {
      const steps = Math.ceil(Math.hypot(bx - ax, by - ay) / 0.2);
      for (let i = 1; i < steps; i++) {
        const t = i / steps;
        if (wall(ax + (bx - ax) * t, ay + (by - ay) * t)) return false;
      }
      return true;
    },
    ray(x, y, ang, max) {
      const dx = Math.cos(ang), dy = Math.sin(ang);
      for (let d = 0; d < max; d += 0.1) if (wall(x + dx * d, y + dy * d)) return d;
      return max;
    },
    inElevator: (x, y) => x >= elevator.x0 && x < elevator.x1 + 1 && y >= elevator.y0 && y < elevator.y1 + 1,
  };
}

export const angleDiff = (a, b) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));

export const colorFor = (id) => {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${(h * 47) % 360} 80% 60%)`;
};

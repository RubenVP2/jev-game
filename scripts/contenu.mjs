// Récupère le contenu de Matou depuis le dépôt des vidéos (RubenVP2/vids-for-rs, public) :
// les épisodes (article, scènes, envoi Postiz, miniature) et la marque (couleurs, Matou,
// icônes). Rien n'est recopié à la main : chaque build part de la branche main des vidéos.
//
// Usage : node scripts/contenu.mjs
//   CONTENU_LOCAL=../vids-for-rs  prend un clone local au lieu de GitHub (pour travailler hors ligne)
//   CONTENU_DEPOT, CONTENU_BRANCHE  changent la source (défaut : vids-for-rs, main)
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const RACINE = path.resolve(import.meta.dirname, '..');
const CIBLE = path.join(RACINE, 'contenu');
const DEPOT = process.env.CONTENU_DEPOT ?? 'https://github.com/RubenVP2/vids-for-rs.git';
const BRANCHE = process.env.CONTENU_BRANCHE ?? 'main';

// Seuls ces fichiers servent au site : pas de voix ni de vidéo (le dépôt grossit chaque jour).
const MOTIFS = [
  '/episodes/*/article.md',
  '/episodes/*/scenes.json',
  '/episodes/*/postiz-envoi.json',
  '/episodes/*/miniature.jpg',
  '/brand/tokens.json',
  '/brand/mascotte/',
  '/brand/icones/',
];

function copier(source) {
  for (const dossier of ['episodes', 'brand']) {
    fs.cpSync(path.join(source, dossier), path.join(CIBLE, dossier), {
      recursive: true,
      filter: (f) => !/\.(mp3|mp4|wav|png)$/.test(f),
    });
  }
}

fs.rmSync(CIBLE, {recursive: true, force: true});
fs.mkdirSync(CIBLE);

if (process.env.CONTENU_LOCAL) {
  const local = path.resolve(RACINE, process.env.CONTENU_LOCAL);
  copier(local);
  console.log(`Contenu copié depuis ${local}`);
} else {
  const tmp = path.join(RACINE, '.contenu-git');
  fs.rmSync(tmp, {recursive: true, force: true});
  const git = (...args) => execFileSync('git', args, {cwd: tmp, stdio: ['ignore', 'ignore', 'inherit']});
  execFileSync('git', ['clone', '--quiet', '--depth', '1', '--filter=blob:none', '--no-checkout', '--branch', BRANCHE, DEPOT, tmp], {stdio: 'inherit'});
  git('sparse-checkout', 'set', '--no-cone', ...MOTIFS);
  git('checkout', '--quiet');
  const commit = execFileSync('git', ['rev-parse', '--short', 'HEAD'], {cwd: tmp}).toString().trim();
  copier(tmp);
  fs.rmSync(tmp, {recursive: true, force: true});
  console.log(`Contenu récupéré : ${DEPOT} (${BRANCHE}, ${commit})`);
}

const episodes = fs.readdirSync(path.join(CIBLE, 'episodes')).filter((d) => fs.existsSync(path.join(CIBLE, 'episodes', d, 'article.md')));
console.log(`${episodes.length} épisode(s) avec un article.`);

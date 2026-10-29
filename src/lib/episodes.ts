// Relie un article à son épisode : scenes.json (numéro, source, statut, verdict) et
// postiz-envoi.json (date de diffusion). Un article n'est en ligne que si la vidéo a été
// programmée par l'utilisateur et que sa date est passée : le site suit la relecture humaine.
import fs from 'node:fs';
import path from 'node:path';
import type {ImageMetadata} from 'astro';
import {getCollection, type CollectionEntry} from 'astro:content';
import {fr} from './typo.mjs';

const EPISODES = path.resolve(process.cwd(), 'contenu/episodes');
if (!fs.existsSync(EPISODES)) {
  throw new Error(`Dossier des épisodes introuvable (${EPISODES}) : lancer « npm run contenu » à la racine du site.`);
}

export type Statut = 'annonce' | 'disponible' | 'rumeur';
export type Verdict = 'buzz' | 'prometteur' | 'gameChanger';

type Scenes = {
  numero: number;
  slug: string;
  serie: 'flash' | 'decrypte';
  source: {nom: string; url: string; date: string; type: string};
  statut: Statut;
  verdict: Verdict;
  scenes: {type: string; raison?: string}[];
};
type Envoi = {date: string; statut: 'brouillon' | 'programmé'};

export type Article = {
  id: string;
  slug: string;
  numero: string;
  serie: Scenes['serie'];
  titre: string;
  description: string;
  source: Scenes['source'];
  statut: Statut;
  verdict: Verdict;
  raison?: string;
  date: Date;
  miniature?: ImageMetadata;
  entree: CollectionEntry<'articles'>;
};

const miniatures = import.meta.glob<ImageMetadata>('@contenu/episodes/*/miniature.jpg', {eager: true, import: 'default'});
const miniature = (id: string) => Object.entries(miniatures).find(([f]) => f.endsWith(`/${id}/miniature.jpg`))?.[1];

function lire<T>(dossier: string, fichier: string): T | undefined {
  const f = path.join(EPISODES, dossier, fichier);
  return fs.existsSync(f) ? (JSON.parse(fs.readFileSync(f, 'utf8')) as T) : undefined;
}

let cache: Article[] | undefined;

/** Articles en ligne, du plus récent au plus ancien. */
export async function articles(): Promise<Article[]> {
  if (cache) return cache;
  const maintenant = Date.now();
  const liste: Article[] = [];
  for (const entree of await getCollection('articles')) {
    const scenes = lire<Scenes>(entree.id, 'scenes.json');
    const envoi = lire<Envoi>(entree.id, 'postiz-envoi.json');
    if (!scenes || envoi?.statut !== 'programmé') continue;
    const date = new Date(envoi.date);
    if (date.getTime() > maintenant) continue;
    liste.push({
      id: entree.id,
      slug: scenes.slug,
      numero: String(scenes.numero).padStart(3, '0'),
      serie: scenes.serie,
      titre: fr(entree.data.titre),
      description: fr(entree.data.description),
      source: scenes.source,
      statut: scenes.statut,
      verdict: scenes.verdict,
      raison: ((r) => r && fr(r))(scenes.scenes.find((s) => s.type === 'verdict')?.raison),
      date,
      miniature: miniature(entree.id),
      entree,
    });
  }
  cache = liste.sort((a, b) => b.date.getTime() - a.date.getTime());
  return cache;
}

/** `==mot==` (surligneur des scènes) → <mark>, le reste échappé. */
export function surligner(texte: string): string {
  const echappe = texte.replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]!);
  return echappe.replace(/==(.+?)==/g, '<mark>$1</mark>');
}

export const SERIES = {flash: 'Flash', decrypte: 'Décrypté'} as const;

export function dateLongue(d: Date): string {
  return d.toLocaleDateString('fr-FR', {day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Europe/Paris'});
}

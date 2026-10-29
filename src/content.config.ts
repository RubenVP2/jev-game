import {defineCollection} from 'astro:content';
import {glob} from 'astro/loaders';
import {z} from 'astro/zod';

// Un article par épisode : episodes/NNN-slug/article.md du dépôt des vidéos (skill « article »),
// récupéré dans contenu/ par scripts/contenu.mjs.
// Le reste (numéro, source, statut, verdict, date) vient des fichiers de l'épisode.
const articles = defineCollection({
  loader: glob({pattern: '*/article.md', base: './contenu/episodes', generateId: ({entry}) => entry.split('/')[0]}),
  schema: z.object({
    titre: z.string().max(65),
    description: z.string().min(80).max(165),
  }),
});

export const collections = {articles};

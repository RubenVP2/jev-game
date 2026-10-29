import {fileURLToPath} from 'node:url';
import sitemap from '@astrojs/sitemap';
import {defineConfig} from 'astro/config';
import {rehypeFr} from './src/lib/typo.mjs';

// L'adresse publique du site sert aux liens canoniques, au plan du site et au flux RSS.
// En build sur Cloudflare (WORKERS_CI), elle est obligatoire : sans elle, Google
// verrait des liens canoniques faux.
const url = process.env.SITE_URL;
if (!url && process.env.WORKERS_CI) {
  throw new Error('SITE_URL manquante : la définir dans les variables de build du Worker (ex. https://matou.ai).');
}

export default defineConfig({
  site: url ?? 'http://localhost:4321',
  trailingSlash: 'always',
  build: {format: 'directory', inlineStylesheets: 'always'},
  prefetch: {prefetchAll: false, defaultStrategy: 'hover'},
  integrations: [sitemap({filter: (page) => !page.endsWith('/liens/')})],
  markdown: {rehypePlugins: [rehypeFr]},
  // épisodes et marque du dépôt des vidéos, récupérés dans contenu/ (scripts/contenu.mjs)
  vite: {resolve: {alias: {'@contenu': fileURLToPath(new URL('./contenu', import.meta.url))}}},
});

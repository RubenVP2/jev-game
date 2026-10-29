import rss from '@astrojs/rss';
import type {APIRoute} from 'astro';
import {MARQUE} from '../config';
import {articles} from '../lib/episodes';

export const GET: APIRoute = async ({site}) =>
  rss({
    title: `${MARQUE.nom} · le blog`,
    description: MARQUE.description,
    site: site!,
    trailingSlash: true,
    customData: '<language>fr-FR</language>',
    items: (await articles()).map((a) => ({
      title: a.titre,
      description: a.description,
      link: `/blog/${a.slug}/`,
      pubDate: a.date,
    })),
  });

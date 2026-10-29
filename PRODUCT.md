# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Principal** : la personne qui vient de voir une vidéo de Matou sur TikTok, Instagram,
  YouTube Shorts ou Threads et touche le lien en bio. Elle est sur son téléphone, entre deux
  vidéos, avec peu d'attention. Le site doit lui faire comprendre Matou en quelques
  secondes, puis l'envoyer s'abonner ou lire un article.
- **Secondaire** : le lecteur arrivé de Google sur un article, qui cherche une actu IA
  précise expliquée simplement.
- **À venir** : marques et partenaires qui veulent travailler avec Matou (contact).

Grand public et pros hors tech : aucun jargon non expliqué.

## Product Purpose

Le site de Matou (`@matou_ai`), « l'actu de l'IA en 30 secondes, un chat t'explique ».
Il reçoit le trafic des réseaux (lien en bio), donne une version texte de chaque vidéo
(blog, trouvable sur Google) et prépare la création de valeur : newsletter et contact
partenariats.

Réussite : un visiteur venu d'une vidéo s'abonne sur un réseau, lit un article, ou
(plus tard) laisse son e-mail.

## Positioning

Une mascotte dessinée à la main par l'auteur (Matou, chat blanc à lunettes) qui trie
l'actu IA avec des rituels propres : tampon annoncé / disponible / rumeur, « En fait… »,
Hype-mètre (pur buzz / prometteur / game changer), toujours la source. Une idée par vidéo.

## Operating Context

- Une vidéo par jour, produite par une routine dans le dépôt des vidéos
  (RubenVP2/vids-for-rs) ; chaque épisode devient un article (`episodes/NNN-slug/article.md`), en ligne seulement quand l'utilisateur a programmé la
  vidéo et que sa date est passée.
- Site Astro statique dans ce dépôt, séparé des vidéos. Il récupère épisodes et marque au
  build (`scripts/contenu.mjs`) et se publie sur Cloudflare Workers toutes les heures
  (GitHub Actions).

## Capabilities and Constraints

- Statique, zéro JavaScript côté client par défaut ; perf et SEO maximaux (Lighthouse 100
  visé sur toutes les catégories).
- Français uniquement.
- Comptes : `@matou_ai` sur TikTok, Instagram, Threads, YouTube ; page LinkedIn « Matou AI »
  (adresse non connue).
- **Ouvert** : service de newsletter (aucun choisi) ; adresse e-mail de contact
  partenariats (non fournie) ; nom de domaine (non fourni, variable `SITE_URL`) ; mentions
  légales (éditeur non fourni).

## Brand Commitments

- Univers « cahier de Matou », identique aux vidéos (dépôt vids-for-rs) : `docs/design-system.md`,
  `brand/tokens.json`, Matou en SVG (`brand/mascotte/`), polices Permanent Marker et
  Shantell Sans. Choix confirmé par l'utilisateur pour le site.
- Ton : pédagogie d'abord, humour pince-sans-rire, tutoiement.
- Jamais l'utilisateur à l'écran.

## Evidence on Hand

- Épisodes réels dans `episodes/` du dépôt des vidéos (scènes, sources, miniatures `miniature.jpg`), articles
  #001 et #002.
- Planches de marque : `docs/images/planche-marque.png`, `docs/images/planche-matou.png`.
- Aucun chiffre d'audience, témoignage, partenaire ou presse : ne rien inventer.

## Product Principles

1. Toujours citer la source ; ne jamais inventer un fait ou un chiffre.
2. Une idée par écran, comme une idée par vidéo.
3. Le visiteur venu d'une vidéo doit reconnaître Matou au premier coup d'œil.
4. Rien n'est publié sans la relecture de l'utilisateur.

## Accessibility & Inclusion

Lisible sur mobile en un coup d'œil, contrastes suffisants, navigation au clavier,
mouvement réduit respecté.

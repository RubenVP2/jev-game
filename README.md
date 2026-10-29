# Le site de Matou

**L'actu de l'IA en 30 secondes. Un chat t'explique.** Page d'accueil et blog de Matou
(`@matou_ai`), en **Astro** statique sur **Cloudflare Workers**.

Les vidéos, les épisodes et la marque vivent dans un autre dépôt,
[RubenVP2/vids-for-rs](https://github.com/RubenVP2/vids-for-rs). Ce dépôt ne contient que
le site : il récupère le contenu au moment du build.

Rôle : recevoir le trafic des réseaux (lien en bio → `/liens/`), être trouvé sur Google
grâce aux articles, et créer de la valeur (lettre, partenariats).

## Pages

| Adresse | Contenu |
| --- | --- |
| `/` | Accueil joué comme un épisode : hook et abonnement, dernier épisode, « En fait… », tampons, Hype-mètre, lettre et contact (si réglés), « C'était Matou, et c'est tout. » |
| `/blog/` | Tous les articles, du plus récent au plus ancien |
| `/blog/<slug>/` | Un article = la version texte d'un épisode |
| `/liens/` | Page « lien en bio » (non indexée) : dernier article, blog, réseaux |
| `/rss.xml`, `/sitemap-index.xml`, `/robots.txt` | Flux, plan du site, robots |

## D'où vient le contenu

`npm run contenu` (lancé seul avant `dev` et `build`) fait un clone partiel de la branche
`main` de vids-for-rs dans `contenu/` (ignoré par git), sans les voix ni les vidéos :

- **Marque** : `brand/tokens.json` (couleurs), `brand/mascotte/*.svg` (Matou),
  `brand/icones/*.svg`.
- **Articles** : `episodes/NNN-slug/article.md` (écrit par le skill `article` de
  vids-for-rs), complété par `scenes.json` (numéro, série, source, tampon, Hype-mètre),
  `miniature.jpg` et `postiz-envoi.json` (date).

Ici : les polices allégées (`public/fonts/`, caractères latins, Shantell Sans figée à
« informel 60 » : 52 Ko au lieu de 174), les réseaux (`src/config.ts`, comptes `@matou_ai`
vérifiés le 28/10/2026), les pages et les styles.

**Quand un article est en ligne** : seulement si `postiz-envoi.json` dit `programmé`
(l'utilisateur a donné son feu vert dans Postiz) **et** que l'heure de la vidéo est passée
au moment du build. Le site se reconstruit toutes les heures : l'article apparaît dans
l'heure qui suit la vidéo, sans rien faire.

## Commandes

Node **24** (`.node-version` ; Astro 7 refuse Node 22.22).

```bash
npm ci
npm run dev       # http://localhost:4321 (récupère le contenu d'abord)
npm run build     # → dist/
npm run preview   # dist/ servi par Wrangler, comme en production
npm run check     # types
```

Hors ligne, ou pour essayer un épisode pas encore poussé : `CONTENU_LOCAL=../vids-for-rs
npm run dev` prend un clone local. `CONTENU_BRANCHE=<branche>` lit une autre branche.

## Mise en ligne

Le workflow `.github/workflows/deployer.yml` construit le site à chaque push, toutes les
heures et à la demande (Actions › Déployer le site › Run workflow). Il ne publie que depuis
la branche par défaut, et seulement quand ces réglages existent (Settings › Secrets and
variables › Actions) :

| Où | Nom | Valeur |
| --- | --- | --- |
| Secret | `CLOUDFLARE_API_TOKEN` | Jeton Cloudflare (modèle « Edit Cloudflare Workers ») |
| Secret | `CLOUDFLARE_ACCOUNT_ID` | Identifiant du compte Cloudflare |
| Variable | `SITE_URL` | L'adresse publique, ex. `https://matou.ai` (liens canoniques, plan du site, RSS) |
| Variable (option) | `LETTRE_ACTION` | Adresse du formulaire d'inscription du service de newsletter (et `LETTRE_CHAMP` si le champ ne s'appelle pas `email`) |
| Variable (option) | `CONTACT_EMAIL` | Adresse pour les marques et partenaires |

Sans eux, le site est construit mais pas publié (un avertissement le dit dans Actions).
Le premier déploiement crée le Worker `matou-site` (`wrangler.jsonc`). Domaine perso :
Cloudflare › Workers & Pages › matou-site › Settings › Domains & Routes › Add › Custom domain.

Ensuite : déclarer le site dans Google Search Console et y envoyer `/sitemap-index.xml` ;
mettre `https://<domaine>/liens/` dans la bio de chaque réseau.

## Performance et SEO

Mesuré avec Lighthouse le 28/10/2026 (accueil et article) : **100** en performance,
accessibilité, bonnes pratiques et SEO ; 112 Ko pour l'accueil, 118 Ko pour un article.

- Zéro JavaScript envoyé au navigateur ; CSS inline ; polices préchargées.
- Images en WebP aux bonnes tailles (Astro), cache d'un an sur `/_astro/` (`public/_headers`).
- Titre, description, lien canonique, Open Graph (`public/og.png`), données structurées
  (Organization, WebSite, Blog, BlogPosting avec la source en `citation`, fil d'Ariane).
- Typographie française : espace fine avant ? ! ; : et dans « » (`src/lib/typo.mjs`).

## Design

Direction décidée avec Impeccable : `PRODUCT.md`, `DESIGN.md`, `.impeccable/surfaces/`.
L'accueil est un épisode en scènes, dans l'univers « cahier de Matou » des vidéos. Contour
au feutre qui frémit (filtre SVG `#feutre` sur le bord seulement), surligneur, tampons et
flèche du Hype-mètre animés au défilement en CSS (`src/styles/mouvement.css`, injecté sans
minification), sans JavaScript, coupés si le visiteur réduit les animations.

La lettre et le contact n'apparaissent que si leurs variables sont réglées : sans service
choisi, rien de factice n'est affiché.

## Plus tard (idées, rien n'est commencé)

- Vidéo dans l'article : il faudra l'héberger (R2, Stream) ou intégrer le Short YouTube.
- Image de partage propre à chaque article (aujourd'hui : la même pour tout le site).
- Mentions légales : à ajouter avec les informations de l'éditeur avant toute monétisation.

---
name: Matou
description: "Le cahier de Matou, version web : l'actu de l'IA expliquée par un chat, dessinée à la main sur papier à carreaux."
colors:
  papier: "#FBF5E6"
  carreau: "#C9D9EC"
  marge: "#EE9A9A"
  encre: "#1C1B1A"
  graphite: "#A9A6A0"
  blanc: "#FFFFFF"
  surligneur: "#FFE14A"
  stylo-bleu: "#2457C5"
  stylo-vert: "#1F8A4C"
  stylo-rouge: "#D33A2C"
  fluo-rose: "#FF9EC4"
  fluo-vert: "#9EEA8C"
  fluo-bleu: "#8FD3FF"
  fluo-orange: "#FFB65C"
typography:
  display:
    fontFamily: "Permanent Marker, Comic Sans MS, cursive"
    fontSize: "clamp(2.9rem, 9vw, 6rem)"
    fontWeight: 400
    lineHeight: 1.02
    letterSpacing: "0.01em"
  headline:
    fontFamily: "Permanent Marker, Comic Sans MS, cursive"
    fontSize: "clamp(2rem, 5.5vw, 3.2rem)"
    fontWeight: 400
    lineHeight: 1.12
    letterSpacing: "0.01em"
  title:
    fontFamily: "Permanent Marker, Comic Sans MS, cursive"
    fontSize: "1.7rem"
    fontWeight: 400
    lineHeight: 1.12
    letterSpacing: "0.01em"
  ecran:
    fontFamily: "Shantell Sans, ui-rounded, system-ui, sans-serif"
    fontSize: "clamp(1rem, 4.2vw, 1.7rem)"
    fontWeight: 800
    lineHeight: 1.3
  chapo:
    fontFamily: "Shantell Sans, ui-rounded, system-ui, sans-serif"
    fontSize: "clamp(1.1rem, 2.6vw, 1.3rem)"
    fontWeight: 400
    lineHeight: 1.5
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "Shantell Sans, ui-rounded, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 800
    lineHeight: 1.2
rounded:
  feutre: "10px 14px 9px 12px"
  bouton: "255px 18px 225px 18px / 18px 225px 18px 255px"
  case: "14px"
  image: "10px"
  tampon: "8px"
spacing:
  carreau: "24px"
  gouttiere: "clamp(1.5rem, 5vw, 4.5rem)"
  feuille: "clamp(1.25rem, 4vw, 2rem)"
  scene: "clamp(4rem, 10vw, 7.5rem)"
  largeur: "72rem"
  lecture: "40rem"
components:
  button-primary:
    backgroundColor: "{colors.surligneur}"
    textColor: "{colors.encre}"
    typography: "{typography.label}"
    rounded: "{rounded.bouton}"
    padding: "0.65rem 1.5rem"
    height: "3.1rem"
  button-secondary:
    backgroundColor: "{colors.blanc}"
    textColor: "{colors.encre}"
    typography: "{typography.label}"
    rounded: "{rounded.bouton}"
    padding: "0.65rem 1.5rem"
    height: "3.1rem"
  feuille:
    backgroundColor: "{colors.blanc}"
    textColor: "{colors.encre}"
    rounded: "{rounded.feutre}"
    padding: "{spacing.feuille}"
  carte-article:
    backgroundColor: "{colors.blanc}"
    textColor: "{colors.encre}"
    rounded: "{rounded.feutre}"
    padding: "1rem"
  input-courriel:
    backgroundColor: "{colors.papier}"
    textColor: "{colors.encre}"
    rounded: "{rounded.image}"
    padding: "0 1rem"
    height: "3.1rem"
  tampon-annonce:
    textColor: "{colors.stylo-bleu}"
    rounded: "{rounded.tampon}"
    padding: "0.12em 0.6em"
  tampon-disponible:
    textColor: "{colors.stylo-vert}"
    rounded: "{rounded.tampon}"
    padding: "0.12em 0.6em"
  tampon-rumeur:
    textColor: "{colors.stylo-rouge}"
    rounded: "{rounded.tampon}"
    padding: "0.12em 0.6em"
  hype-case-choisie:
    backgroundColor: "{colors.fluo-vert}"
    textColor: "{colors.encre}"
    rounded: "{rounded.case}"
    padding: "1rem 0.4rem 0.8rem"
---

# Design System: Matou

<!-- Expression web du monde « cahier de Matou », relevée sur le site construit. Les couleurs ont une source unique : brand/tokens.json, injecté en variables CSS par src/layouts/Base.astro. Les valeurs ci-dessus en sont une copie de lecture : en cas d’écart, brand/tokens.json fait foi. brand/ et docs/design-system.md (spécification vidéo) sont dans le dépôt des vidéos, RubenVP2/vids-for-rs. -->

## Overview

**Creative North Star: "Le cahier de Matou"**

Le site est le même cahier d'écolier que les vidéos, ouvert dans un navigateur. Le fond est un papier crème à petits carreaux avec une marge rouge, entièrement en CSS (aucune image). Tout ce qui est posé dessus a l'air fait main : contours au feutre noir épais qui frémissent sur le bord, feuilles blanches scotchées avec une ombre douce décalée, surligneur jaune sur le mot clé, tampons de couleur en multiply, et Matou, le chat à lunettes, qui change d'expression et de place d'une scène à l'autre.

La page d'accueil se lit comme un épisode, scène après scène, et le mouvement reprend celui des vidéos : entrées sèches avec un léger ressort, surligneur qui se trace de gauche à droite, tampon posé d'un coup. Tout est piloté par le défilement en CSS, visible par défaut, et coupé quand l'utilisateur demande moins de mouvement. Les pages de lecture (blog) gardent le même monde mais calment le jeu : corps de texte en police système, colonne étroite, une seule note « post-it » par nuance importante.

La densité est faible et l'échelle généreuse. Le monde se reconnaît en une image et tranche avec les comptes IA sombres et néon.

**Key Characteristics:**
- Papier crème à carreaux de 24 px et marge rouge, dessinés en CSS pur.
- Contour au feutre irrégulier, déformé par le filtre SVG `#feutre` (turbulence, déplacement 3,5).
- Surligneur jaune rare, posé sur un mot clé par scène.
- Tampons bleu / vert / rouge réservés aux statuts ANNONCÉ / DISPONIBLE / RUMEUR.
- Matou en SVG inline, une expression par scène, posé sur une ellipse d'ombre grise.
- Mouvement lié au défilement, sans JavaScript, absent en mouvement réduit.

## Colors

Un papier chaud et une encre presque noire, éclairés par un jaune fluo rare et trois couleurs de stylo qui ont chacune une signification.

### Primary
- **Surligneur jaune** (surligneur) : le geste du mot clé. Fond des `mark` (tracé biseauté sur 78 % de la hauteur), du numéro d'épisode « MATOU #NNN », de l'action principale et de la page courante dans la navigation. Couleur de sélection du texte.

### Secondary
- **Stylo bleu** (stylo-bleu) : les liens, l'anneau de focus, la couleur d'accent et du curseur des champs, et le tampon ANNONCÉ.
- **Stylo vert** (stylo-vert) : uniquement le tampon DISPONIBLE.
- **Stylo rouge** (stylo-rouge) : le tampon RUMEUR et le cercle au stylo qui entoure le verdict du Hype-mètre.

### Tertiary
- **Fluos du Hype-mètre** (fluo-rose, fluo-vert, fluo-orange) : chacun colore une case du Hype-mètre (pur buzz, prometteur, game changer), seulement quand elle est choisie.
- **Fluo bleu** (fluo-bleu) : surlignage du sous-titre d'accroche, pour le distinguer du jaune du hook.

### Neutral
- **Papier crème** (papier) : le fond de toutes les pages, et celui du champ e-mail.
- **Bleu carreau** (carreau) : les lignes du quadrillage, 1 px.
- **Marge rouge** (marge) : le trait vertical de 2 px, placé dans la gouttière gauche.
- **Encre** (encre) : tout le texte, les contours au feutre, la bordure des miniatures, le filet du pied de page.
- **Graphite** (graphite) : l'ellipse d'ombre sous Matou, à 32 % d'opacité. Jamais pour du texte.
- **Feuille blanche** (blanc) : fond des feuilles scotchées, des cartes, des cases et des boutons secondaires.

### Named Rules
**The Un Surligneur par Scène Rule.** Le jaune signale le mot clé de la scène. Un `mark` jaune par titre ou par phrase, deux au plus sur un écran ; s'il est partout, il ne signale plus rien.

**The Stylo qui Veut Dire Quelque Chose Rule.** Le vert et le rouge ne servent jamais à décorer : ils sont un statut (ou, pour le rouge, l'entourage du verdict). Le bleu est à la fois statut ANNONCÉ et couleur interactive, rien d'autre.

**The Source Unique Rule.** Une couleur se change dans `brand/tokens.json`, jamais dans une feuille de style. Le site la reçoit par les variables CSS que Base.astro génère.

## Typography

**Display Font:** Permanent Marker (avec Comic Sans MS, cursive)
**Screen Font:** Shantell Sans, axe de graisse 400 à 800 (avec ui-rounded, system-ui)
**Body Font:** police système (system-ui, -apple-system, Segoe UI, Roboto)

**Character:** Le marqueur fait les titres comme sur les planches vidéo ; Shantell Sans en 800 est le « texte d'écran » manuscrit et rond ; la police système porte la lecture longue des articles pour rester lisible.

### Hierarchy
- **Display** (Permanent Marker 400, clamp(2.9rem, 9vw, 6rem), 1.02, capitales) : le hook de l'accueil uniquement.
- **Headline** (Permanent Marker 400, clamp(2rem, 5.5vw, 3.2rem), 1.12, capitales) : titres de scène de l'accueil. Les titres d'article (clamp(2rem, 5vw, 3rem)) gardent la casse du texte.
- **Title** (Permanent Marker 400, 1.25 à 1.7rem) : intertitres d'article, titres de cartes, titres de feuilles.
- **Écran** (Shantell Sans 800, clamp(1rem, 4.2vw, 1.7rem), 1.3) : le sous-titre d'accroche, sur une seule ligne, avec son mot clé au fluo. Le même 800 sert aux métadonnées, légendes, navigation et cases.
- **Chapô** (Shantell Sans 400, clamp(1.1rem, 2.6vw, 1.3rem), 1.5, 36rem max) : les phrases d'introduction de scène et d'article.
- **Body** (système 400, 1.0625rem, 1.65) : le corps des articles, en colonne de 40rem.
- **Label** (Shantell Sans 800, 1rem à 1.2rem) : boutons, liens de navigation, « Lire la version texte ».

### Named Rules
**The Marqueur pour Titrer Rule.** Permanent Marker ne sert qu'aux titres, aux numéros d'épisode et aux tampons, toujours en graisse 400, jamais pour une phrase de lecture.

**The Équilibrage Rule.** Les titres sont en `text-wrap: balance`, les paragraphes et listes en `text-wrap: pretty`.

## Layout

Une seule colonne de contenu de 72rem au plus, alignée à gauche sur la gouttière fluide (clamp(1.5rem, 5vw, 4.5rem)) ; la marge rouge du papier est tracée 1,25rem avant cette gouttière, si bien que le texte commence toujours juste à droite de la marge, comme dans un cahier. À droite, le retrait est fixe (1.25rem). L'en-tête et le pied suivent le même alignement.

L'accueil est une suite de scènes espacées de clamp(4rem, 10vw, 7.5rem). Chaque scène pose un texte et un Matou côte à côte (grilles à deux colonnes inégales, environ 1.25 / 1 ou 0.8 / 1.4, en alternant le côté de Matou). Sous 52rem, tout passe sur une colonne et Matou se place au-dessus du texte, à droite, en plus petit (58 % de largeur au plus, 9 à 16rem). Sous 34rem, l'action principale prend toute la largeur et les grilles internes (épisode, statuts) s'empilent.

Les pages de lecture limitent le texte à 40rem ; l'en-tête d'article met la miniature (220px) à droite du titre, puis au-dessus sous 48rem. Les listes de cartes passent en grille auto-fit (min 19rem).

Le quadrillage web est de 24 px (la moitié des 48 px de la vidéo, à l'échelle du 1080 px).

## Elevation & Depth

La profondeur est physique : du papier posé sur du papier. Une seule ombre, douce et décalée vers le bas à droite, comme une feuille posée sur la table dans les vidéos. Pas de surface flottante ni de flou de fond.

### Shadow Vocabulary
- **Ombre posée** (`box-shadow: 7px 9px 3px rgb(28 27 26 / 0.12)`) : feuilles, cartes, boutons, étiquette « Matou #NNN », miniature d'article, post-it.
- **Ombre soulevée** (`box-shadow: 9px 13px 6px rgb(28 27 26 / 0.16)`) : bouton survolé uniquement.
- **Ombre de scotch** (`box-shadow: 0 1px 1px rgb(0 0 0 / 0.06)`) : le morceau de scotch en haut des feuilles.
- **Ellipse de Matou** (graphite à 32 %) : pose Matou sur la ligne du cahier.

### Named Rules
**The Une Seule Ombre Rule.** Tout ce qui est posé sur le cahier porte l'ombre posée ; seul le survol d'un bouton la soulève. Aucune autre ombre n'entre dans le système.

## Shapes

Rien n'est parfaitement droit. Les contours au feutre font 3 px d'encre avec des rayons volontairement inégaux (10px 14px 9px 12px), et passent par le filtre SVG `#feutre` qui ne fait trembler que le bord : le fond et le texte restent nets. Les boutons prennent une forme de patate elliptique ; les cases du Hype-mètre un rayon de 14px ; les tampons 8px ; les miniatures 10px avec bordure d'encre.

Les objets sont légèrement de travers : feuille d'épisode à -0,6°, liste des statuts à 0,5°, miniature d'article à 2°, post-it à -0,8°, étiquette à -5°, numéro à -2°, tampons à -6°. Le scotch (92 × 26 px, jaune translucide) est centré en haut de chaque feuille, tourné de -3°.

## Components

### Buttons
Feutre noir, fond surligneur : on a envie d'appuyer dessus.
- **Shape:** forme elliptique irrégulière (rounded.bouton), contour au feutre de 3 px.
- **Primary:** fond surligneur, texte encre en Shantell Sans 800, 1.1rem, hauteur 3.1rem minimum, padding 0.65rem 1.5rem, ombre posée. L'action d'accueil grossit à 1.2rem / 3.6rem et passe en pleine largeur sur mobile ; celle de l'en-tête se réduit à 1rem / 2.5rem.
- **Hover / Focus:** survol avec ressort (translate(-1px, -3px) rotate(-1deg), 0,18 s, cubic-bezier(0.34, 1.4, 0.64, 1)) et ombre soulevée ; appui en translate(1px, 1px). Focus : anneau stylo bleu de 3 px à 4 px de distance.
- **Secondary:** même forme sur fond blanc ; utilisé pour les réseaux après le premier.

### Chips (Tampons)
- **Style:** Permanent Marker, lettrage espacé (0.06em), bordure de 3 px et texte de la couleur du statut, rayon 8px, rotation -6°, `mix-blend-mode: multiply` pour que l'encre prenne le papier.
- **State:** trois variantes fixes (ANNONCÉ bleu, DISPONIBLE vert, RUMEUR rouge), libellés et couleurs lus dans `brand/tokens.json`.

### Cards / Containers
- **Corner Style:** rayons inégaux au feutre (rounded.feutre).
- **Background:** feuille blanche sur le papier.
- **Shadow Strategy:** ombre posée (voir Elevation & Depth).
- **Border:** feutre d'encre de 3 px, frémissant.
- **Internal Padding:** clamp(1.25rem, 4vw, 2rem) pour les feuilles scotchées ; 1rem pour les cartes d'article, avec miniature de 90px à gauche, et toute la carte cliquable par un seul lien.

### Inputs / Fields
- **Style:** bordure d'encre de 3 px, rayon 10px, fond papier, hauteur 3.1rem, Shantell Sans ; libellé visible au-dessus en 800.
- **Focus:** anneau stylo bleu commun.

### Navigation
- **Style:** barre fine : Matou mini (46px) et « Matou » en marqueur à gauche, liens en Shantell Sans 800 couleur encre à droite, suivis du bouton « S'abonner ». La page courante est surlignée au jaune. Le pied est séparé par un filet d'encre de 3 px et liste les réseaux en liens soulignés.

### Hype-mètre (signature)
Trois cases au feutre côte à côte (icône maison et libellé), la case choisie prend son fluo. Une flèche d'encre au-dessus balaie jusqu'au bout, hésite puis se pose sur le verdict ; le stylo rouge entoure la case d'une ellipse en multiply, tracée de gauche à droite. La raison suit en Shantell Sans 800 avec son mot clé surligné.

### Matou
Le chat en SVG inline (`brand/mascotte/`), une expression par scène (surpris, en fait, sceptique, content), posé sur son ellipse graphite. Décoratif sauf dans le hook.

### Post-it
Dans les articles, une nuance importante devient un post-it jaune pâle avec l'ombre posée, tourné de -0,8°, en Shantell Sans.

## Do's and Don'ts

### Do:
- **Do** lire chaque couleur dans `brand/tokens.json` via les variables CSS de Base.astro (`--papier`, `--encre`, `--surligneur`, `--bleu`, `--vert`, `--rouge`, `--rose`, `--fluo-vert`, `--fluo-bleu`, `--orange`).
- **Do** poser le contenu sur une feuille blanche au feutre, scotchée, légèrement de travers, avec l'ombre posée (7px 9px 3px, encre à 12 %).
- **Do** donner à chaque scène un seul mot surligné au jaune, et un Matou avec une expression qui lui correspond.
- **Do** dessiner les icônes avec les SVG au feutre de `brand/icones/`, en ligne.
- **Do** garder le mouvement visible par défaut, piloté par le défilement en CSS, et supprimé sous `prefers-reduced-motion: reduce`.

### Don't:
- **Don't** utiliser le vert ou le rouge des stylos en décoration : ils signifient DISPONIBLE et RUMEUR.
- **Don't** écrire du texte de lecture en Permanent Marker, ni du texte en graphite.
- **Don't** ajouter d'autres ombres que l'ombre posée et l'ombre soulevée au survol.
- **Don't** tracer des contours parfaitement réguliers : le feutre a des rayons inégaux et passe par le filtre `#feutre`.
- **Don't** passer aux fonds sombres et aux néons des comptes IA : le cahier reste crème.

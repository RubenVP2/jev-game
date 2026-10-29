---
version: 1
slug: "site-src-pages-index-astro"
primary_target: "src/pages/index.astro"
related_targets: ["src/pages/blog/index.astro","src/pages/blog/[slug].astro","src/pages/liens.astro"]
---

# Accueil du site Matou

Mode : Persuade. Visiteur : sort d'une vidéo Matou sur son téléphone (lien en bio), peu d'attention. Action : s'abonner (TikTok d'abord) ou lire le dernier article. Preuve : le dernier épisode réel (numéro, source, tampon, verdict, miniature). Valeur à venir : lettre de Matou (formulaire branché quand un service est choisi) et contact partenariats (quand une adresse est fournie) ; sans réglage, ces blocs ne s'affichent pas. Pages sœurs : `/blog/`, `/blog/<slug>/` (mode Read, même monde), `/liens/`.

## Direction contract

THESIS: La page est un épisode de Matou joué en scènes, du hook au « C'était Matou, et c'est tout. » ; elle refuse le hero titre-sous-titre-bouton suivi d'une rangée de cartes égales.

OWN-WORLD: Cahier crème à carreaux de 24 px, marge rouge, encre #1C1B1A au feutre épais au contour qui frémit, surligneur jaune un seul par scène, tampons au stylo bleu/vert/rouge en multiply, feuilles blanches scotchées à ombre douce décalée, Matou SVG qui change d'expression et de place à chaque scène, icônes maison au feutre. Permanent Marker capitales pour hooks et titres, Shantell Sans 800 pour le texte d'écran, sous-titres sur une ligne avec le mot clé au fluo.

STORY: En trois secondes le visiteur reconnaît le chat de la vidéo et comprend « l'actu IA en 30 s, sourcée ». Le dernier épisode réel prouve la méthode (source, tampon, verdict). Il s'abonne au premier écran ou en clôture, ou lit l'article.

FIRST VIEWPORT: Mobile 390×844 : barre fine (Matou mini à gauche, « S'abonner » à droite). En-tête d'épisode comme en vidéo : « MATOU #NNN » surligné, série, source du dernier épisode. Hook en Permanent Marker ~3,2 rem sur trois lignes, « 30 secondes » surligné. Matou surpris ~55 % de largeur, posé à droite sur la ligne de base. Sous-titre une ligne. Action primaire pleine largeur « Suivre Matou sur TikTok », puis Instagram · YouTube · Threads en petits liens. Desktop 1440 : hook à gauche sur 7 colonnes, Matou à droite grand, même ordre.

FORM: « L'épisode en page », structure 3 de 7 (tirée), seed:e41f84c2572fb383. Interaction signature : les scènes entrent au défilement comme dans la vidéo (ressort sec ~8 images, surligneur qui se trace de gauche à droite, tampon posé d'un coup, flèche du Hype-mètre qui hésite puis se pose et le stylo rouge qui entoure), en CSS scroll-driven sans JavaScript, visible par défaut, coupé en mouvement réduit.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

# Cadrage — pipeline de veille tech vers Threads et TikTok

## Objectif

Publier chaque jour deux briefs techniques en anglais, à 8h et 19h (Europe/Paris), sur Threads et TikTok. Les sujets viennent de GitHub Trending, Hacker News et Reddit. Chaque brouillon est relu et validé sur Discord avant publication.

## Décisions

| Sujet | Décision |
|---|---|
| Sources | GitHub Trending (page HTML + API GitHub pour le README), Hacker News (API Algolia), Reddit (API OAuth) |
| LLM | Google AI Studio, OpenRouter, OrcaRouter, tous via l'API compatible OpenAI. Une chaîne de bascule par tâche (`triage`, `facts`, `write`, `judge`) |
| Langue | Anglais |
| Rythme | 2 posts par jour, à 08:00 et 19:00 Europe/Paris. Brouillon envoyé 2 h avant |
| Formats | Threads : post de 500 caractères max + carrousel des slides, avec une réponse contenant la source. TikTok : carrousel photo |
| Validation | Bot Discord avec boutons : approuver, publier maintenant, éditer, régénérer, autre sujet, rejeter |
| Stack | Python 3.12, Docker Compose sur VPS, SQLite, Playwright pour le rendu, Caddy pour le HTTPS |
| Ton | Sérieux et technique, différenciant : mécanisme, chiffre, compromis, verdict. Aucun emoji ni formule « influenceur » |
| Cohérence entre modèles | Harnais : fiche de faits commune, charte unique (rédacteur + juge), posts validés comme références, normalisation automatique, vérification des chiffres, juge avec grille fixe et révision, contrôle de débordement, profils par modèle |
| Mise en route | Clés dans `.env`, `docker compose up -d`, `veille doctor` vérifie tout |

## Ligne éditoriale

1. **Sélection** : profondeur technique, nouveauté et pertinence pour un public d'ingénieurs confirmés. Sont écartés : polémiques, levées de fonds, conseils de carrière, marketing, listes « awesome ».
2. **Faits** : uniquement ceux du dossier de recherche (README, article, métadonnées). Les commentaires de praticiens fournissent les critiques et sont attribués comme des opinions.
3. **Structure** : une affirmation concrète, puis le mécanisme, le chiffre, le compromis, et enfin un verdict « use it if / skip it if ».
4. **Contrôles automatiques** : longueurs, formules bannies, emojis, hashtags, structure des slides, chiffres absents de la source. Le même modèle corrige ses propres erreurs, trois fois au maximum.
5. **Juge** : un modèle d'une autre famille note chaque brouillon sur 7 critères fixes. Sous 7.5/10, le brouillon est révisé, et la meilleure version est gardée.

## Contraintes des plateformes

- **Threads** :
  - limite de 500 caractères, et les emojis comptent plusieurs octets ;
  - publication en deux temps (créer un conteneur, puis le publier) ;
  - carrousel de 2 à 20 images, téléchargées depuis une URL publique ;
  - token longue durée de 60 jours, rafraîchi automatiquement.
- **TikTok** :
  - pas de post texte, uniquement de la vidéo ou un carrousel photo ;
  - les photos sont tirées d'un domaine vérifié (`PULL_FROM_URL`) ;
  - tant que l'app n'a pas passé l'audit, les publications directes sont privées. D'où le mode `MEDIA_UPLOAD` par défaut : le brouillon arrive dans l'app TikTok, où l'on ajoute la musique avant de publier.

## Feuille de route

- **V1 + V2 (livrées)** : collecte, classement, rédaction via le harnais de cohérence, carrousel, validation Discord (boutons + `/draft` + `/status`), publication Threads et TikTok (brouillon TikTok par défaut), `veille doctor`, `veille eval`.
- **V3** :
  - collecter les statistiques d'engagement (Threads Insights, TikTok) et les réinjecter dans le score ;
  - demander l'audit TikTok pour publier directement ;
  - essayer des variantes A/B de couverture.

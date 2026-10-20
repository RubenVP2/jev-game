# veille — SIGNAL, brief tech quotidien

Pipeline automatique de veille technologique :

- **Collecte** sur GitHub Trending, Hacker News et Reddit.
- **Rédaction** d'un brief technique en anglais par LLM (Google AI Studio, OpenRouter ou OrcaRouter), à travers un **harnais de cohérence**.
- **Rendu** en carrousel d'images.
- **Validation** sur Discord.
- **Publication** sur Threads et TikTok à **8h** et **19h** (heure de Paris).

```
GitHub Trending ─┐                fusion des doublons      dossier : README / article
Hacker News     ─┼─► SQLite ────► score + tri LLM    ────► + meilleurs commentaires
Reddit          ─┘                (anti-répétition)                 │
                                                                    ▼
                           ┌──────────── HARNAIS DE COHÉRENCE ─────────────┐
                           │ fiche de faits ─► rédaction ─► normalisation  │
                           │   ─► contrôles + vérification des chiffres    │
                           │   ─► juge (grille fixe) ─► révision           │
                           │   ─► rendu ─► contrôle de débordement         │
                           └───────────────────────────────────────────────┘
                                                                    │
     Threads (carrousel + réponse avec source) ◄── 8h / 19h ◄── Discord : Approve · Publish now · Edit
     TikTok (carrousel photo)                                            Regenerate · Another topic · Reject
```

## Démarrage : il ne reste que les clés à fournir

```bash
git clone <repo> veille && cd veille
cp .env.example .env          # 1. remplis les clés (section REQUIRED au minimum)
docker compose up -d --build  # 2. lance le service
docker compose exec app veille doctor   # 3. vérifie tout : clés, modèles, Discord, Threads, TikTok, HTTPS, rendu
```

`veille doctor` teste chaque clé et **chaque modèle configuré** (un court appel réel), l'accès au salon Discord, le token Threads, la connexion TikTok, l'URL publique et le rendu des slides. Il dit précisément quoi corriger.

Au démarrage, le bot poste son état dans le salon Discord : prochains créneaux, fournisseurs LLM actifs, plateformes connectées.

### Contenu du `.env`

| Variable | Obligatoire | Rôle |
|---|---|---|
| `GOOGLE_AI_API_KEY` / `OPENROUTER_API_KEY` / `ORCAROUTER_API_KEY` | au moins une | LLM. Avec plusieurs clés, la bascule entre fournisseurs est automatique |
| `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, `DISCORD_ALLOWED_USER_IDS` | oui | Validation des brouillons |
| `DOMAIN` | oui | Domaine qui pointe vers le serveur. Les slides y sont servies en HTTPS |
| `THREADS_APP_ID`, `THREADS_APP_SECRET` | pour Threads | Puis `/connect Threads` sur Discord : un clic d'autorisation |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | pour TikTok | Puis `/connect TikTok` sur Discord : un clic d'autorisation |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | conseillé | Sans elles, Reddit bloque souvent les serveurs |
| `GITHUB_TOKEN` | optionnel | Relève la limite d'appels à l'API GitHub pour lire les README |

**Une plateforme sans identifiants est ignorée**, pas en erreur : tu peux démarrer avec Threads seul et ajouter TikTok plus tard.

Pas de token à copier-coller :
- `/connect` sur Discord envoie un lien d'autorisation ;
- après le clic, le token est stocké, puis rafraîchi automatiquement (Threads : 60 jours, TikTok : 24 h avec un token de renouvellement valable un an) ;
- le bot confirme dans le salon.

Le pseudo affiché sur les slides est celui du compte Threads connecté, sauf si tu en fixes un dans `brand.handle`.

**Identifiants de modèles** : ceux d'OpenRouter et d'OrcaRouter dans `config.yaml` ont été vérifiés dans leurs catalogues en ligne. Ceux de Google AI Studio viennent des notes de version officielles de l'API Gemini : `gemini-3.8-flash` est en disponibilité générale, et `gemini-pro-latest` est l'alias documenté du modèle Pro le plus récent. Si un fournisseur retire ou renomme un modèle, le pipeline prend automatiquement le plus récent de la même famille dans son catalogue (`claude-sonnet-*`, `gemini-*-pro`…) et `veille doctor` signale le remplacement.

## Le harnais de cohérence

Deux modèles différents ne raisonnent pas et n'écrivent pas pareil. Pour que les posts gardent la même voix quel que soit le modèle qui écrit (bascule de fournisseur, changement de modèle), la rédaction passe par un harnais, dans `src/veille/harness/` :

| Étape | Ce qu'elle garantit |
|---|---|
| **Fiche de faits** (tâche `facts`) | Le dossier brut (README, article, commentaires) est d'abord converti en faits structurés : mécanisme, chiffres avec **citation exacte**, compromis, critiques attribuées. Une étape automatique supprime chaque chiffre dont la citation n'existe pas dans le dossier. Tous les rédacteurs travaillent à partir de cette fiche commune. |
| **Charte unique** (`style.py`) | Les mêmes règles de voix, d'accroche, de structure et la même liste de formules bannies, formulées à l'identique pour le rédacteur et pour le juge. |
| **Exemples de référence** | Tes posts **validés sur Discord** servent de modèles de ton, complétés par les exemples fournis (`harness/exemplars/`). La voix converge vers ce que tu approuves. |
| **Accroches récentes** | Les premières lignes des derniers posts sont passées au rédacteur pour éviter de répéter la même formule. |
| **Un modèle par version** | Un même modèle écrit et corrige sa version jusqu'au bout. Si un modèle échoue, le suivant repart de zéro : un post n'est jamais un patchwork de deux modèles. |
| **Normalisation** | Guillemets, tirets, puces, ponctuation des titres, hashtags TikTok, lien source dans la réponse Threads : traités par du code, à l'identique pour tous les modèles. |
| **Contrôles automatiques** | Limites de caractères, nombre d'éléments par slide, mots bannis, emoji, « ! », première personne, questions rhétoriques, phrases trop longues, lien ou hashtag dans le post principal. Chaque problème est renvoyé au modèle pour correction. |
| **Vérification des chiffres** | Tout chiffre du post absent du dossier est refusé (« 4.1k » est accepté si la source dit 4,100). |
| **Juge** (tâche `judge`) | Un modèle d'une autre famille note le brouillon sur 7 critères fixes. Sous `min_score` (7.5/10), le brouillon est révisé avec les remarques du juge, et la meilleure version est conservée. |
| **Contrôle de débordement** | Après le rendu, le texte qui déborde d'une slide est mesuré dans le navigateur. Le rédacteur raccourcit les slides concernées ; en dernier recours, la taille du texte est réduite légèrement. |
| **Profils par modèle** (`llm.profiles`) | Réglages par modèle : mode JSON, température, consignes correctrices pour les habitudes connues d'un modèle. |

Chaque brouillon affiche sur Discord **le modèle qui l'a écrit, la note du juge, le nombre de révisions et les remarques restantes**.

### Comparer les modèles : `veille eval`

```bash
docker compose exec app veille eval                       # modèles de la chaîne "write"
docker compose exec app veille eval --models openrouter/anthropic/claude-sonnet-5.5,google/gemini-pro-latest
```

Le même dossier (un exemple fourni, ou `--dossier fichier.txt`) passe par le harnais avec chaque modèle, à partir de la même fiche de faits. Le tableau affiche, pour chaque modèle :

- la note du juge ;
- le nombre de révisions ;
- les problèmes restants ;
- le temps de génération ;
- la première ligne du post.

Les sorties complètes vont dans `out/eval/`. Utilise-le pour choisir l'ordre de la chaîne `write` et ajuster `llm.profiles`.

## Ligne éditoriale

- **Fond** : le mécanisme, le chiffre qui compte, le compromis, puis un verdict « use it if / skip it if ».
- **Ton** : sérieux et dense, sans emoji, sans « ! », sans question rhétorique, sans hashtag sur Threads, sans première personne.
- **Faits** : uniquement ceux de la source. Les commentaires HN et Reddit sont attribués comme des opinions.
- **Visuel** : un carrousel façon fiche technique (« BRIEF 0042 »), avec des slides typées : couverture, points clés, mécanisme, code, chiffre mesuré, comparatif, verdict. La couverture affiche la popularité du sujet (étoiles, points, commentaires).

## Utilisation au quotidien (Discord)

Chaque brouillon arrive **2 heures avant son créneau**, avec les slides et ces boutons :

| Bouton | Effet |
|---|---|
| Approve for slot | Publication à 8h ou 19h. Si le créneau est passé, publication dans la minute. |
| Publish now | Publication immédiate. |
| Edit text | Modifier le post et la réponse Threads, avec contrôle des 500 caractères. |
| Regenerate | Nouvelle version, avec une consigne optionnelle (« focus on the benchmark »…). Le harnais réutilise la même fiche de faits. |
| Another topic | Rejette le sujet et rédige le suivant pour le même créneau. |
| Reject | Rejette le sujet, qui ne sera plus proposé. |
| Retry publish | Après un échec, relance uniquement les plateformes qui ont échoué. |

Les commandes slash :

- `/draft [instruction]` : génère un brouillon tout de suite pour le prochain créneau libre.
- `/status` : affiche les prochains créneaux, l'état des brouillons et les plateformes connectées.
- `/connect Threads|TikTok` : lien d'autorisation à ouvrir une fois, avec confirmation dans le salon.

Le fonctionnement automatique :

- **Échec de génération** : nouvelle tentative 20 minutes plus tard, si le créneau le permet.
- **Rappel** : à l'heure du créneau, si le brouillon n'est pas encore validé.
- **Redémarrage** : si un créneau est imminent sans brouillon, il est généré au démarrage.

## Configuration (`config.yaml`)

Tout ce qui n'est pas secret se règle ici :

- sources, subreddits, langages GitHub et seuils ;
- créneaux et délai de préparation ;
- marque, `handle`, couleur et hashtags TikTok fixes ;
- chaînes de modèles par tâche (`triage`, `facts`, `write`, `judge`) ;
- profils par modèle ;
- seuils du harnais (`min_score`, `max_revisions`, `exemplars`) ;
- mode TikTok.

Les identifiants de modèles évoluent vite. `veille doctor` signale tout identifiant inconnu d'un fournisseur.

## Mise en place des comptes

### Discord
1. Crée une application sur https://discord.com/developers/applications, ajoute un bot et copie son token dans `DISCORD_BOT_TOKEN`.
2. Dans OAuth2 → URL Generator, coche les scopes `bot` et `applications.commands`, et les permissions *Send Messages*, *Attach Files*, *Embed Links* et *Read Message History*. Ouvre l'URL générée pour inviter le bot sur ton serveur.
3. Active le mode développeur de Discord, puis fais un clic droit pour copier l'ID du salon (`DISCORD_CHANNEL_ID`) et ton ID utilisateur (`DISCORD_ALLOWED_USER_IDS`).

### Domaine et HTTPS
Crée un enregistrement DNS A de `DOMAIN` vers l'IP du serveur, et ouvre les ports 80 et 443. Caddy obtient le certificat tout seul.

### Threads
1. Crée une app Meta avec le cas d'usage « Access the Threads API » : https://developers.facebook.com/apps
2. Dans les réglages du cas d'usage, ajoute les permissions `threads_basic` et `threads_content_publish`, ainsi que le redirect URI `https://DOMAIN/threads/callback`. Ajoute ton compte Threads comme testeur et accepte l'invitation dans l'app Threads.
3. Copie l'ID et le secret de l'app Threads dans `THREADS_APP_ID` et `THREADS_APP_SECRET`, puis tape `/connect Threads` sur Discord.

Alternative sans OAuth : un token longue durée généré dans le tableau de bord, à mettre dans `THREADS_ACCESS_TOKEN`.

La publication se fait en deux temps :
1. Le post principal, avec le carrousel des slides.
2. Une réponse contenant le lien vers la source. Le lien est hors du post principal pour ne pas pénaliser sa portée.

### TikTok
1. Crée une app sur https://developers.tiktok.com avec *Login Kit* et *Content Posting API*, et les scopes `user.info.basic`, `video.upload` et `video.publish`.
2. Configure le redirect URI `https://DOMAIN/tiktok/callback`.
3. **Vérifie le domaine** (enregistrement DNS TXT) : TikTok ne récupère les photos que depuis un domaine vérifié.
4. Tape `/connect TikTok` sur Discord, ouvre le lien et autorise l'accès.

Deux modes, réglés dans `publish.tiktok.mode` :
- `MEDIA_UPLOAD` (par défaut) : le carrousel arrive dans ta boîte de réception TikTok. Tu ajoutes une musique et tu publies depuis l'app.
- `DIRECT_POST` : publication directe, mais **privée tant que l'app TikTok n'a pas passé l'audit**.

### Reddit
Crée une app de type *script* sur https://www.reddit.com/prefs/apps.

## Développement

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]" && playwright install chromium
pytest && ruff check src tests

veille demo --out out/demo       # carrousel d'exemple, sans aucune clé
veille collect                   # collecte + classement
veille draft --out out/draft     # brouillon complet en local (harnais inclus), sans Discord ni publication
veille eval                      # comparer les modèles
veille doctor [--offline]        # diagnostic
veille connect threads|tiktok    # lien d'autorisation (comme /connect)
```

Les tests couvrent :
- les parsers des sources et le classement ;
- la bascule LLM et les profils par modèle ;
- tout le harnais (avec un faux LLM) ;
- la normalisation et la vérification des chiffres ;
- le rendu et la détection de débordement ;
- la publication idempotente ;
- les appels HTTP exacts envoyés à Threads et TikTok (tests de contrat d'après leur documentation) ;
- la connexion OAuth et la résolution automatique des modèles ;
- la logique du bot Discord ;
- un **test de bout en bout** : un faux serveur compatible OpenAI, interrogé en vrai HTTP, de la collecte jusqu'aux slides.

Les données (SQLite, slides, tokens) sont dans le volume Docker `veille_data`. Sauvegarde : `docker compose cp app:/app/data ./backup`.

## Structure

```
src/veille/
  sources/          github · hackernews · reddit · dossier de recherche
  ranking.py        fusion des doublons, score, anti-répétition, tri éditorial LLM
  llm.py            client compatible OpenAI multi-fournisseurs, bascule, profils, JSON validé et réparé
  harness/          harnais de cohérence : style · facts · normalize · prompts · exemplars/ · evaluate
  carousel/         template HTML + rendu Playwright, mesure de débordement et ajustement automatique
  publishers/       threads · tiktok
  pipeline.py       orchestration, créneaux, publication idempotente
  bot.py            bot Discord, commandes slash, ordonnanceur
  web.py            serveur de médias + callback OAuth TikTok
  doctor.py         diagnostic de configuration
  cli.py            commandes `veille …`
```

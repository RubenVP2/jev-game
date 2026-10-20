# veille — SIGNAL, brief tech quotidien

Pipeline automatique de veille technologique :

- **Collecte** sur GitHub Trending, Hacker News et Reddit.
- **Rédaction** d'un brief technique en anglais par LLM (Google AI Studio, OpenRouter ou OrcaRouter).
- **Rendu** en carrousel d'images.
- **Validation** sur Discord.
- **Publication** sur Threads et TikTok à **8h** et **19h** (heure de Paris).

```
GitHub Trending ─┐                 fusion des doublons     dossier : README / article
Hacker News     ─┼─► SQLite ─────► score + tri LLM    ───► + meilleurs commentaires ──► rédaction LLM
Reddit          ─┘                 (anti-répétition)                                   (contrôles éditoriaux)
                                                                                            │
           Threads (carrousel + réponse avec source) ◄── créneau 8h / 19h ◄── Discord ◄── slides JPEG
           TikTok (carrousel photo)                                         [Approve] [Publish now] [Edit]
                                                                            [Regenerate] [Another topic] [Reject]
```

Le cadrage complet est dans [`docs/CADRAGE.md`](docs/CADRAGE.md).

## Ligne éditoriale

L'objectif est de ne pas ressembler aux posts tech habituels :

- **Fond** : le mécanisme (comment ça marche), le chiffre qui compte, le compromis, et un verdict « use it if / skip it if ».
- **Ton** : sérieux et dense, sans emoji, sans point d'exclamation, sans question rhétorique, sans hashtag sur Threads. Une liste de formules bannies (« game-changer », « dive in »…) est vérifiée automatiquement.
- **Faits** : uniquement ceux du dossier (README, article, métadonnées). Les commentaires HN et Reddit servent aux critiques et sont attribués comme des opinions.
- **Visuel** : un carrousel façon fiche technique (« BRIEF 0042 »), avec des slides typées : couverture, points clés, mécanisme, code, chiffre mesuré, comparatif, verdict.

Si la sortie du LLM viole une règle (longueur, mot banni, emoji, nombre de slides), les erreurs lui sont renvoyées pour correction, jusqu'à deux fois.

## Démarrage rapide (local)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env            # au minimum une clé LLM

veille demo --out out/demo      # rend le carrousel d'exemple, sans aucune clé
veille collect                  # collecte + classement (le tri éditorial appelle le LLM)
veille draft --out out/draft    # brouillon complet en local : texte + slides, sans Discord ni publication
pytest                          # tests
```

## Configuration

- **`.env`** : secrets (clés API, tokens). Voir `.env.example`.
- **`config.yaml`** : tout le reste (sources, subreddits, langages GitHub, seuils, créneaux, marque et couleur, modèles).

### LLM : trois fournisseurs, bascule automatique

Les trois fournisseurs exposent une API compatible OpenAI, donc un seul client sert pour les trois. Chaque tâche a une chaîne de modèles : en cas d'erreur, de quota dépassé ou de réponse vide, la suivante est essayée. Les entrées sans clé API sont ignorées.

```yaml
llm:
  tasks:
    triage:   # tri éditorial des candidats, modèle rapide
      - {provider: google, model: gemini-flash-latest}
      - {provider: openrouter, model: google/gemini-3.8-flash}
      - {provider: orcarouter, model: orcarouter/auto}
    write:    # rédaction, meilleur modèle
      - {provider: openrouter, model: anthropic/claude-sonnet-5.5}
      - {provider: google, model: gemini-pro-latest}
      - {provider: orcarouter, model: orcarouter/auto}
```

| Fournisseur | Variable | Clé |
|---|---|---|
| Google AI Studio | `GOOGLE_AI_API_KEY` | https://aistudio.google.com/apikey |
| OpenRouter | `OPENROUTER_API_KEY` | https://openrouter.ai/keys |
| OrcaRouter | `ORCAROUTER_API_KEY` | https://orcarouter.ai |

Les identifiants de modèles évoluent vite. Vérifie-les dans le catalogue de chaque fournisseur et ajuste `config.yaml`.

## Mise en place des services

### 1. Discord (validation)

1. Crée une application sur https://discord.com/developers/applications, puis un bot. Copie son token dans `DISCORD_BOT_TOKEN`.
2. Invite-le sur ton serveur avec les permissions *Send Messages*, *Attach Files*, *Embed Links* et *Read Message History* : OAuth2 → URL Generator, scope `bot`.
3. Active le mode développeur de Discord, puis copie l'ID du salon (`DISCORD_CHANNEL_ID`) et ton ID utilisateur (`DISCORD_ALLOWED_USER_IDS`). Seuls ces utilisateurs peuvent appuyer sur les boutons.

Chaque brouillon arrive 2 heures avant son créneau, avec le texte, les slides et ces boutons :

| Bouton | Effet |
|---|---|
| Approve for slot | Publication automatique à 8h ou 19h. Si le créneau est déjà passé, publication dans la minute. |
| Publish now | Publication immédiate. |
| Edit text | Modifier le post et la réponse Threads, avec contrôle des 500 caractères. |
| Regenerate | Nouvelle version, avec une consigne optionnelle (« focus on the benchmark »…). |
| Another topic | Rejette le sujet et rédige le suivant pour le même créneau. |
| Reject | Rejette le sujet, qui ne sera plus proposé. |
| Retry publish | Après un échec, relance uniquement les plateformes qui ont échoué. |

### 2. Serveur public pour les médias

Threads et TikTok **téléchargent** les slides depuis une URL publique en HTTPS. `docker-compose.yml` inclut Caddy, qui obtient le certificat HTTPS automatiquement :

- `DOMAIN=veille.ton-domaine.com` : un enregistrement DNS A doit pointer vers le VPS.
- `PUBLIC_BASE_URL=https://veille.ton-domaine.com`

Les slides sont servies sous `/media/<id>-<jeton aléatoire>/slide-01.jpg`.

### 3. Threads

1. Crée une app Meta avec le cas d'usage « Access the Threads API » : https://developers.facebook.com/apps
2. Ajoute ton compte Threads comme testeur, puis génère un **token longue durée** (60 jours) avec les permissions `threads_basic` et `threads_content_publish`. Mets-le dans `THREADS_ACCESS_TOKEN`.
3. Le token est rafraîchi automatiquement chaque nuit. Tu peux aussi le rafraîchir à la main avec `veille threads-refresh`.

La publication suit cet ordre :

1. Le post principal, avec le carrousel des slides.
2. Une réponse contenant le détail technique supplémentaire et le lien vers la source. Le lien est hors du post principal pour ne pas pénaliser sa portée.

### 4. TikTok

1. Crée une app sur https://developers.tiktok.com avec les produits *Login Kit* et *Content Posting API*, et les scopes `user.info.basic`, `video.upload` et `video.publish`.
2. Configure le redirect URI `https://veille.ton-domaine.com/tiktok/callback`, puis remplis `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` et `TIKTOK_REDIRECT_URI`.
3. **Vérifie ton domaine** : TikTok n'accepte les photos que depuis un domaine vérifié. Le plus simple est la vérification par enregistrement DNS TXT sur `veille.ton-domaine.com`. Si tu choisis plutôt un fichier `.txt` servi à la racine, dépose-le dans `data/public/`.
4. Le serveur doit tourner. Lance `docker compose exec app veille tiktok-auth`, ouvre l'URL affichée et autorise l'accès : le token est enregistré automatiquement.

Deux modes de publication, réglés dans `config.yaml` → `publish.tiktok.mode` :

- `MEDIA_UPLOAD` (par défaut) : le carrousel arrive dans ta **boîte de réception TikTok**. Tu ajoutes une musique et tu publies depuis l'app, ce qui est de toute façon conseillé pour la portée.
- `DIRECT_POST` : publication directe. **Tant que ton app TikTok n'a pas passé l'audit, ces posts restent privés** (limitation de TikTok).

### 5. Reddit

Crée une app de type *script* sur https://www.reddit.com/prefs/apps et remplis `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` et `REDDIT_USER_AGENT`. Sans identifiants, les endpoints JSON publics sont utilisés, mais Reddit les bloque souvent.

## Déploiement (VPS)

```bash
git clone <repo> veille && cd veille
cp .env.example .env && nano .env
mkdir -p data && sudo chown 1000:1000 data     # le conteneur tourne en utilisateur non-root
docker compose up -d --build
docker compose logs -f app
```

Un seul processus fait tourner trois choses :

- **le bot Discord** ;
- **l'ordonnanceur** : brouillon à 6h et à 17h, vérification chaque minute des brouillons approuvés à publier, rafraîchissement du token Threads chaque nuit ;
- **le serveur de médias**.

Au redémarrage, si un créneau est imminent et n'a pas encore de brouillon, il en génère un.

Les données (SQLite, slides, tokens) sont dans `./data`. Sauvegarde ce dossier.

## Structure

```
src/veille/
  sources/          github.py · hackernews.py · reddit.py · dossier de recherche (__init__.py)
  ranking.py        fusion des doublons, score heuristique, anti-répétition, tri éditorial LLM
  llm.py            client compatible OpenAI multi-fournisseurs + bascule + JSON validé et réparé
  prompts.py        ligne éditoriale (tri + rédaction)
  writer.py         rédaction + contrôles éditoriaux
  carousel/         template HTML des slides + rendu Playwright en JPEG
  publishers/       threads.py · tiktok.py
  pipeline.py       orchestration, créneaux, publication idempotente
  bot.py            bot Discord + ordonnanceur
  web.py            serveur de médias + callback OAuth TikTok
  cli.py            commandes `veille …`
```

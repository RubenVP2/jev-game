# Subterfuge Protocol

Jeu multijoueur sur navigateur (4 à 8 joueurs, 3 manches, 8 à 12 min) qui mêle déduction sociale, extraction sous contrainte audio et arbitrage sémantique par **Kev**.

- **Opérateur** : voit la grille 4×4 et l'alignement des mots (cibles, neutres, pièges, fatal), transmet un indice *mot + chiffre* validé par Kev.
- **Infiltrés** : explorent le complexe en vue de dessus à la lampe torche (cône de 90°), discutent à la voix en audio spatialisé et valident les terminaux par contact.
- **La Taupe** : infiltré secret qui voit le Patrouilleur IA et pousse l'équipe vers les pièges.

## Architecture

| Composant | Implémentation |
| --- | --- |
| Client | React + Canvas 2D (`client/`), compilé par Vite dans `dist/` |
| Serveur de jeu | Node.js + Express + `ws` (`server/`), serveur autoritaire à 15 Hz |
| Audio | WebRTC en maillage (signalisation par le WebSocket) + Web Audio : `PannerNode` linéaire 8 m → 20 m, `BiquadFilterNode` passe-bas à 400 Hz derrière un mur, micro coupé pour les joueurs capturés |
| Arbitrage | `server/kev.js` : client `kev.bool()`, `kev.choice()`, `kev.score()` au-dessus de `POST /v1/systemone` |
| Modèle local | Service `kev/` : [jaredpalmer/kev](https://github.com/jaredpalmer/kev) (Python, PyTorch), checkpoint Hugging Face `jaredpalmer/kev-4b` par défaut (base Qwen3.5-4B) |

### À propos de Kev

[Kev](https://huggingface.co/collections/jaredpalmer/kev) est un **modèle de décision « Système 1 »**, pas un LLM génératif. Il reconstruit l'architecture de Jev (TypeSafe) : un adaptateur LoRA et une tête de pointage posés sur un petit Qwen.

- **Entrée :** un *état* (texte ou objet) et des questions typées.
- **Sortie :** une distribution de probabilités calibrée par question, en **une seule passe avant**. Aucun texte n'est généré, donc aucune hallucination possible.
- **Contrat d'API :** celui de TypeSafe, `POST /v1/systemone`, avec trois types de question :
  - `noul` : probabilité du « oui » ;
  - `choice` : une option parmi N, avec probabilités et confiance ;
  - `score` : niveau attendu sur une échelle ordonnée.

`server/kev.js` expose ces trois types sous les noms de la spec :

| Spec | Kev | Utilisation dans le jeu |
| --- | --- | --- |
| `kev.bool` | `noul` | **A.** `validateOperatorClue` : p(indice légal) |
| `kev.choice` | `choice` | **B.** `directMonsterBehavior` : `PATROL_DEFAULT` / `INVESTIGATE_SECTOR` / `HUNT_LOUDEST` / `LOCKDOWN_VENT` |
| `kev.score` | `score` | **C.** `evaluateMistakeSeverity` : crise de 1 à 5, qui module l'obscurité, la torche et la vitesse du Patrouilleur |

Kev est entraîné en anglais. Les consignes et les critères sont donc en anglais, et l'état (mots, indice) reste en français.

**Checkpoint par défaut : `kev-4b`.** C'est le plus précis de la collection servable sur un seul GPU (0,837 d'exactitude hors domaine selon sa fiche). Il pèse environ 9 Go.

- **GPU NVIDIA recommandé**, avec au moins 10 Go de VRAM. La fiche annonce environ 0,17 s pour une requête de 5 questions.
- **En CPU**, le chargement a saturé une machine de 15 Go de RAM. Prévoyez **au moins 32 Go**, et une latence de plusieurs secondes.
- `kev-0.6b` reste une solution de secours légère (`KEV_RUN=jaredpalmer/kev-0.6b`, environ 3 Go de RAM, 0,7 à 1,2 s par question en CPU). Mais sur nos essais, il **ne discrimine pas les indices** : « Chaton » face à CHAT obtient une probabilité aussi élevée qu'un indice légal.

**Validation des indices :**
- La **garde lexicale déterministe** (mot identique, racine commune, mot composé, quasi-homophone) tranche d'abord.
- La probabilité p(légal) de Kev s'affiche côté Opérateur. Kev reste **consultatif** tant que `KEV_CLUE_THRESHOLD=0`.
- Le seuil de kev-4b n'a pas pu être calibré ici, faute de mémoire suffisante. Jouez quelques indices légaux et illégaux, relevez les p affichés, puis fixez un seuil (par exemple `0.5`) pour que Kev puisse bloquer un indice.

La règle 7.3 reste imposée : un piège force `HUNT_LOUDEST`.

Si Kev est injoignable ou dépasse le délai, un **arbitrage de repli déterministe** prend le relais. Le jeu reste donc jouable sans Kev : laissez `KEV_URL` vide.

## Règles implémentées

- Chaque manche génère 16 terminaux : 6 neutres, 4 cibles, 5 pièges, 1 fatal. Un indice autorise *chiffre + 1* validations.
- **Cible** : la banque est récupérée. **Neutre** : fin de l'indice. **Piège** : alarme, une banque cible est corrompue, le Patrouilleur passe en `HUNT_LOUDEST` et l'indice prend fin. **Fatal** : victoire immédiate de la Taupe.
- Quand toutes les cibles restantes sont validées, l'ascenseur s'ouvre pendant **30 s**. Les joueurs le rejoignent et font un vote flash d'exclusion (majorité stricte).
  - Si la Taupe est éjectée, l'équipe gagne.
  - Si aucun Infiltré n'est dans l'ascenseur à la fermeture, la Taupe gagne.
- **La Taupe gagne aussi si** :
  - le compte à rebours de la manche expire (180 s par défaut) ;
  - tous les Infiltrés sont capturés ;
  - l'objectif de 75 % devient inatteignable.
- **L'équipe gagne** après 3 manches avec au moins **9 banques sur 12** (75 %).
- Les joueurs capturés sont confinés jusqu'à la manche suivante. Les joueurs éjectés le restent jusqu'à la fin de la partie.

## Contrôles

- **Ordinateur** : ZQSD, WASD ou flèches pour se déplacer, Espace (ou E) pour valider un terminal.
- **Mobile ou tablette** : joystick virtuel dynamique sur la moitié gauche de l'écran, bouton d'action ⚡ à droite.

## Développement

```bash
npm install
npm run dev:server   # serveur de jeu sur :3000
npm run dev:client   # Vite sur :5173 (proxy /ws et /config vers :3000)
npm test             # tests de l'arbitre et de la carte
```

Pour tester seul, ouvrez plusieurs onglets : chaque onglet est un joueur distinct. `MIN_PLAYERS=3` est le minimum accepté.

## Kev en local (hors Docker)

```bash
git clone https://github.com/jaredpalmer/kev.git && cd kev
uv sync --extra serve
uv run --extra serve python /chemin/vers/jev-game/kev/serve.py --run jaredpalmer/kev-4b --port 8008
KEV_URL=http://localhost:8008 npm run dev:server   # dans ce dépôt
```

`kev/serve.py` lance `kev.serve` en écoutant sur `0.0.0.0`, ce que la commande d'origine ne permet pas (elle est figée sur 127.0.0.1).

## Déploiement Docker

```bash
# Application + Kev, avec le port 3000 publié en local
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

- Au premier démarrage, le service `kev` télécharge l'adaptateur et le modèle de base Qwen3.5-4B (environ 9 Go) dans le volume `kev-hf`. Tant qu'il n'est pas prêt, le jeu utilise l'arbitrage de repli.
- **Avec un GPU NVIDIA :**
  1. Définissez `KEV_TORCH_INDEX=https://download.pytorch.org/whl/cu128`. L'image installe alors aussi `flash-linear-attention`.
  2. Décommentez le bloc `deploy` dans `docker-compose.yml`.
  3. L'hôte doit avoir le NVIDIA Container Toolkit.
- **Sans GPU :** gardez l'index CPU (l'image par défaut) et prévoyez au moins 32 Go de RAM, ou passez à `KEV_RUN=jaredpalmer/kev-0.6b`.

## Déploiement Dokploy

1. **Create Project**, puis **Create Service**, puis **Compose**. Choisissez ce dépôt Git, branche `main`, fichier `docker-compose.yml`.
2. Si besoin, ajoutez dans l'onglet **Environment** les variables de `.env.example` (par exemple `KEV_RUN=jaredpalmer/kev-4b` sur une machine avec GPU).
3. Dans l'onglet **Domains**, ajoutez votre domaine sur le service **`app`**, port **3000**, avec **HTTPS activé** (Let's Encrypt). Le micro (`getUserMedia`) n'est disponible qu'en HTTPS.
4. Cliquez sur **Deploy**. Au premier lancement, `kev` télécharge ses poids depuis Hugging Face (environ 9 Go, quelques minutes). Voir les besoins GPU et RAM ci-dessus.

Le WebSocket (`/ws`) passe par Traefik sans configuration supplémentaire. Pour une application Dokploy de type *Dockerfile* (sans le service Kev), définissez le port 3000 et laissez `KEV_URL` vide, ou pointez-la vers un serveur Kev existant.

### Variables d'environnement

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `PORT` | `3000` | Port HTTP/WebSocket |
| `KEV_URL` | *(vide)* | URL du serveur Kev (`/v1/systemone`). Vide = arbitrage de repli uniquement |
| `KEV_RUN` | `jaredpalmer/kev-4b` | Checkpoint servi par le service `kev` |
| `KEV_TORCH_INDEX` | index CPU de PyTorch | Index PyTorch utilisé au build de `kev` (`…/whl/cu128` pour NVIDIA) |
| `KEV_API_KEY` | *(vide)* | Jeton Bearer exigé par Kev s'il est défini |
| `KEV_TIMEOUT_MS` | `3000` | Délai max des appels `choice` et `score` |
| `KEV_CLUE_TIMEOUT_MS` | `2000` | Délai max de validation d'un indice |
| `KEV_CLUE_THRESHOLD` | `0` | p(indice légal) minimale pour accepter un indice. 0 = Kev consultatif |
| `MIN_PLAYERS` | `4` | Joueurs minimum pour lancer (≥ 3) |
| `ROUND_SECONDS` | `180` | Compte à rebours d'une manche |
| `EXTRACTION_SECONDS` | `30` | Fenêtre d'extraction et de vote |
| `DIRECTOR_INTERVAL` | `7` | Période (s) du directeur d'IA |
| `STUN_URLS` | `stun:stun.l.google.com:19302` | Serveurs STUN (séparés par des virgules) |
| `TURN_URL`, `TURN_USERNAME`, `TURN_CREDENTIAL` | *(vide)* | Serveur TURN pour les réseaux mobiles ou NAT stricts |

> La voix est en maillage pair-à-pair. Au-delà de 6 joueurs, ou sur des réseaux 4G/5G, un serveur TURN (par exemple coturn) améliore nettement la fiabilité.

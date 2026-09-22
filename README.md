# Subterfuge Protocol

Jeu multijoueur sur navigateur (4 à 8 joueurs, 3 manches, 8 à 12 min) qui mêle déduction sociale, extraction sous contrainte audio et arbitrage sémantique par un modèle de décision « Système 1 » local : **Laya** (multilingue, par défaut) ou **Kev**.

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
| Moteur de décision | Service `laya/` (par défaut) : [convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya), checkpoint multilingue (mmBERT, 322M paramètres). Alternative : service `kev/` ([jaredpalmer/kev](https://github.com/jaredpalmer/kev)) |

### Moteur de décision : Laya (par défaut) ou Kev

La spec parle de **Kev** ([jaredpalmer/kev](https://huggingface.co/collections/jaredpalmer/kev)). **Laya** ([convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya)) appartient à la même famille. Ce sont des **modèles de décision « Système 1 »**, pas des LLM génératifs :

- **Entrée :** un *état* et des questions typées.
- **Sortie :** une distribution de probabilités calibrée par question, en une passe, sans génération de texte.
- **Contrat :** `POST /v1/systemone`. Le jeu est donc indépendant du moteur, seule `KEV_URL` change.

`server/kev.js` garde les noms de la spec :

| Spec | Type | Utilisation dans le jeu |
| --- | --- | --- |
| `kev.bool` | `noul` | **A.** `validateOperatorClue` : p(indice interdit) |
| `kev.choice` | `choice` | **B.** `directMonsterBehavior` : `PATROL_DEFAULT` / `INVESTIGATE_SECTOR` / `HUNT_LOUDEST` / `LOCKDOWN_VENT` |
| `kev.score` | `score` | **C.** `evaluateMistakeSeverity` : crise de 1 à 5, qui module l'obscurité, la torche et la vitesse du Patrouilleur |

Les consignes et les états sont rédigés **en français et en phrases**. Ces modèles (des encodeurs) lisent mal des nombres bruts ou du JSON : « L'équipe est extrêmement bruyante, elle crie » fonctionne, `ambientVolume: 0.9` beaucoup moins.

**Pourquoi Laya par défaut ?** Voici ce qui a été mesuré sur CPU, avec les mêmes sondes en français :

| | Laya multilingue | kev-0.6b | kev-4b |
| --- | --- | --- | --- |
| Langue | 45+ langues, dont le français | anglais | anglais |
| Taille / RAM | ~650 Mo / ~1,5 Go | ~1,5 Go / ~3 Go | ~9 Go / chargement impossible dans 15 Go |
| Latence par question (CPU) | **~200–300 ms** | 0,7–1,2 s | GPU requis |
| B. Patrouilleur (6 situations) | 5 sur 6 cohérentes | choisit toujours la même action | non mesuré |
| A. Indice | détecte « Chat » face à CHAT (p = 0,96), mais faux positifs sur des indices légaux (jusqu'à 1,00 selon le plateau) | ne discrimine pas | non mesuré |

**Limites de la validation des indices :**
- Ni Laya ni kev-0.6b ne sont fiables pour valider un indice seuls. La **garde lexicale déterministe** (mot identique, racine commune, mot composé, quasi-homophone) tranche d'abord.
- Le moteur est **consultatif** par défaut (`KEV_CLUE_THRESHOLD=0`). La probabilité p(interdit) s'affiche côté Opérateur.
- Le score de gravité (C) reste approximatif : les échelles ordinales sont le point faible connu de Laya.

La règle 7.3 reste imposée : un piège force `HUNT_LOUDEST`.

Si le moteur est injoignable ou dépasse le délai, un **arbitrage de repli déterministe** prend le relais. Le jeu reste jouable sans modèle : laissez `KEV_URL` vide.

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

## Moteur de décision en local (hors Docker)

```bash
python -m venv .venv && . .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install laya==0.3.5 fastapi uvicorn
python laya/server.py                       # /v1/systemone sur :8008, télécharge les poids au 1er lancement
KEV_URL=http://localhost:8008 npm run dev:server
```

Pour utiliser Kev à la place : `kev/serve.py` lance `kev.serve` du dépôt [jaredpalmer/kev](https://github.com/jaredpalmer/kev) en écoutant sur `0.0.0.0` (voir `kev/Dockerfile`).

## Déploiement Docker

```bash
# Application + Laya, avec le port 3000 publié en local
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build

# Variante Kev (anglais, plus lourd)
docker compose -f docker-compose.yml -f docker-compose.kev.yml -f docker-compose.local.yml up -d --build
```

- Au premier démarrage, `laya` télécharge le checkpoint multilingue (environ 650 Mo) dans le volume `laya-hf`. Tant qu'il n'est pas prêt, le jeu utilise l'arbitrage de repli.
- **GPU NVIDIA (environ 35 ms par question) :**
  1. Définissez `LAYA_TORCH_INDEX=https://download.pytorch.org/whl/cu128`.
  2. Décommentez le bloc `deploy` du service `laya`.
- **Kev :** kev-4b demande un GPU avec environ 10 Go de VRAM (ou au moins 32 Go de RAM). `KEV_RUN=jaredpalmer/kev-0.6b` tient dans environ 3 Go.
- **Limite de la variante Kev :** le fichier `docker-compose.kev.yml` redirige le jeu vers Kev, mais Docker Compose ne permet pas de retirer un service par surcharge. Le service `laya` démarre donc quand même, mais il n'est pas utilisé.

## Déploiement Dokploy

1. **Create Project**, puis **Create Service**, puis **Compose**. Choisissez ce dépôt Git, branche `main`, fichier `docker-compose.yml`.
2. Si besoin, ajoutez dans l'onglet **Environment** les variables de `.env.example` (par exemple `LAYA_TORCH_INDEX` pour un GPU).
3. Dans l'onglet **Domains**, ajoutez votre domaine sur le service **`app`**, port **3000**, avec **HTTPS activé** (Let's Encrypt). Le micro (`getUserMedia`) n'est disponible qu'en HTTPS.
4. Cliquez sur **Deploy**. Au premier lancement, `laya` télécharge ses poids depuis Hugging Face (environ 650 Mo). Prévoyez environ 2 Go de RAM pour ce service.

Le WebSocket (`/ws`) passe par Traefik sans configuration supplémentaire. Pour une application Dokploy de type *Dockerfile* (sans moteur de décision), définissez le port 3000 et laissez `KEV_URL` vide, ou pointez-la vers un serveur `/v1/systemone` existant.

### Variables d'environnement

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `PORT` | `3000` | Port HTTP/WebSocket |
| `KEV_URL` | `http://laya:8008` (compose) | URL du moteur de décision (`/v1/systemone`). Vide = arbitrage de repli uniquement |
| `LAYA_SUBFOLDER` | `multilingual` | Checkpoint Laya : `multilingual`, ou vide pour l'anglais |
| `LAYA_TORCH_INDEX` | index CPU de PyTorch | Index PyTorch au build de `laya` (`…/whl/cu128` pour NVIDIA) |
| `KEV_RUN`, `KEV_TORCH_INDEX` | `jaredpalmer/kev-4b`, index CPU | Variante Kev (`docker-compose.kev.yml`) |
| `KEV_API_KEY` | *(vide)* | Jeton Bearer exigé par le moteur s'il est défini |
| `KEV_TIMEOUT_MS` | `1500` | Délai max des appels `choice` et `score` |
| `KEV_CLUE_TIMEOUT_MS` | `1000` | Délai max de validation d'un indice |
| `KEV_CLUE_THRESHOLD` | `0` | p(indice interdit) au-delà de laquelle le moteur rejette un indice. 0 = consultatif |
| `MIN_PLAYERS` | `4` | Joueurs minimum pour lancer (≥ 3) |
| `ROUND_SECONDS` | `180` | Compte à rebours d'une manche |
| `EXTRACTION_SECONDS` | `30` | Fenêtre d'extraction et de vote |
| `DIRECTOR_INTERVAL` | `7` | Période (s) du directeur d'IA |
| `STUN_URLS` | `stun:stun.l.google.com:19302` | Serveurs STUN (séparés par des virgules) |
| `TURN_URL`, `TURN_USERNAME`, `TURN_CREDENTIAL` | *(vide)* | Serveur TURN pour les réseaux mobiles ou NAT stricts |

> La voix est en maillage pair-à-pair. Au-delà de 6 joueurs, ou sur des réseaux 4G/5G, un serveur TURN (par exemple coturn) améliore nettement la fiabilité.

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
| Arbitrage | `server/kev.js` : `kev.bool()`, `kev.choice()`, `kev.score()` |
| Modèle local | Ollama (sortie JSON contrainte par schéma, température 0, seed fixe) |

### À propos de Kev

Le paquet `@jaredpalmer/kev` cité dans la spec n'est pas publié sur npm. `server/kev.js` reproduit donc la même API typée au-dessus d'Ollama. Chaque appel renvoie uniquement une valeur typée (booléen, choix dans une énumération ou entier borné), jamais de texte libre.

Les trois cas d'usage de la spec se trouvent dans `server/arbiter.js` :

- **A. `validateOperatorClue`** : une garde lexicale déterministe (mot identique, racine commune, mot composé, quasi-homophone) passe d'abord, puis `kev.bool`.
- **B. `directMonsterBehavior`** : `kev.choice` parmi `PATROL_DEFAULT`, `INVESTIGATE_SECTOR`, `HUNT_LOUDEST` et `LOCKDOWN_VENT`. Un piège force `HUNT_LOUDEST` (règle 7.3).
- **C. `evaluateMistakeSeverity`** : `kev.score` de 1 à 5. Le score module l'obscurité, la portée de la torche et la vitesse du Patrouilleur.

Si Ollama n'est pas joignable ou dépasse le délai, un **arbitrage de repli déterministe** prend le relais. Le jeu reste donc jouable sans LLM : laissez `OLLAMA_URL` vide.

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

## Déploiement Docker

```bash
# Application + Ollama, avec le port 3000 publié en local
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

L'image de l'application seule (`docker build -t subterfuge .`) fonctionne aussi sans Ollama. Le repli déterministe est alors utilisé.

## Déploiement Dokploy

1. **Create Project**, puis **Create Service**, puis **Compose**. Choisissez ce dépôt Git, branche `main`, fichier `docker-compose.yml`.
2. Si besoin, ajoutez dans l'onglet **Environment** les variables de `.env.example` (par exemple `KEV_MODEL=llama3.1:8b` sur une machine avec GPU).
3. Dans l'onglet **Domains**, ajoutez votre domaine sur le service **`app`**, port **3000**, avec **HTTPS activé** (Let's Encrypt). Le micro (`getUserMedia`) n'est disponible qu'en HTTPS.
4. Cliquez sur **Deploy**. Au premier lancement, le service `ollama-pull` télécharge le modèle (environ 1 Go pour `qwen2.5:1.5b`) puis s'arrête.

Le WebSocket (`/ws`) passe par Traefik sans configuration supplémentaire. Pour une application Dokploy de type *Dockerfile* (sans Ollama), définissez le port 3000 et laissez `OLLAMA_URL` vide.

### Variables d'environnement

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `PORT` | `3000` | Port HTTP/WebSocket |
| `OLLAMA_URL` | *(vide)* | URL d'Ollama. Vide = arbitrage de repli uniquement |
| `KEV_MODEL` | `qwen2.5:1.5b` | Modèle utilisé par Kev |
| `KEV_TIMEOUT_MS` | `2500` | Délai max des appels `choice` et `score` |
| `KEV_CLUE_TIMEOUT_MS` | `1500` | Délai max de validation d'un indice (objectif spec : < 200 ms avec GPU) |
| `MIN_PLAYERS` | `4` | Joueurs minimum pour lancer (≥ 3) |
| `ROUND_SECONDS` | `180` | Compte à rebours d'une manche |
| `EXTRACTION_SECONDS` | `30` | Fenêtre d'extraction et de vote |
| `DIRECTOR_INTERVAL` | `7` | Période (s) du directeur d'IA |
| `STUN_URLS` | `stun:stun.l.google.com:19302` | Serveurs STUN (séparés par des virgules) |
| `TURN_URL`, `TURN_USERNAME`, `TURN_CREDENTIAL` | *(vide)* | Serveur TURN pour les réseaux mobiles ou NAT stricts |

> La voix est en maillage pair-à-pair. Au-delà de 6 joueurs, ou sur des réseaux 4G/5G, un serveur TURN (par exemple coturn) améliore nettement la fiabilité.

// Cas d'usage A/B/C de la spec : moteur de décision (Laya par défaut, ou Kev — même contrat
// /v1/systemone) en premier, repli déterministe si indisponible.
import { kev } from './kev.js';

const CLUE_TIMEOUT = Number(process.env.KEV_CLUE_TIMEOUT_MS || 1000);
// Seuil de p(indice interdit) au-delà duquel le moteur de décision rejette un indice.
// 0 = consultatif (défaut) : la garde lexicale déterministe tranche seule et p(interdit) est
// affiché à l'Opérateur. Mesuré avec Laya multilingue : un indice légal (« Xylophonez »)
// obtient parfois p ≈ 0,92–1,00 selon le plateau, un seuil bloquerait donc des indices légaux.
const CLUE_THRESHOLD = Number(process.env.KEV_CLUE_THRESHOLD || 0);
// Les modèles de décision (encodeurs) lisent mieux des phrases que des nombres bruts :
// l'état est donc rédigé en français naturel.

export const normalize = (s) =>
  String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z]/g, '');

const stem = (w) => w.replace(/(ement|ation|eurs?|euse|ette|ique|ier|iere|es|s|x|e)$/, '');

function levenshtein(a, b) {
  const dp = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = dp[0];
    dp[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const tmp = dp[j];
      dp[j] = Math.min(dp[j] + 1, dp[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = tmp;
    }
  }
  return dp[b.length];
}

// Garde lexicale déterministe : identique, racine commune, mot composé, quasi-homophone.
export function lexicalClueCheck(clue, boardWords) {
  const raw = String(clue).trim();
  if (!raw || /\s/.test(raw)) return { ok: false, reason: 'Un seul mot, sans espace.' };
  const c = normalize(raw);
  if (c.length < 2) return { ok: false, reason: 'Indice trop court.' };
  for (const word of boardWords) {
    const w = normalize(word);
    if (c === w) return { ok: false, reason: `Identique à « ${word} ».` };
    if ((c.length >= 3 && w.includes(c)) || (w.length >= 3 && c.includes(w)))
      return { ok: false, reason: `Mot composé / inclus dans « ${word} ».` };
    const sc = stem(c), sw = stem(w);
    if (sc.length >= 3 && sc === sw) return { ok: false, reason: `Même racine que « ${word} ».` };
    let p = 0;
    while (p < c.length && c[p] === w[p]) p++;
    if (p >= 5 || (p >= 4 && Math.min(c.length, w.length) <= 6))
      return { ok: false, reason: `Racine lexicale commune avec « ${word} ».` };
    if (Math.min(c.length, w.length) >= 4 && levenshtein(c, w) <= 1)
      return { ok: false, reason: `Trop proche phonétiquement de « ${word} ».` };
  }
  return { ok: true };
}

// Cas A — kev.bool
export async function validateOperatorClue(clue, boardWords) {
  const lex = lexicalClueCheck(clue, boardWords);
  if (!lex.ok) return { valid: false, reason: lex.reason, source: 'lexical' };
  try {
    const result = await kev.bool({
      input: `Mots du plateau : ${boardWords.join(', ')}. Indice proposé par l'Opérateur : « ${clue} ».`,
      instruction:
        "L'indice est-il interdit parce qu'il ressemble trop à l'un des mots du plateau (même mot, même famille de mots, ou mot composé) ?",
      criteria: { true: 'Oui, interdit', false: 'Non, autorisé' },
      threshold: CLUE_THRESHOLD,
      timeoutMs: CLUE_TIMEOUT,
    });
    return CLUE_THRESHOLD > 0 && result.value
      ? { valid: false, reason: `Kev a rejeté l’indice (p(interdit) = ${result.probability.toFixed(2)}).`, source: 'kev' }
      : { valid: true, source: 'kev', probability: result.probability };
  } catch {
    return { valid: true, source: 'lexical' };
  }
}

export const MONSTER_BEHAVIORS = ['PATROL_DEFAULT', 'INVESTIGATE_SECTOR', 'HUNT_LOUDEST', 'LOCKDOWN_VENT'];

export function fallbackBehavior({ ambientVolume, lastTerminalStatus }, rand = Math.random) {
  if (lastTerminalStatus === 'TRAP' || ambientVolume > 0.6) return 'HUNT_LOUDEST';
  if (lastTerminalStatus === 'SUCCESS' || ambientVolume > 0.3) return 'INVESTIGATE_SECTOR';
  return rand() < 0.2 ? 'LOCKDOWN_VENT' : 'PATROL_DEFAULT';
}

// Cas B — kev.choice
export function describeContext({ ambientVolume, lastTerminalStatus, activeSector }) {
  const noise = ambientVolume < 0.2 ? 'silencieuse' : ambientVolume < 0.6 ? 'assez bruyante' : 'extrêmement bruyante, elle crie';
  const terminal = {
    NEUTRAL: "Aucun terminal n'a été piraté récemment.",
    SUCCESS: "L'équipe vient de pirater un terminal avec succès.",
    TRAP: 'Une alarme de sécurité vient de se déclencher.',
  }[lastTerminalStatus];
  return `L'équipe est ${noise}. ${terminal} Secteur actif : ${activeSector}.`;
}

export async function directMonsterBehavior(context) {
  // Règle 7.3 : un piège de sécurité déclenche toujours la traque du plus bruyant.
  if (context.lastTerminalStatus === 'TRAP') return 'HUNT_LOUDEST';
  try {
    const decision = await kev.choice({
      input: describeContext(context),
      instruction: 'Quel comportement doit adopter le monstre ?',
      choices: {
        PATROL_DEFAULT: 'Tout est calme : ronde de routine',
        INVESTIGATE_SECTOR: "Un terminal vient d'être piraté : fouiller ce secteur",
        HUNT_LOUDEST: 'Alarme déclenchée ou équipe très bruyante : traquer le joueur le plus bruyant',
        LOCKDOWN_VENT: 'Rien de notable depuis longtemps : tendre une embuscade depuis un conduit',
      },
    });
    return decision.choice;
  } catch {
    return fallbackBehavior(context);
  }
}

// Cas C — kev.score
export async function evaluateMistakeSeverity(selectedWord, targetClue, alignment) {
  try {
    const assessment = await kev.score({
      input: `Indice : « ${targetClue} ». Mot choisi par l'équipe : « ${selectedWord} ». Le terminal était ${alignment === 'TRAP' ? 'un piège de sécurité' : 'une donnée neutre'}.`,
      instruction: "À quel point le mot choisi est-il éloigné de l'indice ?",
      min: 1,
      max: 5,
      levels: [
        'Très proche, erreur compréhensible',
        'Assez proche',
        'Moyennement lié',
        'Peu lié',
        'Aucun rapport, erreur absurde',
      ],
    });
    // Un piège reste au minimum une erreur sérieuse.
    return alignment === 'TRAP' ? Math.max(3, assessment.score) : assessment.score;
  } catch {
    return alignment === 'FATAL' ? 5 : alignment === 'TRAP' ? 4 : 2;
  }
}

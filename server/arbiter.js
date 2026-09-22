// Cas d'usage A/B/C de la spec : Kev en premier, repli déterministe si indisponible.
import { kev } from './kev.js';

const CLUE_TIMEOUT = Number(process.env.KEV_CLUE_TIMEOUT_MS || 2000);
// Seuil de la probabilité « indice légal » (noul). 0 = Kev consultatif : la garde lexicale
// tranche seule. kev-0.6b ne discrimine pas assez les indices pour bloquer ; montez le seuil
// (ex. 0.5) avec kev-4b / kev-8b après l'avoir calibré sur vos propres indices.
const CLUE_THRESHOLD = Number(process.env.KEV_CLUE_THRESHOLD || 0);
// Kev est entraîné en anglais : instructions et critères sont formulés en anglais,
// l'état (mots du plateau, indice) reste en français.

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
      input: { clue, board: boardWords },
      instruction:
        'Is the clue a legal Codenames clue? It is illegal if it is identical to a board word, shares a direct lexical root with a board word, or is an obvious compound of a board word.',
      criteria: { true: 'Legal clue', false: 'Illegal clue: identical, same root or compound of a board word' },
      threshold: CLUE_THRESHOLD,
      timeoutMs: CLUE_TIMEOUT,
    });
    return result.value
      ? { valid: true, source: 'kev', probability: result.probability }
      : { valid: false, reason: `Kev a rejeté l’indice (p = ${result.probability.toFixed(2)}).`, source: 'kev' };
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
export async function directMonsterBehavior(context) {
  // Règle 7.3 : un piège de sécurité déclenche toujours la traque du plus bruyant.
  if (context.lastTerminalStatus === 'TRAP') return 'HUNT_LOUDEST';
  try {
    const decision = await kev.choice({
      input: context,
      instruction: 'Pick the priority behavior of the containment entity given the danger and the noise level.',
      choices: {
        PATROL_DEFAULT: 'Everything is quiet: routine patrol',
        INVESTIGATE_SECTOR: 'A terminal was hacked or there is moderate noise: search the active sector',
        HUNT_LOUDEST: 'A security trap fired or the team is very loud: sprint to the loudest player',
        LOCKDOWN_VENT: 'The team is making steady progress: ambush them from a vent',
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
      input: `The team selected "${selectedWord}" while trying to follow the clue "${targetClue}". The terminal was ${alignment === 'TRAP' ? 'a security trap' : 'neutral data'}.`,
      instruction: 'Rate how dangerous and semantically incoherent this mistake is.',
      min: 1,
      max: 5,
      levels: [
        'Slight divergence: the word is close to the clue',
        'Minor mistake',
        'Serious mistake',
        'Severe mistake: the word is unrelated to the clue',
        'Critical error: antivirus triggered',
      ],
    });
    // Un piège reste au minimum une erreur sérieuse.
    return alignment === 'TRAP' ? Math.max(3, assessment.score) : assessment.score;
  } catch {
    return alignment === 'FATAL' ? 5 : alignment === 'TRAP' ? 4 : 2;
  }
}

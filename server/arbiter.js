// Cas d'usage A/B/C de la spec : Kev en premier, repli déterministe si indisponible.
import { kev } from './kev.js';

const CLUE_TIMEOUT = Number(process.env.KEV_CLUE_TIMEOUT_MS || 1500);

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
      input: `Indice proposé: "${clue}". Mots présents sur le plateau: ${JSON.stringify(boardWords)}.`,
      instruction:
        "Détermine si l'indice est valide selon les règles de Codenames : aucun mot identique, aucune racine lexicale directe avec un mot présent sur le plateau, aucun mot composé évident.",
      timeoutMs: CLUE_TIMEOUT,
    });
    return result.value
      ? { valid: true, source: 'kev' }
      : { valid: false, reason: 'Kev a rejeté l’indice (triche lexicale détectée).', source: 'kev' };
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
      input: JSON.stringify(context),
      instruction:
        "Sélectionne le comportement prioritaire pour l'entité de confinement en fonction du danger et du niveau sonore.",
      choices: MONSTER_BEHAVIORS,
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
      input: `L'équipe a sélectionné "${selectedWord}" en tentant de suivre l'indice "${targetClue}".`,
      instruction:
        "Évalue la dangerosité et l'incohérence sémantique de cette erreur sur une échelle de 1 (légère divergence) à 5 (erreur critique/antivirus déclenché).",
      min: 1,
      max: 5,
    });
    // Un piège reste au minimum une erreur sérieuse.
    return alignment === 'TRAP' ? Math.max(3, assessment.score) : assessment.score;
  } catch {
    return alignment === 'FATAL' ? 5 : alignment === 'TRAP' ? 4 : 2;
  }
}

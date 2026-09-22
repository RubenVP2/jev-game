// Client du moteur de décision « Système 1 » servi localement : Laya (convaiinnovations/laya,
// multilingue, par défaut) ou Kev (jaredpalmer/kev). Aucun des deux ne génère de texte :
// un état + des questions typées entrent, une distribution de probabilités calibrée par
// question sort, en une seule passe avant (contrat TypeSafe
// POST /v1/systemone, types noul / choice / score). Toutes les questions d'une requête
// sont évaluées en parallèle, pour à peu près la latence d'une seule.
// Cette surcouche expose l'API de la spec : kev.bool(), kev.choice(), kev.score().

const KEV_URL = (process.env.KEV_URL || '').replace(/\/$/, '');
const API_KEY = process.env.KEV_API_KEY || '';
const MODEL = process.env.KEV_MODEL || 'kev-latest';
const DEFAULT_TIMEOUT = Number(process.env.KEV_TIMEOUT_MS || 1500);

export class KevUnavailable extends Error {}

async function systemone(state, questions, timeoutMs = DEFAULT_TIMEOUT) {
  if (!KEV_URL) throw new KevUnavailable('KEV_URL non configurée');
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${KEV_URL}/v1/systemone`, {
      method: 'POST',
      signal: ctrl.signal,
      headers: { 'content-type': 'application/json', ...(API_KEY && { authorization: `Bearer ${API_KEY}` }) },
      body: JSON.stringify({ model: MODEL, state, questions }),
    });
    if (!res.ok) throw new KevUnavailable(`Kev HTTP ${res.status}`);
    const data = await res.json();
    for (const id of Object.keys(questions))
      if (!data.answers?.[id]) throw new KevUnavailable(`réponse manquante pour « ${id} »`);
    return data.answers;
  } catch (err) {
    throw err instanceof KevUnavailable ? err : new KevUnavailable(err.message);
  } finally {
    clearTimeout(timer);
  }
}

export const kev = {
  enabled: Boolean(KEV_URL),
  model: MODEL,
  systemone,

  // Noul : probabilité de « oui », seuillée par l'appelant.
  async bool({ input, instruction, criteria, threshold = 0.5, timeoutMs }) {
    const { q } = await systemone(input, { q: { type: 'noul', instructions: instruction, criteria } }, timeoutMs);
    return { value: q.noul >= threshold, probability: q.noul };
  },

  // Choice : `choices` est une liste de noms ou un objet { nom: description }.
  async choice({ input, instruction, choices, timeoutMs }) {
    const criteria = Array.isArray(choices) ? Object.fromEntries(choices.map((c) => [c, ''])) : choices;
    const { q } = await systemone(input, { q: { type: 'choice', instructions: instruction, criteria } }, timeoutMs);
    if (!(q.choice in criteria)) throw new KevUnavailable('choix hors liste');
    return { choice: q.choice, probabilities: q.probabilities, confidence: q.confidence };
  },

  // Score : niveaux ordonnés min..max ; Kev renvoie le niveau moyen attendu (indice depuis 0).
  async score({ input, instruction, min, max, levels, timeoutMs }) {
    const criteria = levels || Array.from({ length: max - min + 1 }, (_, i) => String(min + i));
    const { q } = await systemone(input, { q: { type: 'score', instructions: instruction, criteria } }, timeoutMs);
    const expected = min + Number(q.score);
    if (!Number.isFinite(expected)) throw new KevUnavailable('score invalide');
    return { score: Math.min(max, Math.max(min, Math.round(expected))), expected, probabilities: q.probabilities, confidence: q.confidence };
  },
};

// Premier appel : charge les poids en mémoire et vérifie que le serveur répond.
export async function warmupKev() {
  if (!kev.enabled) return;
  for (let attempt = 1; attempt <= 30; attempt++) {
    try {
      await kev.bool({ input: 'ping', instruction: 'Is this a ping?', timeoutMs: 60000 });
      console.log(`[kev] ${KEV_URL} prêt`);
      return;
    } catch (e) {
      if (attempt === 30) console.warn(`[kev] injoignable (${e.message}) : arbitrage de repli actif`);
      else await new Promise((r) => setTimeout(r, 10000));
    }
  }
}

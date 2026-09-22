// Kev : arbitre d'inférence structurée typée (Système 1).
// API compatible avec la spec : kev.bool(), kev.choice(), kev.score().
// Backend : modèle local servi par Ollama, sortie contrainte par schéma JSON,
// température 0 et seed fixe pour un arbitrage déterministe. Aucun texte libre.

const OLLAMA_URL = (process.env.OLLAMA_URL || '').replace(/\/$/, '');
const MODEL = process.env.KEV_MODEL || 'qwen2.5:1.5b';
const DEFAULT_TIMEOUT = Number(process.env.KEV_TIMEOUT_MS || 2500);

const SYSTEM =
  "Tu es Kev, un arbitre logique strict pour un jeu. Tu ne produis jamais de texte libre : " +
  'tu réponds uniquement avec un objet JSON conforme au schéma demandé.';

export class KevUnavailable extends Error {}

async function infer(schema, { input, instruction, timeoutMs = DEFAULT_TIMEOUT }) {
  if (!OLLAMA_URL) throw new KevUnavailable('OLLAMA_URL non configurée');
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${OLLAMA_URL}/api/chat`, {
      method: 'POST',
      signal: ctrl.signal,
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        model: MODEL,
        stream: false,
        format: schema,
        keep_alive: '30m',
        options: { temperature: 0, seed: 42, num_predict: 32 },
        messages: [
          { role: 'system', content: SYSTEM },
          { role: 'user', content: `Instruction : ${instruction}\nEntrée : ${input}` },
        ],
      }),
    });
    if (!res.ok) throw new KevUnavailable(`Ollama HTTP ${res.status}`);
    const data = await res.json();
    return JSON.parse(data.message?.content ?? '{}');
  } catch (err) {
    throw err instanceof KevUnavailable ? err : new KevUnavailable(err.message);
  } finally {
    clearTimeout(timer);
  }
}

export const kev = {
  enabled: Boolean(OLLAMA_URL),
  model: MODEL,

  async bool(opts) {
    const out = await infer(
      { type: 'object', properties: { value: { type: 'boolean' } }, required: ['value'] },
      opts,
    );
    if (typeof out.value !== 'boolean') throw new KevUnavailable('réponse bool invalide');
    return { value: out.value };
  },

  async choice({ choices, ...opts }) {
    const out = await infer(
      { type: 'object', properties: { choice: { type: 'string', enum: choices } }, required: ['choice'] },
      opts,
    );
    if (!choices.includes(out.choice)) throw new KevUnavailable('réponse choice invalide');
    return { choice: out.choice };
  },

  async score({ min, max, ...opts }) {
    const out = await infer(
      {
        type: 'object',
        properties: { score: { type: 'integer', minimum: min, maximum: max } },
        required: ['score'],
      },
      opts,
    );
    const n = Math.round(Number(out.score));
    if (!Number.isFinite(n)) throw new KevUnavailable('réponse score invalide');
    return { score: Math.min(max, Math.max(min, n)) };
  },
};

// Préchauffe le modèle pour tenir l'objectif de latence (< 200 ms sur GPU).
export async function warmupKev() {
  if (!kev.enabled) return;
  try {
    await kev.bool({ input: 'ping', instruction: 'Réponds true.', timeoutMs: 120000 });
    console.log(`[kev] modèle ${MODEL} prêt`);
  } catch (e) {
    console.warn(`[kev] préchauffage impossible (${e.message}) — arbitrage de repli actif`);
  }
}

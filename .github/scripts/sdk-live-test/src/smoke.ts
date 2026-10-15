/**
 * Secrets smoke: one model per registered provider that has its API key env set.
 *
 * Pick order for openai with OPENAI_API_KEY:
 *   1. First SMOKE_PREFERRED id present in the catalogue (gpt-4o-mini, …)
 *   2. Else highest score among active serverless chat/completion models
 *
 * Smoke runs baseline scenarios only (see runTargets baselineOnly).
 */
import type { CatalogueModel } from './catalogue.js';
import { getProviderSpec, listRegisteredProviders } from './providers.js';
import type { Target } from './run.js';

/** Curated from provider docs + live /models; first catalogue hit wins. */
const SMOKE_PREFERRED: Record<string, string[]> = {
  openai: ['gpt-4o-mini', 'gpt-4o-mini-2024-07-18', 'gpt-4.1-mini'],
  anthropic: ['claude-haiku-5-5', 'claude-haiku-4-5-20251001', 'claude-haiku-4-5'],
  groq: ['openai/gpt-oss-20b', 'qwen/qwen3.8-27b', 'openai/gpt-oss-120b', 'allam-2-7b'],
  xai: ['grok-4.3', 'grok-4.5', 'grok-4.7', 'grok-latest'],
  cerebras: ['qwen-3.8-27b', 'gpt-oss-120b'],
  'together-ai': [
    'Qwen/Qwen3.5-9B',
    'Prism-ML/Ternary-Bonsai-27B',
    'zai-org/GLM-5.3-Flash',
    'openai/gpt-oss-120b',
  ],
  deepinfra: ['anthropic/claude-haiku-4-5', 'google/gemini-2.5-flash'],
  'mistral-ai': ['mistral-small-latest', 'ministral-8b-latest', 'open-mistral-nemo'],
  sambanova: ['Meta-Llama-3.1-8B-Instruct', 'MiniMax-M2.7'],
  cohere: ['command-r7b-12-2024', 'command-r-08-2024', 'command-a-03-2025'],
  'perplexity-ai': ['sonar', 'sonar-pro'],
  openrouter: ['openai/gpt-4o-mini', 'anthropic/claude-haiku-4.5'],
  ai21: ['jamba-mini', 'jamba-mini-1.6-2025-03'],
  'google-gemini': ['gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-1.5-flash'],
};

const SMOKE_BAN = /(codex|realtime|image|embed|tts|whisper|guard|moderation)/i;

/** Fallback score when no preferred ID exists in the catalogue. */
export function smokeScore(model: CatalogueModel): number {
  const id = model.model.toLowerCase();
  let score = 0;
  if (model.mode === 'chat') score += 100;
  else if (model.mode === 'completion') score += 40;
  else score -= 50;
  if (SMOKE_BAN.test(id)) score -= 100;
  if (/(mini|haiku|flash|small|lite|nano|8b|instant)/.test(id)) score += 30;
  if (/(opus|ultra|pro|o1|o3|120b|70b)/.test(id)) score -= 20;
  if ((model.status as string | undefined) === 'deprecated') score -= 80;
  return score;
}

function pickModel(provider: string, candidates: CatalogueModel[]): CatalogueModel | undefined {
  const pool = candidates.filter(
    (m) =>
      (m.mode === 'chat' || m.mode === 'completion') &&
      !['deprecated', 'retired'].includes(String(m.status ?? '')) &&
      !SMOKE_BAN.test(m.model),
  );
  if (pool.length === 0) return undefined;

  const preferred = SMOKE_PREFERRED[provider] ?? [];
  for (const id of preferred) {
    const hit = pool.find((m) => m.model === id);
    if (hit) return hit;
  }

  const sorted = [...pool].sort((a, b) => {
    const aSrv = a.provisioning === 'serverless' ? 1 : 0;
    const bSrv = b.provisioning === 'serverless' ? 1 : 0;
    if (bSrv !== aSrv) return bSrv - aSrv;
    const aAct = a.status === 'active' ? 1 : 0;
    const bAct = b.status === 'active' ? 1 : 0;
    if (bAct !== aAct) return bAct - aAct;
    return smokeScore(b) - smokeScore(a) || a.model.localeCompare(b.model);
  });
  return sorted[0];
}

export function targetsWithSecrets(catalogue: CatalogueModel[]): Target[] {
  const out: Target[] = [];
  for (const provider of listRegisteredProviders()) {
    const spec = getProviderSpec(provider)!;
    if (!process.env[spec.apiKeyEnv]) {
      console.log(`smoke skip ${provider}: missing env ${spec.apiKeyEnv}`);
      continue;
    }
    const candidates = catalogue.filter((m) => m.provider === provider);
    if (candidates.length === 0) {
      console.log(`smoke skip ${provider}: no models in catalogue`);
      continue;
    }
    const pick = pickModel(provider, candidates);
    if (!pick) {
      console.log(`smoke skip ${provider}: no suitable model`);
      continue;
    }
    console.log(`smoke pick ${provider}/${pick.model} (mode=${pick.mode}) via ${spec.apiKeyEnv}`);
    out.push({ provider, modelId: pick.model });
  }
  return out;
}

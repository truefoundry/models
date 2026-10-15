import type { CatalogueModel } from './catalogue.js';
import { getProviderSpec, listRegisteredProviders } from './providers.js';
import type { Target } from './run.js';

/**
 * Curated cheap chat IDs for CI smoke (first hit in catalogue wins).
 * Heuristic "mini" picks (codex-mini, retired haiku, etc.) are unreliable.
 */
const SMOKE_PREFERRED: Record<string, string[]> = {
  openai: ['gpt-4o-mini', 'gpt-4o-mini-2024-07-18', 'gpt-4.1-mini'],
  // Dated id — bare `claude-haiku-4-5` 404s on some Anthropic keys.
  anthropic: ['claude-haiku-4-5-20251001', 'claude-haiku-4-5', 'claude-haiku-5-5'],
  groq: ['openai/gpt-oss-20b', 'openai/gpt-oss-120b', 'allam-2-7b', 'gemma-7b-it'],
  xai: ['grok-3-mini', 'grok-2-1212'],
  cerebras: ['qwen-3.8-27b', 'gpt-oss-120b', 'llama3.1-70b'],
  // Prefer Together serverless Turbo / small instruct — many Llama 3.1 Turbo ids are dedicated-only.
  'together-ai': [
    'Qwen/Qwen2.5-7B-Instruct-Turbo',
    'openai/gpt-oss-20b',
    'meta-llama/Llama-3.3-70B-Instruct-Turbo',
    'LiquidAI/LFM2.5-8B-A1B',
    'arize-ai/qwen-2-1.5b-instruct',
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
  const usable = candidates.filter(
    (m) =>
      (m.mode === 'chat' || m.mode === 'completion') &&
      !['deprecated', 'retired'].includes(String(m.status ?? '')) &&
      !SMOKE_BAN.test(m.model),
  );
  const pool = usable.length ? usable : candidates;
  const preferred = SMOKE_PREFERRED[provider] ?? [];
  for (const id of preferred) {
    const hit = pool.find((m) => m.model === id);
    if (hit) return hit;
  }
  // Prefer catalogue serverless + active when falling back.
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

/** One model per registered provider that has its API key env set. */
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

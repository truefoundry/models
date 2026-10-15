import type { CatalogueModel } from './catalogue.js';
import { getProviderSpec, listRegisteredProviders } from './providers.js';
import type { Target } from './run.js';

/** Prefer cheap chat models for workflow_dispatch smoke. */
export function smokeScore(model: CatalogueModel): number {
  const id = model.model.toLowerCase();
  let score = 0;
  if (model.mode === 'chat') score += 100;
  else if (model.mode === 'completion') score += 40;
  else score -= 50;
  if (/(mini|haiku|flash|small|lite|nano)/.test(id)) score += 30;
  if (/(opus|ultra|pro|o1|o3|realtime|image|embed|tts|whisper)/.test(id)) score -= 20;
  if ((model.status as string | undefined) === 'deprecated') score -= 40;
  return score;
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
    candidates.sort((a, b) => smokeScore(b) - smokeScore(a) || a.model.localeCompare(b.model));
    const pick = candidates[0]!;
    console.log(`smoke pick ${provider}/${pick.model} (mode=${pick.mode}) via ${spec.apiKeyEnv}`);
    out.push({ provider, modelId: pick.model });
  }
  return out;
}

/**
 * Secrets smoke: one chat model per registered provider that has its credential env set.
 *
 * `spec.apiKeyEnv` is the env *name* (e.g. "OPENAI_API_KEY" or "VERTEX_KEY_FILE").
 * `process.env[spec.apiKeyEnv]` is the secret *value* (never logged).
 *
 * Example: OPENAI_API_KEY set → first openai chat row in the catalogue
 *   → [{ provider: "openai", modelId: "…" }]
 *
 * Smoke runs baseline scenarios only (see runTargets baselineOnly).
 */
import type { CatalogueModel } from './catalogue.js';
import { getProviderSpec, listRegisteredProviders } from './providers.js';
import type { Target } from './run.js';

export function targetsWithSecrets(catalogue: CatalogueModel[]): Target[] {
  const out: Target[] = [];
  for (const provider of listRegisteredProviders()) {
    const spec = getProviderSpec(provider)!;
    if (!process.env[spec.apiKeyEnv]) {
      console.log(`smoke skip ${provider}: missing env ${spec.apiKeyEnv}`);
      continue;
    }
    const pick = catalogue.find((m) => m.provider === provider && m.mode === 'chat');
    if (!pick) {
      console.log(`smoke skip ${provider}: no chat model in catalogue`);
      continue;
    }
    console.log(`smoke pick ${provider}/${pick.model} via ${spec.apiKeyEnv}`);
    out.push({ provider, modelId: pick.model });
  }
  return out;
}

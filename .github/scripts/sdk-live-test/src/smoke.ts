/**
 * Secrets smoke: one model per registered provider (spec.smokeModel, else first chat) whose credential and account env are set.
 *
 * `spec.apiKeyEnv` is the env *name* (e.g. "OPENAI_API_KEY" or "VERTEX_KEY_FILE").
 * `process.env[spec.apiKeyEnv]` is the secret *value* (never logged).
 *
 * Example: OPENAI_API_KEY set → openai/gpt-4o-mini
 *   → [{ provider: "openai", modelId: "gpt-4o-mini" }]
 *
 * Smoke runs baseline scenarios only (see runTargets baselineOnly).
 */
import type { CatalogueModel } from './catalogue.js';
import { getProviderSpec, listRegisteredProviders, missingAccountEnv } from './providers.js';
import type { Target } from './run.js';

export function targetsWithSecrets(catalogue: CatalogueModel[]): Target[] {
  const out: Target[] = [];
  for (const provider of listRegisteredProviders()) {
    const spec = getProviderSpec(provider)!;
    if (!process.env[spec.apiKeyEnv]) {
      console.log(`smoke skip ${provider}: missing env ${spec.apiKeyEnv}`);
      continue;
    }
    const missingEnv = missingAccountEnv(spec);
    if (missingEnv) {
      console.log(`smoke skip ${provider}: missing env ${missingEnv}`);
      continue;
    }
    const pick = catalogue.find(
      (m) =>
        m.provider === provider &&
        (spec.smokeModel ? m.model === spec.smokeModel : m.mode === 'chat'),
    );
    if (!pick) {
      console.log(`smoke skip ${provider}: smoke model not in catalogue`);
      continue;
    }
    console.log(`smoke pick ${provider}/${pick.model} via ${spec.apiKeyEnv}`);
    out.push({ provider, modelId: pick.model });
  }
  return out;
}

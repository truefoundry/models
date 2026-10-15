import fs from 'node:fs';
import type { ProviderModelConfigs } from '@truefoundry/ai-gateway-sdk';

export type ModelParam = {
  key: string;
  defaultValue?: unknown;
  supportedValues?: string[];
};

export type CatalogueModel = {
  provider: string;
  model: string;
  mode: string;
  features?: string[];
  thinking?: boolean;
  removeParams?: string[];
  requiredParams?: string[];
  supportedModes?: string[];
  params?: ModelParam[];
  defaultProviderParams?: { params?: ModelParam[] };
  modalities?: { input?: string[]; output?: string[] };
  [key: string]: unknown;
};

/** Load dist/ai-models.json produced by `npm run build:json`. */
export function loadCatalogue(path: string): CatalogueModel[] {
  const raw = JSON.parse(fs.readFileSync(path, 'utf8')) as CatalogueModel[];
  if (!Array.isArray(raw)) {
    throw new Error(`Expected ai-models.json array at ${path}`);
  }
  return raw;
}

/** Nested map the SDK expects: modelConfig[provider][modelId] = catalogue row. */
export function toModelConfigMap(models: CatalogueModel[]): ProviderModelConfigs {
  const out: ProviderModelConfigs = {};
  for (const m of models) {
    if (!out[m.provider]) out[m.provider] = {};
    out[m.provider][m.model] = m as ProviderModelConfigs[string][string];
  }
  return out;
}

export function findCatalogueModel(
  models: CatalogueModel[],
  provider: string,
  modelId: string,
): CatalogueModel | undefined {
  return models.find((m) => m.provider === provider && m.model === modelId);
}

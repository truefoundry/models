import {
  LlmGatewaySdk,
  type Endpoint,
  type ProviderOptions,
  type SdkCallInputs,
  type SdkRequestBody,
} from '@truefoundry/ai-gateway-sdk';
import {
  findCatalogueModel,
  loadCatalogue,
  toModelConfigMap,
  type CatalogueModel,
} from './catalogue.js';
import { getProviderSpec } from './providers.js';
import { planScenarios, type Scenario } from './scenarios.js';

export type Target = { provider: string; modelId: string };

export type ScenarioResult = {
  provider: string;
  modelId: string;
  scenario: string;
  status: 'pass' | 'fail';
  detail: string;
};

function memoryCache() {
  const store = new Map<string, unknown>();
  return {
    get: async (key: string) => store.get(key),
    update: async (key: string, value: unknown) => {
      store.set(key, value);
    },
  };
}

function modelTypesForMode(mode: string): string[] {
  return [mode];
}

function buildCall(
  model: CatalogueModel,
  apiKey: string,
  scenario: Scenario,
): SdkCallInputs {
  const spec = getProviderSpec(model.provider);
  if (!spec) throw new Error(`No provider spec for ${model.provider}`);

  const accountName = `sdk-live-${model.provider}`;
  const providerOptions = {
    model: {
      fqn: `${accountName}/${model.model}`,
      name: model.model,
      manifest: {
        name: model.model,
        type: spec.modelIntegrationType,
        model_id: model.model,
        model_types: modelTypesForMode(model.mode),
      },
    },
    providerAccount: {
      fqn: accountName,
      name: accountName,
      provider: spec.sdkProvider,
      tenantName: 'sdk-live',
      manifest: {
        type: spec.accountType,
        name: accountName,
        ...(spec.baseUrl ? { base_url: spec.baseUrl } : {}),
        auth_data: {
          type: 'api-key',
          [spec.authKeyField ?? 'api_key']: apiKey,
        },
        integrations: [],
      },
    },
  } as unknown as ProviderOptions;

  return {
    request: {
      body: scenario.body as SdkRequestBody,
      method: 'POST',
      headers: {},
      endpoint: scenario.endpoint as Endpoint,
      path: scenario.path,
      search: '',
    },
    execution: { requestTimeoutMs: 120_000 },
    providerOptions,
    callConfig: {},
    session: { tenantName: 'sdk-live' },
  };
}

export async function runTargets(
  cataloguePath: string,
  targets: Target[],
): Promise<ScenarioResult[]> {
  const catalogue = loadCatalogue(cataloguePath);
  const sdk = new LlmGatewaySdk({
    allowAmbientCredentials: false,
    modelConfig: toModelConfigMap(catalogue),
    providerConfig: {},
    cache: memoryCache(),
  });

  const results: ScenarioResult[] = [];

  for (const t of targets) {
    const spec = getProviderSpec(t.provider);
    if (!spec) {
      results.push({
        provider: t.provider,
        modelId: t.modelId,
        scenario: 'setup',
        status: 'fail',
        detail: 'provider not in SDK live harness registry (add providers.ts + GitHub secret)',
      });
      continue;
    }
    const apiKey = process.env[spec.apiKeyEnv];
    if (!apiKey) {
      results.push({
        provider: t.provider,
        modelId: t.modelId,
        scenario: 'setup',
        status: 'fail',
        detail: `missing GitHub secret / env ${spec.apiKeyEnv}`,
      });
      continue;
    }

    const model = findCatalogueModel(catalogue, t.provider, t.modelId);
    if (!model) {
      results.push({
        provider: t.provider,
        modelId: t.modelId,
        scenario: 'setup',
        status: 'fail',
        detail: 'not found in ai-models.json (missing costs or build skip)',
      });
      continue;
    }

    const scenarios = planScenarios(model);
    for (const scenario of scenarios) {
      if (scenario.id.startsWith('unsupported/')) {
        results.push({
          provider: t.provider,
          modelId: t.modelId,
          scenario: scenario.id,
          status: 'fail',
          detail: `mode ${model.mode} has no SDK live scenario`,
        });
        continue;
      }
      try {
        const call = buildCall(model, apiKey, scenario);
        const { response, executionReport } = await sdk.execute(call);
        const text = await response.text();
        await executionReport;
        if (!response.ok) {
          results.push({
            provider: t.provider,
            modelId: t.modelId,
            scenario: scenario.id,
            status: 'fail',
            detail: `HTTP ${response.status}: ${text.slice(0, 400)}`,
          });
        } else {
          results.push({
            provider: t.provider,
            modelId: t.modelId,
            scenario: scenario.id,
            status: 'pass',
            detail: `HTTP ${response.status}`,
          });
        }
      } catch (err) {
        results.push({
          provider: t.provider,
          modelId: t.modelId,
          scenario: scenario.id,
          status: 'fail',
          detail: err instanceof Error ? err.message : String(err),
        });
      }
    }
  }

  return results;
}

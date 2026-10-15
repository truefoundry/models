/**
 * Execute planned scenarios through LlmGatewaySdk against the real provider API.
 *
 * Flow for openai/gpt-4o-mini + chat/baseline/non-stream:
 *   1. Look up catalogue row + OPENAI_API_KEY
 *   2. Build fake providerAccount (api-key + base_url) and model FQN
 *   3. sdk.execute → SDK maps OpenAI-shaped body to provider HTTP
 *   4. Pass = response.ok (2xx)
 */
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

function pushResult(results: ScenarioResult[], r: ScenarioResult): void {
  results.push(r);
  console.log(`${r.status.toUpperCase()} ${r.provider}/${r.modelId} ${r.scenario}: ${r.detail}`);
}

function memoryCache() {
  const store = new Map<string, unknown>();
  return {
    get: async (key: string) => store.get(key),
    update: async (key: string, value: unknown) => {
      store.set(key, value);
    },
  };
}

function buildCall(
  model: CatalogueModel,
  apiKey: string,
  scenario: Scenario,
): SdkCallInputs {
  const spec = getProviderSpec(model.provider);
  if (!spec) throw new Error(`No provider spec for ${model.provider}`);

  // Synthetic account — same shape the gateway would load from control-plane.
  // Example FQN: sdk-live-openai/gpt-4o-mini
  const accountName = `sdk-live-${model.provider}`;
  const providerOptions = {
    model: {
      fqn: `${accountName}/${model.model}`,
      name: model.model,
      manifest: {
        name: model.model,
        type: spec.modelIntegrationType,
        model_id: model.model,
        model_types: [model.mode],
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

export type RunTargetsOptions = {
  /** Smoke: only scenario ids containing "baseline" (credential + harness check). */
  baselineOnly?: boolean;
};

export async function runTargets(
  cataloguePath: string,
  targets: Target[],
  options: RunTargetsOptions = {},
): Promise<ScenarioResult[]> {
  const catalogue = loadCatalogue(cataloguePath);
  const sdk = new LlmGatewaySdk({
    allowAmbientCredentials: false,
    modelConfig: toModelConfigMap(catalogue),
    providerConfig: {},
    cache: memoryCache(),
  });

  const results: ScenarioResult[] = [];

  for (let i = 0; i < targets.length; i++) {
    const t = targets[i]!;
    console.log(`\n[${i + 1}/${targets.length}] ${t.provider}/${t.modelId}`);

    const spec = getProviderSpec(t.provider);
    if (!spec) {
      pushResult(results, {
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
      pushResult(results, {
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
      pushResult(results, {
        provider: t.provider,
        modelId: t.modelId,
        scenario: 'setup',
        status: 'fail',
        detail: 'not found in ai-models.json (missing costs or build skip)',
      });
      continue;
    }

    let scenarios = planScenarios(model);
    if (options.baselineOnly) {
      scenarios = scenarios.filter((s) => s.id.includes('baseline'));
    }
    for (const scenario of scenarios) {
      if (scenario.id.startsWith('unsupported/')) {
        pushResult(results, {
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
          pushResult(results, {
            provider: t.provider,
            modelId: t.modelId,
            scenario: scenario.id,
            status: 'fail',
            detail: `HTTP ${response.status}: ${text.slice(0, 400)}`,
          });
        } else {
          pushResult(results, {
            provider: t.provider,
            modelId: t.modelId,
            scenario: scenario.id,
            status: 'pass',
            detail: `HTTP ${response.status}`,
          });
        }
      } catch (err) {
        pushResult(results, {
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

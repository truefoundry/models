/**
 * Execute planned scenarios through LlmGatewaySdk against the real provider API.
 *
 * Flow for openai/gpt-4o-mini + chat/baseline/non-stream:
 *   1. Look up catalogue row + OPENAI_API_KEY
 *   2. Build fake providerAccount (api-key + base_url) and model FQN
 *   3. sdk.execute → SDK maps OpenAI-shaped body to provider HTTP
 *   4. Pass = response.ok (2xx)
 *
 * Vertex (google-vertex): VERTEX_KEY_FILE = SA JSON → auth_data type key-file;
 * project_id from that JSON; region from provider spec (europe-west4).
 */
import { setTimeout as sleep } from 'node:timers/promises';
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
import {
  getProviderSpec,
  missingAccountEnv,
  projectIdFromKeyFile,
  type ProviderSpec,
} from './providers.js';
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

function accountEnvFields(spec: ProviderSpec): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const [field, envName] of Object.entries(spec.accountEnv ?? {})) {
    const value = process.env[envName];
    if (value) fields[field] = value;
  }
  return fields;
}

function authData(spec: ProviderSpec, credential: string) {
  if (spec.authType === 'key-file') {
    return { type: 'key-file' as const, key_file_content: credential };
  }
  return {
    type: 'api-key' as const,
    [spec.authKeyField ?? 'api_key']: credential,
  };
}

function buildCall(
  model: CatalogueModel,
  credential: string,
  scenario: Scenario,
): SdkCallInputs {
  const spec = getProviderSpec(model.provider);
  if (!spec) throw new Error(`No provider spec for ${model.provider}`);

  // Synthetic account — same shape the gateway would load from control-plane.
  // Example FQN: sdk-live-openai/gpt-4o-mini
  const accountName = `sdk-live-${model.provider}`;
  // Fall back to a region the catalogue lists (e.g. bare Bedrock IDs are in-region only in a few regions).
  const costRegions = (model.costs ?? []).map((c) => c.region);
  const region =
    Object.entries(spec.modelPrefixRegions ?? {}).find(([prefix]) => model.model.startsWith(prefix))?.[1] ??
    (spec.region && costRegions.length && !costRegions.includes(spec.region) ? costRegions[0] : spec.region);
  const keyFileExtras =
    spec.authType === 'key-file'
      ? {
          project_id: projectIdFromKeyFile(credential),
          region: region ?? 'europe-west4',
        }
      : {};
  const providerOptions = {
    model: {
      fqn: `${accountName}/${model.model}`,
      name: model.model,
      manifest: {
        name: model.model,
        type: spec.modelIntegrationType,
        model_id: `${spec.modelIdPrefix ?? ''}${model.model}`,
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
        ...(region && spec.authType !== 'key-file' ? { region } : {}),
        ...accountEnvFields(spec),
        ...keyFileExtras,
        auth_data: authData(spec, credential),
        integrations: [],
      },
    },
  } as unknown as ProviderOptions;

  return {
    request: {
      body: scenario.body as SdkRequestBody,
      method: 'POST',
      headers: scenario.headers ?? {},
      endpoint: scenario.endpoint as Endpoint,
      path: scenario.path,
      search: scenario.search ?? '',
    },
    execution: { requestTimeoutMs: 120_000 },
    providerOptions,
    callConfig: {},
    session: { tenantName: 'sdk-live' },
  };
}

const MAX_RETRIES = 3;
const RETRY_BASE_MS = 2_000;
// Rate limits and transient upstream errors; 500 is excluded since it can be a real failure.
const RETRYABLE_STATUSES = new Set([429, 502, 503, 504]);

/** Retries transient failures with 2s, 4s, 8s backoff. */
async function executeWithRetry(
  sdk: LlmGatewaySdk,
  call: SdkCallInputs,
  label: string,
): Promise<{ response: Response; text: string }> {
  for (let attempt = 0; ; attempt++) {
    const { response, executionReport } = await sdk.execute(call);
    const text = await response.text();
    await executionReport;
    if (!RETRYABLE_STATUSES.has(response.status) || attempt >= MAX_RETRIES) return { response, text };

    const waitMs = RETRY_BASE_MS * 2 ** attempt;
    console.log(`${response.status} ${label}: retry ${attempt + 1}/${MAX_RETRIES} in ${waitMs / 1000}s`);
    await sleep(waitMs);
  }
}

export type RunTargetsOptions = {
  /** Only scenario ids containing "baseline" (credential + harness check). */
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
    const credential = process.env[spec.apiKeyEnv];
    if (!credential) {
      pushResult(results, {
        provider: t.provider,
        modelId: t.modelId,
        scenario: 'setup',
        status: 'fail',
        detail: `missing GitHub secret / env ${spec.apiKeyEnv}`,
      });
      continue;
    }
    const missingEnv = missingAccountEnv(spec);
    if (missingEnv) {
      pushResult(results, {
        provider: t.provider,
        modelId: t.modelId,
        scenario: 'setup',
        status: 'fail',
        detail: `missing GitHub secret / env ${missingEnv}`,
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
      const started = performance.now();
      const elapsed = () => `${((performance.now() - started) / 1000).toFixed(1)}s`;
      try {
        const call = buildCall(model, credential, scenario);
        const { response, text } = await executeWithRetry(
          sdk,
          call,
          `${t.provider}/${t.modelId} ${scenario.id}`,
        );
        if (!response.ok) {
          pushResult(results, {
            provider: t.provider,
            modelId: t.modelId,
            scenario: scenario.id,
            status: 'fail',
            detail: `HTTP ${response.status} (${elapsed()}): ${text.slice(0, 400)}`,
          });
        } else {
          pushResult(results, {
            provider: t.provider,
            modelId: t.modelId,
            scenario: scenario.id,
            status: 'pass',
            detail: `HTTP ${response.status} (${elapsed()})`,
          });
        }
      } catch (err) {
        pushResult(results, {
          provider: t.provider,
          modelId: t.modelId,
          scenario: scenario.id,
          status: 'fail',
          detail: `${err instanceof Error ? err.message : String(err)} (${elapsed()})`,
        });
      }
    }
  }

  return results;
}

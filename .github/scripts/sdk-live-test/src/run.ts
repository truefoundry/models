/**
 * Execute planned scenarios through LlmGatewaySdk against the real provider API.
 *
 * Flow for openai/gpt-4o-mini + chat/baseline/non-stream:
 *   1. Look up catalogue row + OPENAI_API_KEY
 *   2. Build fake providerAccount (api-key + base_url) and model FQN
 *   3. sdk.execute → SDK maps OpenAI-shaped body to provider HTTP
 *   4. Verdict = judge(): 2xx plus visible evidence for declared features; absent features
 *      should be rejected (a working undeclared feature is a warn)
 *
 * Vertex (google-vertex): VERTEX_KEY_FILE = SA JSON → auth_data type key-file;
 * project_id from that JSON; region from provider spec (europe-west4).
 */
import {
  LlmGatewaySdk,
  type Endpoint,
  type ProviderModelConfigs,
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
import { isTransient, judge } from './expectations.js';
import { getProviderSpec, projectIdFromKeyFile, type ProviderSpec } from './providers.js';
import { planScenarios, type Scenario } from './scenarios.js';

export type Target = { provider: string; modelId: string };

export type ScenarioResult = {
  provider: string;
  modelId: string;
  scenario: string;
  status: 'pass' | 'warn' | 'fail';
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
  const keyFileExtras =
    spec.authType === 'key-file'
      ? {
          project_id: projectIdFromKeyFile(credential),
          region: spec.region ?? 'europe-west4',
        }
      : {};
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

/** Copy of the config map where `model` also declares `feature`; the original is untouched. */
export function withDeclaredFeature(
  map: ProviderModelConfigs,
  model: CatalogueModel,
  feature: string,
): ProviderModelConfigs {
  return withRow(map, model, { ...model, features: [...(model.features ?? []), feature] });
}

/**
 * Copy where `model` takes `param`: added to `params`, dropped from `removeParams`. The SDK
 * strips params a model does not list (`modelSupportsParam`), so without this the probe would
 * never reach the provider.
 */
export function withDeclaredParam(
  map: ProviderModelConfigs,
  model: CatalogueModel,
  param: string,
): ProviderModelConfigs {
  const params = (model.params ?? []).some((p) => p.key === param)
    ? model.params
    : [...(model.params ?? []), { key: param }];
  const removeParams = (model.removeParams ?? []).filter((k) => k !== param);
  return withRow(map, model, { ...model, params, removeParams });
}

function withRow(map: ProviderModelConfigs, model: CatalogueModel, row: CatalogueModel): ProviderModelConfigs {
  return {
    ...map,
    [model.provider]: { ...map[model.provider], [model.model]: row },
  } as ProviderModelConfigs;
}

const RETRY_DELAYS_MS = [2_000, 6_000];

/** Retry 429 / 5xx twice, so a rate limit or a blip is not read as the model's answer. */
async function executeWithRetry(
  sdk: LlmGatewaySdk,
  call: SdkCallInputs,
): Promise<{ status: number; text: string }> {
  for (let attempt = 0; ; attempt++) {
    const { response, executionReport } = await sdk.execute(call);
    const text = await response.text();
    await executionReport;
    const delay = RETRY_DELAYS_MS[attempt];
    if (!isTransient(response.status) || delay == null) return { status: response.status, text };
    await new Promise((r) => setTimeout(r, delay));
  }
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
  const modelConfig = toModelConfigMap(catalogue);
  const sdk = new LlmGatewaySdk({
    allowAmbientCredentials: false,
    modelConfig,
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
    // A rejected absent probe only counts when the plain call to the same model worked.
    let baselineOk = false;
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
      // The SDK reads `features` (e.g. Bedrock drops tool_choice, folds system into user when
      // undeclared). An absent probe runs against a copy that declares the feature, so the
      // request reaches the provider as sent.
      const probing = scenario.expect === 'absent';
      if (probing && scenario.param) {
        sdk.updateModelConfig(withDeclaredParam(modelConfig, model, scenario.param));
      } else if (probing && scenario.feature) {
        sdk.updateModelConfig(withDeclaredFeature(modelConfig, model, scenario.feature));
      }
      try {
        const call = buildCall(model, credential, scenario);
        const { status, text } = await executeWithRetry(sdk, call);
        const verdict = judge(scenario, status, text, { baselineOk });
        // Absent probes are chat-only and planned after the chat baseline (planOneMode('chat')).
        if (scenario.id === 'chat/baseline/non-stream') baselineOk = verdict.status === 'pass';
        pushResult(results, {
          provider: t.provider,
          modelId: t.modelId,
          scenario: scenario.id,
          ...verdict,
        });
      } catch (err) {
        pushResult(results, {
          provider: t.provider,
          modelId: t.modelId,
          scenario: scenario.id,
          status: 'fail',
          detail: err instanceof Error ? err.message : String(err),
        });
      } finally {
        if (probing) sdk.updateModelConfig(modelConfig);
      }
    }
  }

  return results;
}

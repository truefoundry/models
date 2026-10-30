/**
 * Providers this harness can call live.
 * Directory name under providers/ must match the key (e.g. providers/together-ai/).
 *
 * Unlisted providers (Azure, audio-only, …) fail the PR check
 * when a changed model targets them — add a row + GitHub secret to opt in.
 */
export type ProviderSpec = {
  /** SDK Providers index + modelConfig key. */
  sdkProvider: string;
  modelIntegrationType: string;
  accountType: string;
  /** Env var holding the credential GitHub secret (API key or Vertex SA JSON). */
  apiKeyEnv: string;
  baseUrl?: string;
  /** auth_data field name; default api_key (Gemini uses apiKey). */
  authKeyField?: 'api_key' | 'apiKey';
  /** Default api-key. Vertex uses key-file (SA JSON in apiKeyEnv). */
  authType?: 'api-key' | 'key-file';
  /** Account region. Vertex key-file uses europe-west4; Bedrock API-key accounts use us-east-1. */
  region?: string;
  /** Region override by model-id prefix, e.g. Vertex `meta/` → us-east5, Bedrock geo profile `in.` → ap-south-1. */
  modelPrefixRegions?: Record<string, string>;
  /** Account manifest fields whose values come from env (Databricks base_url, Foundry endpoints). */
  accountEnv?: Record<string, string>;
  /** Model verified live for smoke; if deprecated or unset, the first non-deprecated chat model. */
  smokeModel?: string;
  /** Prepended to the catalogue model id on the wire, for gateways that namespace models by account. */
  modelIdPrefix?: string;
};

const SPECS: Record<string, ProviderSpec> = {
  openai: {
    sdkProvider: 'openai',
    modelIntegrationType: 'integration/model/openai',
    accountType: 'provider-account/openai',
    apiKeyEnv: 'OPENAI_API_KEY',
    baseUrl: 'https://api.openai.com/v1',
    smokeModel: 'gpt-4o-mini',
  },
  anthropic: {
    sdkProvider: 'anthropic',
    modelIntegrationType: 'integration/model/anthropic',
    accountType: 'provider-account/anthropic',
    apiKeyEnv: 'ANTHROPIC_API_KEY',
    baseUrl: 'https://api.anthropic.com/v1',
    smokeModel: 'claude-haiku-4-5-20251001',
  },
  groq: {
    sdkProvider: 'groq',
    modelIntegrationType: 'integration/model/groq',
    accountType: 'provider-account/groq',
    apiKeyEnv: 'GROQ_API_KEY',
    smokeModel: 'openai/gpt-oss-20b',
  },
  xai: {
    sdkProvider: 'xai',
    modelIntegrationType: 'integration/model/xai',
    accountType: 'provider-account/xai',
    apiKeyEnv: 'XAI_API_KEY',
    baseUrl: 'https://api.x.ai/v1',
    smokeModel: 'grok-4.3',
  },
  cerebras: {
    sdkProvider: 'cerebras',
    modelIntegrationType: 'integration/model/cerebras',
    accountType: 'provider-account/cerebras',
    apiKeyEnv: 'CEREBRAS_API_KEY',
    smokeModel: 'gpt-oss-120b',
  },
  'together-ai': {
    sdkProvider: 'together-ai',
    modelIntegrationType: 'integration/model/together-ai',
    accountType: 'provider-account/together-ai',
    apiKeyEnv: 'TOGETHER_AI_API_KEY',
  },
  deepinfra: {
    sdkProvider: 'deepinfra',
    modelIntegrationType: 'integration/model/deepinfra',
    accountType: 'provider-account/deepinfra',
    apiKeyEnv: 'DEEPINFRA_API_KEY',
    smokeModel: 'meta-llama/Llama-3.3-70B-Instruct-Turbo',
  },
  'mistral-ai': {
    sdkProvider: 'mistral-ai',
    modelIntegrationType: 'integration/model/mistral-ai',
    accountType: 'provider-account/mistral-ai',
    apiKeyEnv: 'MISTRAL_AI_API_KEY',
    smokeModel: 'mistral-small-latest',
  },
  'perplexity-ai': {
    sdkProvider: 'perplexity-ai',
    modelIntegrationType: 'integration/model/perplexity-ai',
    accountType: 'provider-account/perplexity-ai',
    apiKeyEnv: 'PERPLEXITY_AI_API_KEY',
  },
  openrouter: {
    sdkProvider: 'openrouter',
    modelIntegrationType: 'integration/model/openrouter',
    accountType: 'provider-account/openrouter',
    apiKeyEnv: 'OPENROUTER_API_KEY',
  },
  sambanova: {
    sdkProvider: 'sambanova',
    modelIntegrationType: 'integration/model/sambanova',
    accountType: 'provider-account/sambanova',
    apiKeyEnv: 'SAMBANOVA_API_KEY',
    smokeModel: 'Meta-Llama-3.3-70B-Instruct',
  },
  ai21: {
    sdkProvider: 'ai21',
    modelIntegrationType: 'integration/model/ai21',
    accountType: 'provider-account/ai21',
    apiKeyEnv: 'AI21_API_KEY',
  },
  cohere: {
    sdkProvider: 'cohere',
    modelIntegrationType: 'integration/model/cohere',
    accountType: 'provider-account/cohere',
    apiKeyEnv: 'COHERE_API_KEY',
    smokeModel: 'command-r-08-2024',
  },
  'google-gemini': {
    sdkProvider: 'google-gemini',
    modelIntegrationType: 'integration/model/gemini',
    accountType: 'provider-account/google-gemini',
    apiKeyEnv: 'GOOGLE_GEMINI_API_KEY',
    authKeyField: 'apiKey',
    smokeModel: 'gemini-3.8-flash',
  },
  'google-vertex': {
    sdkProvider: 'google-vertex',
    modelIntegrationType: 'integration/model/vertex',
    accountType: 'provider-account/google-vertex',
    apiKeyEnv: 'VERTEX_KEY_FILE',
    authType: 'key-file',
    region: 'global',
    modelPrefixRegions: { 'meta/': 'us-east5' },
    smokeModel: 'anthropic/claude-haiku-4-5',
  },
  'aws-bedrock': {
    sdkProvider: 'aws-bedrock',
    modelIntegrationType: 'integration/model/bedrock',
    accountType: 'provider-account/aws-bedrock',
    apiKeyEnv: 'AWS_BEDROCK_API_KEY',
    region: 'us-east-1',
    modelPrefixRegions: {
      'in.': 'ap-south-1',
      'eu.': 'eu-west-1',
      'ca.': 'ca-central-1',
      'au.': 'ap-southeast-2',
    },
    smokeModel: 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
  },
  'aws-bedrock-mantle': {
    sdkProvider: 'aws-bedrock-mantle',
    modelIntegrationType: 'integration/model/bedrock-mantle',
    accountType: 'provider-account/aws-bedrock-mantle',
    apiKeyEnv: 'AWS_BEDROCK_MANTLE_API_KEY',
    region: 'us-east-1',
    smokeModel: 'anthropic.claude-haiku-4-5',
  },
  databricks: {
    sdkProvider: 'databricks',
    modelIntegrationType: 'integration/model/databricks',
    accountType: 'provider-account/databricks',
    apiKeyEnv: 'DATABRICKS_API_KEY',
    accountEnv: { base_url: 'DATABRICKS_BASE_URL' },
    smokeModel: 'databricks-meta-llama-3-1-8b-instruct',
  },
  'microsoft-foundry': {
    sdkProvider: 'microsoft-foundry',
    modelIntegrationType: 'integration/model/microsoft-foundry',
    accountType: 'provider-account/microsoft-foundry',
    apiKeyEnv: 'MICROSOFT_FOUNDRY_API_KEY',
    accountEnv: {
      openai_endpoint: 'MICROSOFT_FOUNDRY_OPENAI_ENDPOINT',
      project_endpoint: 'MICROSOFT_FOUNDRY_PROJECT_ENDPOINT',
    },
    smokeModel: 'gpt-5.6-luna',
  },
  wafer: {
    sdkProvider: 'wafer',
    modelIntegrationType: 'integration/model/wafer',
    accountType: 'provider-account/wafer',
    apiKeyEnv: 'WAFER_API_KEY',
    smokeModel: 'DeepSeek-V4-Flash-0423',
  },
  typesafe: {
    sdkProvider: 'typesafe',
    modelIntegrationType: 'integration/model/typesafe',
    accountType: 'provider-account/typesafe',
    apiKeyEnv: 'TYPESAFE_API_KEY',
    smokeModel: 'jev-1.13.0',
  },
  elevenlabs: {
    sdkProvider: 'elevenlabs',
    modelIntegrationType: 'integration/model/elevenlabs',
    accountType: 'provider-account/elevenlabs',
    apiKeyEnv: 'ELEVENLABS_API_KEY',
    smokeModel: 'eleven_flash_v2_5',
  },
  deepgram: {
    sdkProvider: 'deepgram',
    modelIntegrationType: 'integration/model/deepgram',
    accountType: 'provider-account/deepgram',
    apiKeyEnv: 'DEEPGRAM_API_KEY',
    smokeModel: 'aura-2-thalia-en',
  },
  'fireworks-ai': {
    sdkProvider: 'fireworks-ai',
    modelIntegrationType: 'integration/model/fireworks-ai',
    accountType: 'provider-account/fireworks-ai',
    apiKeyEnv: 'FIREWORKS_AI_API_KEY',
    smokeModel: 'accounts/fireworks/models/gpt-oss-120b',
  },
  'truefoundry-managed': {
    sdkProvider: 'truefoundry-managed',
    modelIntegrationType: 'integration/model/truefoundry-managed',
    accountType: 'provider-account/truefoundry-managed',
    apiKeyEnv: 'TRUEFOUNDRY_MANAGED_API_KEY',
    accountEnv: { base_url: 'TRUEFOUNDRY_MANAGED_BASE_URL' },
    modelIdPrefix: 'tfy-managed/',
    smokeModel: 'gpt-oss-120b',
  },
};

/** project_id from a Google service-account JSON string (Vertex key-file secret). */
export function projectIdFromKeyFile(raw: string): string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error('key-file credential is not valid JSON');
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('key-file credential must be a JSON object');
  }
  const projectId = (parsed as { project_id?: unknown }).project_id;
  if (typeof projectId !== 'string' || !projectId) {
    throw new Error('key-file credential JSON missing project_id');
  }
  return projectId;
}

export function missingAccountEnv(spec: ProviderSpec): string | undefined {
  for (const envName of Object.values(spec.accountEnv ?? {})) {
    if (!process.env[envName]) return envName;
  }
  return undefined;
}

export function getProviderSpec(providerDir: string): ProviderSpec | undefined {
  return SPECS[providerDir];
}

export function listRegisteredProviders(): string[] {
  return Object.keys(SPECS);
}

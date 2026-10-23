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
  /** Account manifest fields whose values come from env (Databricks base_url, Foundry endpoints). */
  accountEnv?: Record<string, string>;
};

const SPECS: Record<string, ProviderSpec> = {
  openai: {
    sdkProvider: 'openai',
    modelIntegrationType: 'integration/model/openai',
    accountType: 'provider-account/openai',
    apiKeyEnv: 'OPENAI_API_KEY',
    baseUrl: 'https://api.openai.com/v1',
  },
  anthropic: {
    sdkProvider: 'anthropic',
    modelIntegrationType: 'integration/model/anthropic',
    accountType: 'provider-account/anthropic',
    apiKeyEnv: 'ANTHROPIC_API_KEY',
    baseUrl: 'https://api.anthropic.com/v1',
  },
  groq: {
    sdkProvider: 'groq',
    modelIntegrationType: 'integration/model/groq',
    accountType: 'provider-account/groq',
    apiKeyEnv: 'GROQ_API_KEY',
  },
  xai: {
    sdkProvider: 'xai',
    modelIntegrationType: 'integration/model/xai',
    accountType: 'provider-account/xai',
    apiKeyEnv: 'XAI_API_KEY',
    baseUrl: 'https://api.x.ai/v1',
  },
  cerebras: {
    sdkProvider: 'cerebras',
    modelIntegrationType: 'integration/model/cerebras',
    accountType: 'provider-account/cerebras',
    apiKeyEnv: 'CEREBRAS_API_KEY',
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
  },
  'mistral-ai': {
    sdkProvider: 'mistral-ai',
    modelIntegrationType: 'integration/model/mistral-ai',
    accountType: 'provider-account/mistral-ai',
    apiKeyEnv: 'MISTRAL_AI_API_KEY',
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
  },
  'google-gemini': {
    sdkProvider: 'google-gemini',
    modelIntegrationType: 'integration/model/gemini',
    accountType: 'provider-account/google-gemini',
    apiKeyEnv: 'GOOGLE_GEMINI_API_KEY',
    authKeyField: 'apiKey',
  },
  'google-vertex': {
    sdkProvider: 'google-vertex',
    modelIntegrationType: 'integration/model/vertex',
    accountType: 'provider-account/google-vertex',
    apiKeyEnv: 'VERTEX_KEY_FILE',
    authType: 'key-file',
    region: 'europe-west4',
  },
  'aws-bedrock': {
    sdkProvider: 'aws-bedrock',
    modelIntegrationType: 'integration/model/bedrock',
    accountType: 'provider-account/aws-bedrock',
    apiKeyEnv: 'AWS_BEDROCK_API_KEY',
    region: 'us-east-1',
  },
  'aws-bedrock-mantle': {
    sdkProvider: 'aws-bedrock-mantle',
    modelIntegrationType: 'integration/model/bedrock-mantle',
    accountType: 'provider-account/aws-bedrock-mantle',
    apiKeyEnv: 'AWS_BEDROCK_MANTLE_API_KEY',
    region: 'us-east-1',
  },
  databricks: {
    sdkProvider: 'databricks',
    modelIntegrationType: 'integration/model/databricks',
    accountType: 'provider-account/databricks',
    apiKeyEnv: 'DATABRICKS_API_KEY',
    accountEnv: { base_url: 'DATABRICKS_BASE_URL' },
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

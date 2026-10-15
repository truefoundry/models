/** API-key providers the harness can call. Unlisted providers fail the PR check. */
export type ProviderSpec = {
  /** SDK Providers index + modelConfig key (matches models-repo directory for these). */
  sdkProvider: string;
  modelIntegrationType: string;
  accountType: string;
  /** Env var holding the API key GitHub secret. */
  apiKeyEnv: string;
  baseUrl?: string;
  /** auth_data field name; default api_key (Gemini uses apiKey). */
  authKeyField?: 'api_key' | 'apiKey';
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
    baseUrl: 'https://api.anthropic.com',
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
};

export function getProviderSpec(providerDir: string): ProviderSpec | undefined {
  return SPECS[providerDir];
}

/** Registered provider directory names (models-repo `providers/<name>/`). */
export function listRegisteredProviders(): string[] {
  return Object.keys(SPECS);
}

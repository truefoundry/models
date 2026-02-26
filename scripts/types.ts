// --- Costs ---

export interface PricingTier {
  from: number;
  cost_per_token: number;
}

export interface TieredPricing {
  input?: PricingTier[];
  output?: PricingTier[];
  cache_read?: PricingTier[];
  cache_write?: PricingTier[];
}

export interface Cost {
  input_cost_per_token?: number;
  output_cost_per_token?: number;
  cache_read_input_token_cost?: number;
  cache_creation_input_token_cost?: number;
  input_cost_per_token_batches?: number;
  output_cost_per_token_batches?: number;
  input_cost_per_audio_token?: number;
  output_cost_per_audio_token?: number;
  cache_creation_input_audio_token_cost?: number;
  input_cost_per_request?: number;
  input_cost_per_character?: number;
  input_cost_per_second?: number;
  output_cost_per_second?: number;
  input_cost_per_query?: number;
  input_cost_per_image?: number;
  output_cost_per_image?: number;
  tiered_pricing?: TieredPricing;
}

export interface CostWithRegion extends Cost {
  region: string;
}

// --- Limits ---

export interface Limits {
  context_window?: number;
  max_tokens?: number;
  max_input_tokens?: number;
  max_output_tokens?: number;
  max_query_tokens?: number;
  output_vector_size?: number;
  tool_use_system_prompt_tokens?: number;
}

// --- Params ---

export interface ParamConfig {
  key: string;
  defaultValue?: any;
  minValue?: number;
  maxValue?: number;
  type?: string;
  options?: any[];
  skipValues?: Array<string | number | boolean | null>;
  rule?: Record<string, any>;
  properties?: Record<string, any>;
}

// --- Features ---

export type Feature =
  | 'function_calling'
  | 'parallel_function_calling'
  | 'vision'
  | 'audio_input'
  | 'audio_output'
  | 'chat'
  | 'image'
  | 'pdf'
  | 'doc'
  | 'cache_control'
  | 'tool_choice'

// --- Messages ---

export interface MessageConfig {
  options: string[];
}

// --- Default provider config (from default.yaml) ---

export interface DefaultProviderParams {
  params?: ParamConfig[];
  messages?: MessageConfig;
  type?: {
    primary?: string;
    supported?: string[];
  };
}

// --- Model config ---

export interface ModelData {
  model: string;
  costs?: CostWithRegion[];
  limits?: Limits;
  features?: Feature[];
  messages?: MessageConfig;
  params?: ParamConfig[];
  removeParams?: string[];
  requiredParams?: string[];
  mode?: string;
  thinking?: boolean;
  isDeprecated?: boolean;
  sources?: string[];
}

export interface UnifiedModelConfig {
  provider: string;
  defaultProviderParams: DefaultProviderParams;
  model: string;
  costs?: CostWithRegion[];
  limits: Limits;
  features: Feature[];
  messages?: MessageConfig;
  params: ParamConfig[];
  removeParams: string[];
  requiredParams: string[];
  mode: string;
  thinking: boolean;
  isDeprecated: boolean;
  sources: string[];
}

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

export interface CostObj {
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
  tiered_pricing?: TieredPricing;
}

export interface CostObjWithRegion extends CostObj {
  region?: string;
}

export interface CostWithSupportedRegions extends CostObj {
  supported_regions?: string[];
}

export type Costs = CostObjWithRegion[] | CostWithSupportedRegions;

// --- Limits ---

export interface Limits {
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
  | 'cache_control';

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
  is_deprecated?: boolean;
  costs?: Costs;
  limits?: Limits;
  features?: Feature[];
  params?: ParamConfig[];
  messages?: MessageConfig;
  removeParams?: string[];
  defaultRegion?: string;
  mode?: string;
  original_provider?: string;
  requiredParams?: string[];
}

export interface UnifiedModelConfig {
  provider: string;
  model: string;
  is_deprecated: boolean;
  costs?: Costs;
  limits: Limits;
  features: Feature[];
  params: ParamConfig[];
  messages?: MessageConfig;
  defaultProviderParams: DefaultProviderParams;
  removeParams: string[];
  defaultRegion: string;
  mode: string;
  original_provider: string;
  requiredParams: string[];
}

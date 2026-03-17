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

export type ParamKey =
  | 'max_tokens'
  | 'max_completion_tokens'
  | 'temperature'
  | 'top_p'
  | 'top_k'
  | 'response_format'
  | 'json_schema'
  | 'reasoning_effort'
  | 'verbosity'
  | 'reasoning'
  | 'thinking'
  | 'tool_choice'
  | 'stream'
  | 'stop'
  | 'n'
  | 'seed'
  | 'min_tokens'
  | 'parallel_tool_calls';

export type ParamType = 'string' | 'boolean' | 'array-of-strings' | 'json' | 'number';

export interface ParamConfig {
  key: ParamKey;
  defaultValue?: string | number | boolean | null;
  minValue?: number;
  maxValue?: number;
  type?: ParamType;
}

// --- Features ---

export type Feature =
  | 'function_calling'
  | 'parallel_function_calling'
  | 'chat'
  | 'cache_control'
  | 'system_messages'
  | 'tool_choice'
  | 'prompt_caching'
  | 'structured_output'
  | 'assistant_prefill'
  | 'tools'
  | 'code_execution';

// --- Modes ---

export type Mode =
  | 'completion'
  | 'embedding'
  | 'rerank'
  | 'realtime'
  | 'audio_transcription'
  | 'audio_translation'
  | 'text_to_speech'
  | 'moderation'
  | 'image'
  | 'video'
  | 'proxy'
  | 'unknown';

// --- Modalities ---

export type Modality = 'text' | 'image' | 'audio' | 'pdf' | 'doc' | 'code' | 'video';

export interface Modalities {
  input?: Modality[];
  output?: Modality[];
}

// --- Messages ---

export type MessageOption = 'system' | 'user' | 'assistant' | 'developer';

export interface MessageConfig {
  options: MessageOption[];
}

// --- Default provider config (from default.yaml) ---

export interface DefaultProviderParams {
  params?: ParamConfig[];
  messages?: MessageConfig;
}

// --- Model config ---

export interface ModelData {
  model: string;
  costs?: CostWithRegion[];
  limits?: Limits;
  features?: Feature[];
  modalities?: Modalities;
  messages?: MessageConfig;
  params?: ParamConfig[];
  removeParams?: ParamKey[];
  requiredParams?: ParamKey[];
  mode?: Mode;
  thinking?: boolean;
  isDeprecated?: boolean;
  deprecationDate?: string;
  sources?: string[];
  supportedModes?: Mode[];
}

export interface UnifiedModelConfig {
  provider: string;
  defaultProviderParams: DefaultProviderParams;
  model: string;
  costs?: CostWithRegion[];
  limits: Limits;
  features: Feature[];
  modalities?: Modalities;
  messages?: MessageConfig;
  params: ParamConfig[];
  removeParams: ParamKey[];
  requiredParams: ParamKey[];
  mode: Mode;
  thinking: boolean;
  isDeprecated: boolean;
  deprecationDate?: string;
  sources: string[];
  supportedModes?: Mode[];
}

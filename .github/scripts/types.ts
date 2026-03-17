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
  cache_read_input_audio_token_cost?: number;
  cache_creation_input_audio_token_cost?: number;
  cache_storage_cost_per_token_per_hour?: number;
  input_cost_per_request?: number;
  input_cost_per_character?: number;
  input_cost_per_second?: number;
  output_cost_per_second?: number;
  input_cost_per_query?: number;
  input_cost_per_image?: number;
  output_cost_per_image?: number;
  input_cost_per_image_token?: number;
  output_cost_per_image_token?: number;
  input_cost_per_video_token?: number;
  output_cost_per_video_token?: number;
  input_cost_per_page?: number;
  input_cost_per_annotated_page?: number;
  tiered_pricing?: TieredPricing;
  // Resolution-based pricing (e.g. output_cost_per_second_1080p, output_cost_per_image_4k)
  [key: string]: number | TieredPricing | string | undefined;
}

export type AWSRegion =
  | 'af-south-1' | 'ap-east-1' | 'ap-east-2' | 'ap-northeast-1' | 'ap-northeast-2' | 'ap-northeast-3'
  | 'ap-south-1' | 'ap-south-2' | 'ap-southeast-1' | 'ap-southeast-2' | 'ap-southeast-3' | 'ap-southeast-4'
  | 'ap-southeast-5' | 'ap-southeast-6' | 'ap-southeast-7' | 'ca-central-1' | 'ca-west-1'
  | 'cn-north-1' | 'cn-northwest-1' | 'eu-central-1' | 'eu-central-2' | 'eu-north-1'
  | 'eu-south-1' | 'eu-south-2' | 'eu-west-1' | 'eu-west-2' | 'eu-west-3' | 'il-central-1'
  | 'me-central-1' | 'me-south-1' | 'mx-central-1' | 'sa-east-1'
  | 'us-east-1' | 'us-east-2' | 'us-gov-east-1' | 'us-gov-west-1' | 'us-west-1' | 'us-west-2';

export type GCPRegion =
  | 'global'
  | 'northamerica-northeast1' | 'northamerica-northeast2'
  | 'southamerica-east1'
  | 'us-central1' | 'us-east1' | 'us-east4' | 'us-east5' | 'us-south1' | 'us-west1' | 'us-west2' | 'us-west3' | 'us-west4'
  | 'asia-east1' | 'asia-east2' | 'asia-northeast1' | 'asia-northeast2' | 'asia-northeast3'
  | 'asia-south1' | 'asia-south2' | 'asia-southeast1' | 'asia-southeast2'
  | 'australia-southeast1' | 'australia-southeast2'
  | 'europe-central2' | 'europe-north1' | 'europe-southwest1'
  | 'europe-west1' | 'europe-west2' | 'europe-west3' | 'europe-west4' | 'europe-west6' | 'europe-west8' | 'europe-west9'
  | 'me-central1' | 'me-central2' | 'me-west1';

export interface CostWithRegion extends Cost {
  region: '*' | AWSRegion | GCPRegion;
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
  options?: MessageOption[];
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
  mode: Mode;
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

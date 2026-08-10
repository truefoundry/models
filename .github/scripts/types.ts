import type * as Generated from './autogen/types';

export interface UnifiedModelConfig extends Generated.ModelConfig {
  defaultProviderParams?: Generated.DefaultConfig;
  provider: string;
}

export type UnifiedProviderConfig = Generated.ProviderConfig;

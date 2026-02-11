import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';
import { ModelData, UnifiedModelConfig, DefaultProviderParams } from './types';

const PROVIDERS_DIR = path.resolve(__dirname, '..', 'providers');
const OUTPUT_DIR = path.resolve(__dirname, '..', 'dist');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'ai-models.json');

function collectModelFiles(dir: string): string[] {
  const results: string[] = [];

  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectModelFiles(fullPath));
    } else if (
      entry.isFile() &&
      entry.name.endsWith('.yaml') &&
      entry.name !== 'default.yaml'
    ) {
      results.push(fullPath);
    }
  }

  return results;
}

function buildUnifiedConfig(
  modelData: ModelData,
  providerName: string,
  defaultProviderParams: DefaultProviderParams,
): UnifiedModelConfig {
  return {
    provider: providerName,
    model: modelData.model,
    is_deprecated: modelData.is_deprecated || false,
    costs: modelData.costs,
    limits: modelData.limits || {},
    features: modelData.features || [],
    params: modelData.params || [],
    messages: modelData.messages || undefined,
    defaultProviderParams,
    removeParams: modelData.removeParams || [],
    defaultRegion: modelData.defaultRegion || '',
    mode: modelData.mode || '',
    original_provider: modelData.original_provider || providerName,
    requiredParams: modelData.requiredParams || [],
  };
}

function main(): void {
  const configs: UnifiedModelConfig[] = [];

  const providerDirs = fs
    .readdirSync(PROVIDERS_DIR, { withFileTypes: true })
    .filter((e: fs.Dirent) => e.isDirectory());

  console.log(`Found ${providerDirs.length} providers`);

  for (const providerEntry of providerDirs) {
    const providerName = providerEntry.name;
    const providerPath = path.join(PROVIDERS_DIR, providerName);

    let defaultProviderParams: DefaultProviderParams = {};
    const defaultYamlPath = path.join(providerPath, 'default.yaml');
    if (fs.existsSync(defaultYamlPath)) {
      defaultProviderParams = yaml.load(
        fs.readFileSync(defaultYamlPath, 'utf-8'),
      ) as DefaultProviderParams;
    }

    const modelFiles = collectModelFiles(providerPath);

    for (const modelFilePath of modelFiles) {
      try {
        const modelData = yaml.load(
          fs.readFileSync(modelFilePath, 'utf-8'),
        ) as ModelData;
        configs.push(
          buildUnifiedConfig(modelData, providerName, defaultProviderParams),
        );
      } catch (err) {
        console.warn(`Warning: failed to parse ${modelFilePath}: ${err}`);
      }
    }

    console.log(`  ${providerName}: ${modelFiles.length} models`);
  }

  configs.sort((a, b) => {
    if (a.provider === b.provider) {
      return a.model.localeCompare(b.model);
    }
    return a.provider.localeCompare(b.provider);
  });

  if (!fs.existsSync(OUTPUT_DIR)) {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  }

  const json = JSON.stringify(configs, null, 2);
  fs.writeFileSync(OUTPUT_FILE, json, 'utf-8');

  console.log(`\nWrote ${configs.length} models to ${OUTPUT_FILE}`);
}

main();

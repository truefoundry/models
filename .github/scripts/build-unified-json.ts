import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';
import { DefaultConfig, ModelConfig } from './autogen/types';
import { NON_MODEL_YAML } from './constants';
import { UnifiedModelConfig } from './types';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const PROVIDERS_DIR = path.join(REPO_ROOT, 'providers');
const OUTPUT_DIR = path.join(REPO_ROOT, 'dist');
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
      !NON_MODEL_YAML.has(entry.name)
    ) {
      results.push(fullPath);
    }
  }

  return results;
}

function buildUnifiedConfig(
  modelData: ModelConfig,
  providerName: string,
  defaultProviderParams: DefaultConfig,
): UnifiedModelConfig {
  return {
    ...modelData,
    provider: providerName,
    defaultProviderParams,
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

    let defaultProviderParams: DefaultConfig = {};
    const defaultYamlPath = path.join(providerPath, 'default.yaml');
    if (fs.existsSync(defaultYamlPath)) {
      defaultProviderParams = yaml.load(
        fs.readFileSync(defaultYamlPath, 'utf-8'),
      ) as DefaultConfig;
    }

    const modelFiles = collectModelFiles(providerPath);

    for (const modelFilePath of modelFiles) {
      try {
        const modelData = yaml.load(
          fs.readFileSync(modelFilePath, 'utf-8'),
        ) as ModelConfig;
        if (!modelData.costs || modelData.costs.length === 0) continue;
        // TODO: revert — temporarily skipping google-vertex google/ models with unsupported modes
        const SKIPPED_VERTEX_MODES = new Set(['text_to_speech', 'audio_transcription', 'audio_translation', 'realtime']);
        if (providerName === 'google-vertex' && modelData.model.startsWith('google/') && SKIPPED_VERTEX_MODES.has(modelData.mode)) continue;
        configs.push(
          buildUnifiedConfig(modelData, providerName, defaultProviderParams),
        );

        // Anthropic models are also available through the AWS Claude platform,
        // so emit an exact copy under the aws-claude-platform provider.
        if (providerName === 'anthropic') {
          configs.push(
            buildUnifiedConfig(
              modelData,
              'aws-claude-platform',
              defaultProviderParams,
            ),
          );
        }
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

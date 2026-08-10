import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';
import { PROVIDER_CONFIG_YAML } from './constants';
import { UnifiedProviderConfig } from './types';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const PROVIDERS_DIR = path.join(REPO_ROOT, 'providers');
const OUTPUT_DIR = path.join(REPO_ROOT, 'dist');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'provider-configs.json');

function main(): void {
  // Keyed by provider directory name. Providers without a provider-config.yaml
  // are absent rather than `{}` — an empty config is a meaningful value
  // downstream (e.g. "drop every anthropic-beta token").
  const configs: Record<string, UnifiedProviderConfig> = {};

  const providerDirs = fs
    .readdirSync(PROVIDERS_DIR, { withFileTypes: true })
    .filter((e: fs.Dirent) => e.isDirectory())
    .map((e: fs.Dirent) => e.name)
    .sort((a: string, b: string) => a.localeCompare(b));

  console.log(`Found ${providerDirs.length} providers`);

  for (const providerName of providerDirs) {
    const configPath = path.join(
      PROVIDERS_DIR,
      providerName,
      PROVIDER_CONFIG_YAML,
    );
    if (!fs.existsSync(configPath)) continue;

    try {
      const providerConfig = yaml.load(
        fs.readFileSync(configPath, 'utf-8'),
      ) as UnifiedProviderConfig | null | undefined;
      if (!providerConfig) {
        console.warn(`Warning: ${configPath} is empty; skipping`);
        continue;
      }
      configs[providerName] = providerConfig;
      console.log(`  ${providerName}: ${PROVIDER_CONFIG_YAML}`);
    } catch (err) {
      console.warn(`Warning: failed to parse ${configPath}: ${err}`);
    }
  }

  if (!fs.existsSync(OUTPUT_DIR)) {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  }

  const json = JSON.stringify(configs, null, 2);
  fs.writeFileSync(OUTPUT_FILE, json, 'utf-8');

  console.log(
    `\nWrote ${Object.keys(configs).length} provider configs to ${OUTPUT_FILE}`,
  );
}

main();

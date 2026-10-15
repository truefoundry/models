/**
 * PR targeting: map changed YAML paths → catalogue model ids.
 *
 * Flow:
 *   "providers/openai/gpt-4o.yaml"
 *     → parseProviderModelPath → { provider: "openai" }
 *     → modelIdFromYamlFile    → "gpt-4o"  (from YAML `model:` field)
 */
import fs from 'node:fs';
import path from 'node:path';
import yaml from 'js-yaml';

const NON_MODEL_FILES = new Set(['default.yaml', 'provider-config.yaml']);

export type ChangedModel = { provider: string };

/**
 * Parse a repo-relative model YAML path.
 *
 *   "providers/openai/gpt-4o.yaml"          → { provider: "openai" }
 *   "providers/anthropic/claude-haiku-5-5.yaml" → { provider: "anthropic" }
 *   "providers/openai/default.yaml"         → undefined  (not a model)
 *   "providers/openai/provider-config.yaml" → undefined
 *   "README.md"                             → undefined
 */
export function parseProviderModelPath(filePath: string): ChangedModel | undefined {
  if (!filePath.startsWith('providers/') || !filePath.endsWith('.yaml')) return undefined;
  if (NON_MODEL_FILES.has(path.basename(filePath))) return undefined;

  // "openai/gpt-4o.yaml" → provider "openai", stem "gpt-4o"
  const relative = filePath.slice('providers/'.length);
  const slash = relative.indexOf('/');
  if (slash <= 0) return undefined;

  const provider = relative.slice(0, slash);
  const fileStem = relative.slice(slash + 1, -'.yaml'.length);
  if (!fileStem) return undefined;

  return { provider };
}

/**
 * Read catalogue model id from YAML on disk.
 *
 *   repoRoot + "providers/openai/gpt-4o.yaml"
 *     (file contains `model: gpt-4o`) → "gpt-4o"
 *   missing file or no `model:` field → undefined
 */
export function modelIdFromYamlFile(repoRoot: string, filePath: string): string | undefined {
  const abs = path.join(repoRoot, filePath);
  if (!fs.existsSync(abs)) return undefined;
  const data = yaml.load(fs.readFileSync(abs, 'utf8')) as { model?: string } | null;
  return data?.model;
}

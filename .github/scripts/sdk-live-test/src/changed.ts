/**
 * PR targeting: map changed YAML paths → catalogue model ids.
 *
 * Example: providers/openai/gpt-4o.yaml → provider openai, model from YAML `model:`.
 */
import fs from 'node:fs';
import path from 'node:path';
import yaml from 'js-yaml';

const NON_MODEL = new Set(['default.yaml', 'provider-config.yaml']);

export type ChangedModel = { provider: string; modelFileStem: string; path: string };

export function parseProviderModelPath(filePath: string): ChangedModel | undefined {
  if (!filePath.startsWith('providers/') || !filePath.endsWith('.yaml')) return undefined;
  const base = path.basename(filePath);
  if (NON_MODEL.has(base)) return undefined;
  const rel = filePath.slice('providers/'.length);
  const slash = rel.indexOf('/');
  if (slash < 0) return undefined;
  const provider = rel.slice(0, slash);
  const modelFileStem = rel.slice(slash + 1, -'.yaml'.length);
  if (!provider || !modelFileStem) return undefined;
  return { provider, modelFileStem, path: filePath };
}

/** Catalogue `model:` id from a YAML file on disk. */
export function modelIdFromYamlFile(repoRoot: string, filePath: string): string | undefined {
  const abs = path.join(repoRoot, filePath);
  if (!fs.existsSync(abs)) return undefined;
  const data = yaml.load(fs.readFileSync(abs, 'utf8')) as { model?: string } | null;
  return data?.model;
}

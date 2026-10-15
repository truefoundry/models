#!/usr/bin/env node
/**
 * CLI entry for SDK live checks.
 *
 * Modes:
 *   --smoke-with-secrets
 *     One cheap chat model per providers.ts entry whose API key env is set.
 *     Example: OPENAI_API_KEY set → openai/gpt-4o-mini (baseline only).
 *
 *   --model provider/modelId …
 *     Explicit targets. Example: --model anthropic/claude-haiku-5-5
 *
 *   --files-list changed.txt [--base-dir /tmp/base]
 *     PR path: each providers/<p>/<file>.yaml with a significant YAML delta.
 *     Example line: providers/openai/gpt-4o.yaml → full scenario matrix for that model.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadCatalogue } from './catalogue.js';
import {
  isSignificantYamlChange,
  modelIdFromYamlFile,
  parseProviderModelPath,
} from './changed.js';
import { runTargets, type Target } from './run.js';
import { targetsWithSecrets } from './smoke.js';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

function parseArgs(argv: string[]) {
  let catalogue = path.join(REPO_ROOT, 'dist/ai-models.json');
  let filesList: string | undefined;
  let baseDir: string | undefined;
  let smokeWithSecrets = false;
  const models: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--catalogue') catalogue = path.resolve(argv[++i]!);
    else if (a === '--files-list') filesList = path.resolve(argv[++i]!);
    else if (a === '--base-dir') baseDir = path.resolve(argv[++i]!);
    else if (a === '--model') models.push(argv[++i]!);
    else if (a === '--smoke-with-secrets') smokeWithSecrets = true;
    else if (a === '--help' || a === '-h') {
      console.log(`Usage:
  tsx src/index.ts --catalogue dist/ai-models.json --model openai/gpt-4o
  tsx src/index.ts --catalogue dist/ai-models.json --smoke-with-secrets
  tsx src/index.ts --files-list changed.txt [--base-dir /tmp/base-checkout]
`);
      process.exit(0);
    }
  }
  return { catalogue, filesList, baseDir, models, smokeWithSecrets };
}

function targetsFromModelFlags(flags: string[]): Target[] {
  return flags.map((f) => {
    const slash = f.indexOf('/');
    if (slash < 0) throw new Error(`--model expects provider/modelId, got ${f}`);
    return { provider: f.slice(0, slash), modelId: f.slice(slash + 1) };
  });
}

function targetsFromFilesList(listPath: string, baseDir: string | undefined): Target[] {
  const lines = fs
    .readFileSync(listPath, 'utf8')
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
  const out: Target[] = [];
  for (const filePath of lines) {
    const parsed = parseProviderModelPath(filePath);
    if (!parsed) continue;
    const after = fs.readFileSync(path.join(REPO_ROOT, filePath), 'utf8');
    const before =
      baseDir && fs.existsSync(path.join(baseDir, filePath))
        ? fs.readFileSync(path.join(baseDir, filePath), 'utf8')
        : null;
    // Cost-only edits are skipped; features/mode/params changes run live.
    if (!isSignificantYamlChange(before, after)) {
      console.log(`skip insignificant: ${filePath}`);
      continue;
    }
    const modelId = modelIdFromYamlFile(REPO_ROOT, filePath);
    if (!modelId) {
      console.warn(`skip (no model: field): ${filePath}`);
      continue;
    }
    out.push({ provider: parsed.provider, modelId });
  }
  return out;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!fs.existsSync(args.catalogue)) {
    console.error(`Catalogue missing: ${args.catalogue} (run npm run build:json)`);
    process.exit(2);
  }

  let targets: Target[] = [];
  if (args.smokeWithSecrets) {
    targets = targetsWithSecrets(loadCatalogue(args.catalogue));
  } else if (args.models.length) {
    targets = targetsFromModelFlags(args.models);
  } else if (args.filesList) {
    targets = targetsFromFilesList(args.filesList, args.baseDir);
  } else {
    console.error('Pass --smoke-with-secrets, --model provider/id, and/or --files-list');
    process.exit(2);
  }

  if (targets.length === 0) {
    console.log('No models to test.');
    process.exit(0);
  }

  console.log(`Testing ${targets.length} model(s) via @truefoundry/ai-gateway-sdk`);
  const results = await runTargets(args.catalogue, targets, {
    baselineOnly: args.smokeWithSecrets,
  });
  let failed = 0;
  for (const r of results) {
    const line = `${r.status.toUpperCase()} ${r.provider}/${r.modelId} ${r.scenario}: ${r.detail}`;
    console.log(line);
    if (r.status === 'fail') failed++;
  }

  if (failed > 0) {
    console.error(`\n${failed} scenario(s) failed`);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

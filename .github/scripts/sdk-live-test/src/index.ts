#!/usr/bin/env node
/**
 * CLI entry for SDK live checks.
 *
 * Modes:
 *   --smoke-with-secrets
 *     One chat model per providers.ts entry whose API key env is set.
 *     Example: OPENAI_API_KEY set → first openai chat row in catalogue (baseline only).
 *
 *   --model provider/modelId …
 *     Explicit targets. Example: --model anthropic/claude-haiku-5-5
 *
 *   --files-list changed.txt
 *     PR path: each providers/<p>/<file>.yaml in the list → full scenario matrix.
 *     Example line: providers/openai/gpt-4o.yaml
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadCatalogue } from './catalogue.js';
import { modelIdFromYamlFile, parseProviderModelPath } from './changed.js';
import { runTargets, type Target } from './run.js';
import { targetsWithSecrets } from './smoke.js';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

function parseArgs(argv: string[]) {
  let catalogue = path.join(REPO_ROOT, 'dist/ai-models.json');
  let filesList: string | undefined;
  let smokeWithSecrets = false;
  const models: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--catalogue') catalogue = path.resolve(argv[++i]!);
    else if (a === '--files-list') filesList = path.resolve(argv[++i]!);
    else if (a === '--model') models.push(argv[++i]!);
    else if (a === '--smoke-with-secrets') smokeWithSecrets = true;
    else if (a === '--help' || a === '-h') {
      console.log(`Usage:
  tsx src/index.ts --model openai/gpt-4o
  tsx src/index.ts --smoke-with-secrets
  tsx src/index.ts --files-list changed.txt
  # --catalogue defaults to <repo>/dist/ai-models.json; if set, use an absolute path
  # (relative paths resolve from process cwd, not repo root)
`);
      process.exit(0);
    }
  }
  return { catalogue, filesList, models, smokeWithSecrets };
}

function targetsFromModelFlags(flags: string[]): Target[] {
  return flags.map((f) => {
    const slash = f.indexOf('/');
    if (slash < 0) throw new Error(`--model expects provider/modelId, got ${f}`);
    return { provider: f.slice(0, slash), modelId: f.slice(slash + 1) };
  });
}

function targetsFromFilesList(listPath: string): Target[] {
  const out: Target[] = [];
  for (const line of fs.readFileSync(listPath, 'utf8').split('\n')) {
    const filePath = line.trim();
    if (!filePath) continue;
    const parsed = parseProviderModelPath(filePath);
    if (!parsed) continue;
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

  let targets: Target[];
  if (args.smokeWithSecrets) {
    targets = targetsWithSecrets(loadCatalogue(args.catalogue));
  } else if (args.models.length) {
    targets = targetsFromModelFlags(args.models);
  } else if (args.filesList) {
    targets = targetsFromFilesList(args.filesList);
  } else {
    console.error('Pass --smoke-with-secrets, --model provider/id, or --files-list');
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

  const failed = results.filter((r) => r.status === 'fail').length;
  const passed = results.length - failed;
  console.log(`\nDone: ${passed} passed, ${failed} failed (${results.length} scenario(s))`);
  if (failed > 0) {
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

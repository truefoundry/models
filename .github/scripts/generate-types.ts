/// <reference types="node" />
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';

const CUE_FILE = path.resolve(__dirname, '../test/model.cue');
const OUTPUT_DIR = path.resolve(__dirname, 'autogen');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'types.ts');

function main(): void {
  const openApiJson = execSync(`cue def --out openapi "${CUE_FILE}"`, {
    encoding: 'utf-8',
  });

  const openApi = JSON.parse(openApiJson);
  const schemaNames: string[] = Object.keys(openApi.components?.schemas ?? {});

  const tmpInput = path.join(os.tmpdir(), `model-openapi-${Date.now()}.json`);
  const tmpOutput = path.join(os.tmpdir(), `model-types-${Date.now()}.ts`);
  fs.writeFileSync(tmpInput, openApiJson, 'utf-8');

  try {
    const bin = path.resolve(__dirname, '../../node_modules/.bin/openapi-typescript');
    execSync(`"${bin}" "${tmpInput}" -o "${tmpOutput}" --alphabetize`, {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    const generated = fs.readFileSync(tmpOutput, 'utf-8');

    const reExports = schemaNames
      .map((name) => `export type ${name} = components['schemas']['${name}'];`)
      .join('\n');

    const output = [
      generated.trim(),
      '',
      reExports,
      '',
    ].join('\n');

    if (!fs.existsSync(OUTPUT_DIR)) {
      fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    }
    fs.writeFileSync(OUTPUT_FILE, output, 'utf-8');
    console.log(`Generated ${OUTPUT_FILE} (${output.split('\n').length} lines)`);
  } finally {
    for (const f of [tmpInput, tmpOutput]) {
      if (fs.existsSync(f)) fs.unlinkSync(f);
    }
  }
}

main();

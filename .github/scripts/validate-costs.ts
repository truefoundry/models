import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';

import type { CostWithRegion, ModelData } from './types';

const PROVIDERS_DIR = path.resolve(__dirname, '..', '..', 'providers');

function collectYamlFiles(dir: string): string[] {
    const results: string[] = [];

    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            results.push(...collectYamlFiles(fullPath));
        } else if (entry.isFile() && entry.name.endsWith('.yaml')) {
            results.push(fullPath);
        }
    }

    return results;
}

interface Violation {
    file: string;
    index: number;
    entry: CostWithRegion;
}

function validateFile(filePath: string): Violation[] {
    const content = fs.readFileSync(filePath, 'utf-8');
    const data = yaml.load(content) as ModelData | null;

    if (data == null || !Array.isArray(data.costs)) {
        return [];
    }

    const violations: Violation[] = [];

    for (let i = 0; i < data.costs.length; i++) {
        const entry = data.costs[i];
        const keyCount = Object.keys(entry).length;

        if (keyCount < 2) {
            violations.push({ file: filePath, index: i, entry });
        }
    }

    return violations;
}

function main(): void {
    const args = process.argv.slice(2);
    const files = args.length > 0
        ? args.filter((f) => f.endsWith('.yaml')).map((f) => path.resolve(f))
        : collectYamlFiles(PROVIDERS_DIR);

    const allViolations: Violation[] = [];

    for (const filePath of files) {
        allViolations.push(...validateFile(filePath));
    }

    if (allViolations.length === 0) {
        console.log(`Checked ${files.length} files — all cost entries are valid.`);
        process.exit(0);
    }

    console.error(`\nFound ${allViolations.length} cost entry violation(s) — each must have at least one pricing field beside region:\n`);

    for (const { file, index, entry } of allViolations) {
        const relativePath = path.relative(process.cwd(), file);
        console.error(`  ${relativePath}  [costs[${index}]]: ${JSON.stringify(entry)}`);
    }

    process.exit(1);
}

main();

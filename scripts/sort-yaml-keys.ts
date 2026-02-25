import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';

const PROVIDERS_DIR = path.resolve(__dirname, '..', 'providers');

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

function main(): void {
    const args = process.argv.slice(2);
    const files = args.length > 0
        ? args.filter((f) => f.endsWith('.yaml')).map((f) => path.resolve(f))
        : collectYamlFiles(PROVIDERS_DIR);
    let sortedCount = 0;

    for (const filePath of files) {
        const content = fs.readFileSync(filePath, 'utf-8');
        const data = yaml.load(content);

        if (data == null || typeof data !== 'object') {
            continue;
        }

        const sorted = yaml.dump(data, {
            sortKeys: true,
            indent: 4,
            lineWidth: 256,
            noRefs: true,
            quotingType: '"',
            forceQuotes: false,
        });

        if (sorted !== content) {
            fs.writeFileSync(filePath, sorted, 'utf-8');
            sortedCount++;
            console.log(`  Sorted: ${path.relative(PROVIDERS_DIR, filePath)}`);
        }
    }

    console.log(`\nProcessed ${files.length} files, sorted ${sortedCount}`);
}

main();

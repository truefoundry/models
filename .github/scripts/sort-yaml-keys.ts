import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';

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

function main(): void {
    const args = process.argv.slice(2);
    const files = args.length > 0
        ? args.filter((f) => f.endsWith('.yaml')).map((f) => path.resolve(f))
        : collectYamlFiles(PROVIDERS_DIR);
    const pendingWrites: Array<{ filePath: string; sorted: string; original: string }> = [];
    let sortedCount = 0;

    for (const filePath of files) {
        const content = fs.readFileSync(filePath, 'utf-8');
        let data: unknown;
        try {
            data = yaml.load(content);
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            throw new Error(`Failed to parse YAML file ${filePath}: ${message}`);
        }

        if (data == null || typeof data !== 'object') {
            continue;
        }

        const record = data as Record<string, unknown>;
        if (Array.isArray(record.costs)) {
            record.costs = [...record.costs].sort((a, b) => {
                const ra = String((a as Record<string, unknown>).region ?? '');
                const rb = String((b as Record<string, unknown>).region ?? '');
                return rb.localeCompare(ra);
            });
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
            pendingWrites.push({ filePath, sorted, original: content });
        }
    }

    for (const pending of pendingWrites) {
        if (pending.sorted !== pending.original) {
            fs.writeFileSync(pending.filePath, pending.sorted, 'utf-8');
            sortedCount++;
        }
    }

    console.log(`\nProcessed ${files.length} files, sorted ${sortedCount}`);
}

main();

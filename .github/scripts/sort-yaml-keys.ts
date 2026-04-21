import fs from 'fs';
import path from 'path';
import { parseDocument, isMap, isSeq, isScalar, YAMLMap, YAMLSeq, Pair, Scalar } from 'yaml';

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

function keyOf(pair: Pair): string {
    const k = pair.key;
    if (isScalar(k)) return String((k as Scalar).value ?? '');
    return String(k ?? '');
}

function sortMapKeys(node: YAMLMap): void {
    // Sort the map's pairs by key. Comments (commentBefore/comment) are
    // attached to the Pair / its key / its value nodes, so reordering the
    // items array preserves them automatically.
    node.items.sort((a, b) => keyOf(a).localeCompare(keyOf(b)));

    for (const pair of node.items) {
        const value = pair.value;
        if (isMap(value)) {
            sortMapKeys(value as YAMLMap);
        } else if (isSeq(value)) {
            sortSeqMapsRecursively(value as YAMLSeq);
        }
    }
}

function sortSeqMapsRecursively(seq: YAMLSeq): void {
    for (const item of seq.items) {
        if (isMap(item)) {
            sortMapKeys(item as YAMLMap);
        } else if (isSeq(item)) {
            sortSeqMapsRecursively(item as YAMLSeq);
        }
    }
}

function sortCostsByRegionDesc(root: YAMLMap): void {
    const costsPair = root.items.find((p) => keyOf(p) === 'costs');
    if (!costsPair) return;
    const costs = costsPair.value;
    if (!isSeq(costs)) return;

    (costs as YAMLSeq).items.sort((a, b) => {
        const ra = isMap(a) ? String(((a as YAMLMap).get('region') as unknown) ?? '') : '';
        const rb = isMap(b) ? String(((b as YAMLMap).get('region') as unknown) ?? '') : '';
        return rb.localeCompare(ra);
    });
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
        let doc;
        try {
            doc = parseDocument(content, { keepSourceTokens: true });
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            throw new Error(`Failed to parse YAML file ${filePath}: ${message}`);
        }

        if (doc.errors.length > 0) {
            const message = doc.errors.map((e) => e.message).join('; ');
            throw new Error(`Failed to parse YAML file ${filePath}: ${message}`);
        }

        const root = doc.contents;
        if (!isMap(root)) {
            continue;
        }

        sortCostsByRegionDesc(root as YAMLMap);
        sortMapKeys(root as YAMLMap);

        const sorted = doc.toString({ indent: 4, lineWidth: 256, doubleQuotedAsJSON: false });

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

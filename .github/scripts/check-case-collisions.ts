import { execSync } from 'child_process';
import path from 'path';

const REPO_ROOT = path.resolve(__dirname, '..', '..');

function getTrackedPaths(): string[] {
  const output = execSync('git ls-files', {
    cwd: REPO_ROOT,
    encoding: 'utf-8',
  });
  return output.split('\n').filter((line) => line.length > 0);
}

function findCaseCollisions(paths: string[]): string[][] {
  const byLowerCasePath = new Map<string, string[]>();

  for (const filePath of paths) {
    const key = filePath.toLowerCase();
    const group = byLowerCasePath.get(key);
    if (group) {
      group.push(filePath);
    } else {
      byLowerCasePath.set(key, [filePath]);
    }
  }

  return [...byLowerCasePath.values()].filter((group) => group.length > 1);
}

function main(): void {
  const paths = getTrackedPaths();
  const collisions = findCaseCollisions(paths);

  if (collisions.length > 0) {
    console.error(
      `Found ${collisions.length} path(s) that collide when compared case-insensitively:\n`,
    );
    for (const group of collisions) {
      console.error(`  - ${group.join('\n  - ')}`);
    }
    console.error(
      '\nTracked paths that differ only by letter case break `git clone`/`git checkout` on ' +
        'case-insensitive filesystems (macOS, Windows) and can make CI (Linux, case-sensitive) ' +
        'silently ship duplicate or divergent records for the same file. Rename or remove one ' +
        'path from each group above so every tracked path is unique case-insensitively.',
    );
    process.exit(1);
  }

  console.log(`Checked ${paths.length} tracked paths, no case collisions found.`);
}

main();

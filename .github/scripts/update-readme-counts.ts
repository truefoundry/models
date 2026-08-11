import fs from 'fs';
import path from 'path';
import { NON_MODEL_YAML } from './constants';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const PROVIDERS_DIR = path.join(REPO_ROOT, 'providers');
const README_PATH = path.join(REPO_ROOT, 'README.md');

interface ProviderMeta {
  name: string;
  description: string;
}

const PROVIDER_META: Record<string, ProviderMeta> = {
  'ai21': { name: 'AI21', description: 'Jamba models' },
  'anthropic': { name: 'Anthropic', description: 'Claude 3, Claude 3.5, Claude 4' },
  'aws-bedrock': { name: 'AWS Bedrock', description: 'Claude, Llama, Titan, Mistral on AWS' },
  'azure-ai-foundry': { name: 'Azure AI Foundry', description: 'Azure AI models' },
  'azure-open-ai': { name: 'Azure OpenAI', description: 'OpenAI models on Azure' },
  'cerebras': { name: 'Cerebras', description: 'Fast inference models' },
  'cohere': { name: 'Cohere', description: 'Command, Embed models' },
  'databricks': { name: 'Databricks', description: 'Databricks-hosted models' },
  'deepgram': { name: 'Deepgram', description: 'Speech-to-text and text-to-speech models' },
  'deepinfra': { name: 'DeepInfra', description: 'Open source model hosting' },
  'elevenlabs': { name: 'ElevenLabs', description: 'Voice synthesis and text-to-speech models' },
  'google-gemini': { name: 'Google Gemini', description: 'Gemini Pro, Ultra, Flash' },
  'google-vertex': { name: 'Google Vertex AI', description: 'Gemini, PaLM on GCP' },
  'groq': { name: 'Groq', description: 'Fast inference models' },
  'mistral-ai': { name: 'Mistral AI', description: 'Mistral, Mixtral, Codestral' },
  'openai': { name: 'OpenAI', description: 'GPT-4, GPT-4o, GPT-5, o1, o3, DALL-E, Whisper, TTS' },
  'openrouter': { name: 'OpenRouter', description: 'Unified API for open source models' },
  'perplexity-ai': { name: 'Perplexity', description: 'Search-augmented models' },
  'sambanova': { name: 'SambaNova', description: 'Enterprise AI models' },
  'together-ai': { name: 'Together AI', description: 'Open source model hosting' },
  'xai': { name: 'xAI', description: 'Grok models' },
};

function countModelFiles(dir: string): number {
  let count = 0;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      count += countModelFiles(fullPath);
    } else if (
      entry.isFile() &&
      entry.name.endsWith('.yaml') &&
      !NON_MODEL_YAML.has(entry.name)
    ) {
      count++;
    }
  }
  return count;
}

function formatDisplayName(dirName: string): string {
  return dirName
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function main(): void {
  const providerDirs = fs
    .readdirSync(PROVIDERS_DIR, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name);

  const counts: { dir: string; meta: ProviderMeta; count: number }[] = [];

  for (const dir of providerDirs) {
    const providerPath = path.join(PROVIDERS_DIR, dir);
    const count = countModelFiles(providerPath);
    const meta = PROVIDER_META[dir] ?? {
      name: formatDisplayName(dir),
      description: '',
    };
    counts.push({ dir, meta, count });
  }

  counts.sort((a, b) => b.count - a.count);

  const tableHeader = [
    '| Provider | Models | Description |',
    '|----------|--------|-------------|',
  ];
  const tableRows = counts.map(
    ({ meta, count }) => `| ${meta.name} | ${count} | ${meta.description} |`,
  );
  const table = [...tableHeader, ...tableRows].join('\n');

  let readme = fs.readFileSync(README_PATH, 'utf-8');

  const tablePattern =
    /\| Provider \| Models \| Description \|\n\|[-|]+\|\n(?:\|[^\n]+\|\n?)*/;
  if (!tablePattern.test(readme)) {
    console.error('Could not find the provider table in README.md');
    process.exit(1);
  }
  readme = readme.replace(tablePattern, table + '\n');

  const providerCountPattern =
    /Consistent model configuration format across \d+ providers/;
  if (providerCountPattern.test(readme)) {
    readme = readme.replace(
      providerCountPattern,
      `Consistent model configuration format across ${counts.length} providers`,
    );
  }

  fs.writeFileSync(README_PATH, readme, 'utf-8');

  console.log(`Updated README.md with ${counts.length} providers:`);
  for (const { meta, count } of counts) {
    console.log(`  ${meta.name}: ${count} models`);
  }
}

main();

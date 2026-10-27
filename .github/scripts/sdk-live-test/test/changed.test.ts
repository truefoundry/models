import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, it } from 'node:test';
import { modelIdFromYamlFile, parseProviderPath } from '../src/changed.js';
import { getProviderSpec, projectIdFromKeyFile } from '../src/providers.js';
import { planScenarios } from '../src/scenarios.js';
import { targetsWithSecrets } from '../src/smoke.js';

describe('parseProviderPath', () => {
  it('parses model yaml', () => {
    assert.deepEqual(parseProviderPath('providers/openai/gpt-4o.yaml'), {
      provider: 'openai',
    });
  });
  it('parses nested provider dirs', () => {
    assert.deepEqual(parseProviderPath('providers/openrouter/meta/muse-glimmer-30b.yaml'), {
      provider: 'openrouter',
    });
  });
  it('skips default.yaml', () => {
    assert.equal(parseProviderPath('providers/openai/default.yaml'), undefined);
  });
});

describe('modelIdFromYamlFile', () => {
  it('keeps directory-prefixed model ids', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'sdk-live-'));
    const rel = 'providers/vertex/meta/llama-72b.yaml';
    const abs = path.join(root, rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, 'model: meta/llama-72b\n');
    try {
      assert.equal(modelIdFromYamlFile(root, rel), 'meta/llama-72b');
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });
});

describe('planScenarios', () => {
  it('chat: features × stream + params', () => {
    const ids = planScenarios({
      provider: 'openai',
      model: 'gpt',
      mode: 'chat',
      thinking: true,
      features: ['json_output', 'function_calling', 'tool_choice', 'system_messages'],
      params: [
        { key: 'temperature', defaultValue: 0.2 },
        { key: 'top_p', defaultValue: 0.9 },
        { key: 'reasoning_effort', defaultValue: 'medium' },
      ],
    }).map((s) => s.id);
    assert.ok(ids.includes('chat/baseline/non-stream'));
    assert.ok(ids.includes('chat/baseline/stream'));
    assert.ok(ids.includes('chat/json_output/stream'));
    assert.ok(ids.includes('chat/function_calling/non-stream'));
    assert.ok(ids.includes('chat/tool_choice/non-stream'));
    assert.ok(ids.includes('chat/system_messages/stream'));
    assert.ok(ids.includes('chat/reasoning/medium/non-stream'));
    assert.ok(ids.includes('chat/params/non-stream'));
    assert.ok(ids.includes('chat/params/stream'));
  });

  it('caps with max_completion_tokens when max_tokens removed', () => {
    const body = planScenarios({
      provider: 'openai',
      model: 'gpt',
      mode: 'chat',
      removeParams: ['max_tokens'],
    }).find((s) => s.id === 'chat/baseline/non-stream')!.body as Record<string, unknown>;
    assert.equal(body.max_completion_tokens, 64);
    assert.equal(body.max_tokens, undefined);
  });

  it('skips reasoning without catalogue reasoning_effort', () => {
    const ids = planScenarios({
      provider: 'anthropic',
      model: 'claude',
      mode: 'chat',
      thinking: true,
      removeParams: ['reasoning_effort'],
    }).map((s) => s.id);
    assert.ok(!ids.some((id) => id.includes('/reasoning/')));
  });

  it('skips reasoning when only provider-default reasoning_effort (no thinking)', () => {
    const ids = planScenarios({
      provider: 'openai',
      model: 'gpt-4-turbo',
      mode: 'chat',
      defaultProviderParams: {
        params: [{ key: 'reasoning_effort', defaultValue: 'medium', supportedValues: ['medium', 'high'] }],
      },
    }).map((s) => s.id);
    assert.ok(!ids.some((id) => id.includes('/reasoning/')));
  });

  it('emits one reasoning scenario per supportedValues entry', () => {
    const scenarios = planScenarios({
      provider: 'openai',
      model: 'gpt',
      mode: 'chat',
      thinking: true,
      params: [{ key: 'reasoning_effort', defaultValue: 'medium', supportedValues: ['medium', 'high'] }],
    });
    const reasoning = scenarios.filter((s) => s.id.includes('/reasoning/'));
    assert.deepEqual(
      reasoning.map((s) => s.id),
      ['chat/reasoning/medium/non-stream', 'chat/reasoning/high/non-stream'],
    );
    assert.equal((reasoning[0]!.body as Record<string, unknown>).reasoning_effort, 'medium');
    assert.equal((reasoning[1]!.body as Record<string, unknown>).reasoning_effort, 'high');
  });

  it('single reasoning scenario when only defaultValue', () => {
    const ids = planScenarios({
      provider: 'openai',
      model: 'gpt',
      mode: 'chat',
      thinking: true,
      params: [{ key: 'reasoning_effort', defaultValue: 'medium' }],
    }).map((s) => s.id);
    assert.deepEqual(
      ids.filter((id) => id.includes('/reasoning/')),
      ['chat/reasoning/medium/non-stream'],
    );
  });

  it('chat: cache_control aliases to prompt_caching', () => {
    const ids = planScenarios({
      provider: 'anthropic',
      model: 'claude',
      mode: 'chat',
      features: ['prompt_caching', 'cache_control'],
    }).map((s) => s.id);
    const cacheIds = ids.filter((id) => id.includes('prompt_caching') || id.includes('cache_control'));
    assert.deepEqual(cacheIds, ['chat/prompt_caching/non-stream', 'chat/prompt_caching/stream']);
  });

  it('embedding baseline + multimodal', () => {
    const ids = planScenarios({
      provider: 'cohere',
      model: 'e',
      mode: 'embedding',
      modalities: { input: ['text', 'image', 'pdf'], output: ['embedding'] },
    }).map((s) => s.id);
    assert.deepEqual(ids, ['embedding/baseline', 'embedding/image', 'embedding/pdf']);
  });

  it('image moderation decision baselines', () => {
    assert.deepEqual(
      planScenarios({ provider: 'openai', model: 'dall-e', mode: 'image' }).map((s) => s.id),
      ['image/baseline'],
    );
    assert.deepEqual(
      planScenarios({ provider: 'openai', model: 'omni', mode: 'moderation' }).map((s) => s.id),
      ['moderation/baseline'],
    );
    assert.deepEqual(
      planScenarios({ provider: 'openai', model: 'dec', mode: 'decision' }).map((s) => s.id),
      ['decision/baseline'],
    );
    assert.ok(
      (
        planScenarios({ provider: 'openrouter', model: 'jev', mode: 'decision' })[0]
          .body as Record<string, unknown>
      ).state,
    );
  });

  it('plans every harnessed supportedModes entry', () => {
    const ids = planScenarios({
      provider: 'openai',
      model: 'gpt',
      mode: 'chat',
      supportedModes: ['chat', 'responses'],
    }).map((s) => s.id);
    assert.ok(ids.includes('chat/baseline/non-stream'));
    assert.ok(ids.includes('responses/baseline/non-stream'));
  });

  it('skips unharnessed supportedModes when another mode is covered', () => {
    const ids = planScenarios({
      provider: 'openai',
      model: 'gpt',
      mode: 'chat',
      supportedModes: ['chat', 'unsupported', 'realtime'],
    }).map((s) => s.id);
    assert.ok(ids.includes('chat/baseline/non-stream'));
    assert.ok(!ids.some((id) => id.startsWith('unsupported/')));
  });

  it('unsupported mode fails marker', () => {
    for (const mode of ['realtime', 'video', 'ocr', 'unknown']) {
      assert.deepEqual(
        planScenarios({ provider: 'openai', model: 'x', mode }).map((s) => s.id),
        [`unsupported/${mode}`],
      );
    }
  });

  it('adds vision pdf audio doc when modalities declare them', () => {
    const ids = planScenarios({
      provider: 'openai',
      model: 'gpt',
      mode: 'chat',
      modalities: { input: ['text', 'image', 'pdf', 'audio', 'doc'], output: ['text'] },
    }).map((s) => s.id);
    assert.ok(ids.includes('chat/vision/non-stream'));
    assert.ok(ids.includes('chat/pdf/non-stream'));
    assert.ok(ids.includes('chat/audio/non-stream'));
    assert.ok(!ids.includes('chat/doc/non-stream')); // pdf wins when both present
  });

  it('responses: features + modality smokes', () => {
    const ids = planScenarios({
      provider: 'openai',
      model: 'r',
      mode: 'responses',
      features: ['json_output', 'system_messages'],
      modalities: { input: ['text', 'image'], output: ['text'] },
    }).map((s) => s.id);
    assert.ok(ids.includes('responses/baseline/non-stream'));
    assert.ok(ids.includes('responses/json_output/stream'));
    assert.ok(!ids.some((id) => id.includes('system_messages')));
    assert.ok(ids.includes('responses/vision/non-stream'));
  });

  it('responses features map chat tools and response_format', () => {
    const body = planScenarios({
      provider: 'openai',
      model: 'r',
      mode: 'responses',
      features: ['json_output', 'function_calling'],
    }).find((s) => s.id === 'responses/json_output/non-stream')!.body as Record<string, unknown>;
    assert.ok(Array.isArray(body.input));
    assert.equal(body.response_format, undefined);
    assert.equal((body.text as { format: { type: string } }).format.type, 'json_object');

    const toolsBody = planScenarios({
      provider: 'openai',
      model: 'r',
      mode: 'responses',
      features: ['function_calling'],
    }).find((s) => s.id === 'responses/function_calling/non-stream')!.body as Record<string, unknown>;
    const tools = toolsBody.tools as Array<{ type: string; name: string }>;
    assert.equal(tools[0]?.name, 'get_weather');
  });

  it('chat+responses supportedModes uses responses/ ids for modality smokes', () => {
    const ids = planScenarios({
      provider: 'openai',
      model: 'gpt',
      mode: 'chat',
      supportedModes: ['chat', 'responses'],
      modalities: { input: ['text', 'image', 'pdf'], output: ['text'] },
    }).map((s) => s.id);
    assert.ok(ids.includes('chat/vision/non-stream'));
    assert.ok(ids.includes('responses/vision/non-stream'));
    assert.ok(ids.includes('responses/pdf/non-stream'));
  });
});

describe('new provider credentials', () => {
  it('registers bedrock, mantle, databricks, and microsoft-foundry', () => {
    assert.equal(getProviderSpec('aws-bedrock')?.apiKeyEnv, 'AWS_BEDROCK_API_KEY');
    assert.equal(getProviderSpec('aws-bedrock')?.region, 'us-east-1');
    assert.equal(getProviderSpec('aws-bedrock-mantle')?.apiKeyEnv, 'AWS_BEDROCK_MANTLE_API_KEY');
    assert.equal(getProviderSpec('databricks')?.accountEnv?.base_url, 'DATABRICKS_BASE_URL');
    assert.equal(
      getProviderSpec('microsoft-foundry')?.accountEnv?.openai_endpoint,
      'MICROSOFT_FOUNDRY_OPENAI_ENDPOINT',
    );
  });
});

describe('smoke skips deprecated models', () => {
  it('falls back to first non-deprecated chat model when the pin is deprecated', () => {
    const prev = process.env.XAI_API_KEY;
    process.env.XAI_API_KEY = 'xai-test';
    try {
      const catalogue = [
        { provider: 'xai', model: 'grok-4.3', mode: 'chat', isDeprecated: true },
        { provider: 'xai', model: 'grok-old', mode: 'chat', isDeprecated: true },
        { provider: 'xai', model: 'grok-gone', mode: 'chat', status: 'retired' },
        { provider: 'xai', model: 'grok-sunset', mode: 'chat', status: 'deprecated' },
        { provider: 'xai', model: 'grok-5', mode: 'chat' },
      ];
      assert.deepEqual(targetsWithSecrets(catalogue), [{ provider: 'xai', modelId: 'grok-5' }]);
      assert.deepEqual(targetsWithSecrets(catalogue.slice(0, 4)), []);
    } finally {
      if (prev === undefined) delete process.env.XAI_API_KEY;
      else process.env.XAI_API_KEY = prev;
    }
  });
});

describe('wafer, typesafe, elevenlabs', () => {
  it('are registered with their secrets', () => {
    assert.equal(getProviderSpec('wafer')?.apiKeyEnv, 'WAFER_API_KEY');
    assert.equal(getProviderSpec('typesafe')?.apiKeyEnv, 'TYPESAFE_API_KEY');
    assert.equal(getProviderSpec('elevenlabs')?.apiKeyEnv, 'ELEVENLABS_API_KEY');
  });

  it('elevenlabs tts uses the native proxy with a voice_id in the path', () => {
    const [scenario, ...rest] = planScenarios({
      provider: 'elevenlabs',
      model: 'eleven_flash_v2_5',
      mode: 'text_to_speech',
    });
    assert.equal(rest.length, 0);
    assert.equal(scenario!.endpoint, 'tts-proxy');
    assert.match(scenario!.path, /^\/tts\/elevenlabs\/v1\/text-to-speech\/[A-Za-z0-9]+$/);
    assert.deepEqual(scenario!.body, { text: 'hello', model_id: 'eleven_flash_v2_5' });
  });
});

describe('google-vertex key-file', () => {
  it('is registered as key-file auth', () => {
    const spec = getProviderSpec('google-vertex');
    assert.ok(spec);
    assert.equal(spec.authType, 'key-file');
    assert.equal(spec.apiKeyEnv, 'VERTEX_KEY_FILE');
    assert.equal(spec.accountType, 'provider-account/google-vertex');
  });

  it('reads project_id from SA JSON', () => {
    assert.equal(
      projectIdFromKeyFile(JSON.stringify({ type: 'service_account', project_id: 'truefoundry-devtest' })),
      'truefoundry-devtest',
    );
  });
});

describe('smoke-with-secrets', () => {
  it('picks pinned smoke model, else first chat model, only for providers with env set', () => {
    const prev = process.env.OPENAI_API_KEY;
    delete process.env.ANTHROPIC_API_KEY;
    process.env.OPENAI_API_KEY = 'sk-test';
    try {
      const targets = targetsWithSecrets([
        { provider: 'openai', model: 'gpt-4o', mode: 'chat' },
        { provider: 'openai', model: 'gpt-4o-mini', mode: 'chat' },
        { provider: 'openai', model: 'text-embedding-3-small', mode: 'embedding' },
        { provider: 'anthropic', model: 'claude-haiku-5-5', mode: 'chat' },
      ]);
      assert.deepEqual(targets, [{ provider: 'openai', modelId: 'gpt-4o-mini' }]);
    } finally {
      if (prev === undefined) delete process.env.OPENAI_API_KEY;
      else process.env.OPENAI_API_KEY = prev;
    }
  });

  it('skips databricks and foundry until account env is set', () => {
    const keys = [
      'DATABRICKS_API_KEY',
      'DATABRICKS_BASE_URL',
      'MICROSOFT_FOUNDRY_API_KEY',
      'MICROSOFT_FOUNDRY_OPENAI_ENDPOINT',
      'MICROSOFT_FOUNDRY_PROJECT_ENDPOINT',
      'AWS_BEDROCK_API_KEY',
    ] as const;
    const prev = Object.fromEntries(keys.map((key) => [key, process.env[key]]));
    const catalogue = [
      { provider: 'databricks', model: 'databricks-meta-llama-3-1-8b-instruct', mode: 'chat' },
      { provider: 'microsoft-foundry', model: 'gpt-5.6-luna', mode: 'chat' },
      { provider: 'aws-bedrock', model: 'us.anthropic.claude-haiku-4-5-20251001-v1:0', mode: 'chat' },
    ];
    process.env.DATABRICKS_API_KEY = 'db-test';
    delete process.env.DATABRICKS_BASE_URL;
    process.env.MICROSOFT_FOUNDRY_API_KEY = 'foundry-test';
    process.env.MICROSOFT_FOUNDRY_OPENAI_ENDPOINT = 'https://example.openai.azure.com';
    delete process.env.MICROSOFT_FOUNDRY_PROJECT_ENDPOINT;
    process.env.AWS_BEDROCK_API_KEY = 'bedrock-test';
    try {
      assert.deepEqual(targetsWithSecrets(catalogue), [
        { provider: 'aws-bedrock', modelId: 'us.anthropic.claude-haiku-4-5-20251001-v1:0' },
      ]);
      process.env.DATABRICKS_BASE_URL = 'https://example.cloud.databricks.com';
      process.env.MICROSOFT_FOUNDRY_PROJECT_ENDPOINT = 'https://example.services.ai.azure.com';
      assert.deepEqual(targetsWithSecrets(catalogue), [
        { provider: 'aws-bedrock', modelId: 'us.anthropic.claude-haiku-4-5-20251001-v1:0' },
        { provider: 'databricks', modelId: 'databricks-meta-llama-3-1-8b-instruct' },
        { provider: 'microsoft-foundry', modelId: 'gpt-5.6-luna' },
      ]);
    } finally {
      for (const key of keys) {
        if (prev[key] === undefined) delete process.env[key];
        else process.env[key] = prev[key];
      }
    }
  });
});


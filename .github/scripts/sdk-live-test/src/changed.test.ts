import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { parseProviderModelPath } from './changed.js';
import { planScenarios } from './scenarios.js';
import { targetsWithSecrets } from './smoke.js';

describe('parseProviderModelPath', () => {
  it('parses model yaml', () => {
    assert.deepEqual(parseProviderModelPath('providers/openai/gpt-4o.yaml'), {
      provider: 'openai',
    });
  });
  it('skips default.yaml', () => {
    assert.equal(parseProviderModelPath('providers/openai/default.yaml'), undefined);
  });
});

describe('planScenarios', () => {
  it('chat: features × stream + params', () => {
    const ids = planScenarios({
      provider: 'openai',
      model: 'gpt',
      mode: 'chat',
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
    assert.ok(ids.includes('chat/reasoning/stream'));
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

  it('uses catalogue reasoning_effort default', () => {
    const body = planScenarios({
      provider: 'openai',
      model: 'gpt',
      mode: 'chat',
      params: [{ key: 'reasoning_effort', defaultValue: 'medium', supportedValues: ['medium', 'high'] }],
    }).find((s) => s.id === 'chat/reasoning/non-stream')!.body as Record<string, unknown>;
    assert.equal(body.reasoning_effort, 'medium');
  });

  it('chat: prompt_caching and cache_control dedupe', () => {
    const ids = planScenarios({
      provider: 'anthropic',
      model: 'claude',
      mode: 'chat',
      features: ['prompt_caching', 'cache_control'],
    }).map((s) => s.id);
    const cacheIds = ids.filter((id) => id.includes('prompt_caching') || id.includes('cache_control'));
    assert.equal(cacheIds.length, 2); // stream + non-stream for one feature name
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

  it('responses features keep chat messages as input', () => {
    const body = planScenarios({
      provider: 'openai',
      model: 'r',
      mode: 'responses',
      features: ['json_output'],
    }).find((s) => s.id === 'responses/json_output/non-stream')!.body as Record<string, unknown>;
    assert.ok(Array.isArray(body.input));
    assert.equal(body.response_format && (body.response_format as { type: string }).type, 'json_object');
  });
});

describe('smoke-with-secrets', () => {
  it('picks first chat model only for providers with env set', () => {
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
      assert.deepEqual(targets, [{ provider: 'openai', modelId: 'gpt-4o' }]);
    } finally {
      if (prev === undefined) delete process.env.OPENAI_API_KEY;
      else process.env.OPENAI_API_KEY = prev;
    }
  });
});


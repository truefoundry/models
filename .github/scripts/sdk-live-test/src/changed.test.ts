import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { isSignificantYamlChange, parseProviderModelPath } from './changed.js';
import { planScenarios } from './scenarios.js';

describe('parseProviderModelPath', () => {
  it('parses model yaml', () => {
    assert.deepEqual(parseProviderModelPath('providers/openai/gpt-4o.yaml'), {
      provider: 'openai',
      modelFileStem: 'gpt-4o',
      path: 'providers/openai/gpt-4o.yaml',
    });
  });
  it('skips default.yaml', () => {
    assert.equal(parseProviderModelPath('providers/openai/default.yaml'), undefined);
  });
});

describe('isSignificantYamlChange', () => {
  it('treats new file as significant', () => {
    assert.equal(isSignificantYamlChange(null, 'model: x\nmode: chat\n'), true);
  });
  it('ignores cost-only edits', () => {
    const before =
      'model: x\nmode: chat\nfeatures:\n  - json_output\ncosts:\n  - region: "*"\n    input_cost_per_token: 1\n';
    const after =
      'model: x\nmode: chat\nfeatures:\n  - json_output\ncosts:\n  - region: "*"\n    input_cost_per_token: 2\n';
    assert.equal(isSignificantYamlChange(before, after), false);
  });
  it('flags feature edits', () => {
    const before = 'model: x\nmode: chat\nfeatures:\n  - json_output\n';
    const after = 'model: x\nmode: chat\nfeatures:\n  - json_output\n  - function_calling\n';
    assert.equal(isSignificantYamlChange(before, after), true);
  });
});

describe('planScenarios', () => {
  it('chat: features × stream + params', () => {
    const ids = planScenarios({
      provider: 'openai',
      model: 'gpt',
      mode: 'chat',
      features: ['json_output', 'function_calling', 'tool_choice', 'system_messages'],
      thinking: true,
      params: [{ key: 'temperature', defaultValue: 0.2 }, { key: 'top_p', defaultValue: 0.9 }],
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
});

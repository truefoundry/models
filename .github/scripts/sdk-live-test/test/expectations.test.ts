import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { isTransient, judge } from '../src/expectations.js';
import { withDeclaredFeature, withDeclaredParam } from '../src/run.js';
import { planScenarios } from '../src/scenarios.js';

// Shape of providers/microsoft-foundry/claude-opus-5-5-fast-2.yaml in #5533 (declares prefill + tool_choice).
const FOUNDRY_OPUS_55 = {
  provider: 'anthropic',
  model: 'claude-opus-5-5',
  mode: 'chat',
  features: ['function_calling', 'tool_choice', 'system_messages', 'assistant_prefill'],
};

// The same model after #5524: prefill and forced tool_choice removed.
const ANTHROPIC_OPUS_55_FIXED = {
  provider: 'anthropic',
  model: 'claude-opus-5-5',
  mode: 'chat',
  features: ['function_calling', 'system_messages', 'json_output'],
};

const chat = (message: Record<string, unknown>) =>
  JSON.stringify({ choices: [{ index: 0, message: { role: 'assistant', ...message } }] });

const scenario = (model: Parameters<typeof planScenarios>[0], id: string) => {
  const s = planScenarios(model).find((x) => x.id === id);
  assert.ok(s, `scenario ${id} not planned`);
  return s;
};

describe('absent-feature probes', () => {
  it('probes every undeclared chat feature once, non-stream', () => {
    const ids = planScenarios(ANTHROPIC_OPUS_55_FIXED).map((s) => s.id);
    assert.ok(ids.includes('chat/absent/assistant_prefill/non-stream'));
    assert.ok(ids.includes('chat/absent/tool_choice/non-stream'));
    assert.ok(ids.includes('chat/absent/structured_output/non-stream'));
    assert.ok(!ids.includes('chat/absent/function_calling/non-stream'), 'declared feature is not absent');
    assert.ok(!ids.some((id) => id.startsWith('chat/absent/') && id.endsWith('/stream')));
  });

  it('does not probe prompt_caching as absent (a 2xx proves nothing about caching)', () => {
    const ids = planScenarios(ANTHROPIC_OPUS_55_FIXED).map((s) => s.id);
    assert.ok(!ids.includes('chat/absent/prompt_caching/non-stream'));
  });

  it('no absent probes outside chat', () => {
    const ids = planScenarios({ provider: 'openai', model: 'r', mode: 'responses' }).map((s) => s.id);
    assert.ok(!ids.some((id) => id.includes('/absent/')));
  });
});

describe('judge', () => {
  it('#5533: declared assistant_prefill rejected by provider -> fail', () => {
    const s = scenario(FOUNDRY_OPUS_55, 'chat/assistant_prefill/non-stream');
    const v = judge(s, 400, '{"error":{"message":"Prefilling is not supported"}}');
    assert.equal(v.status, 'fail');
  });

  it('#5524 fixed file: undeclared prefill rejected -> pass', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent/assistant_prefill/non-stream');
    const body = '{"error":{"message":"Prefilling assistant messages is not supported for this model."}}';
    assert.equal(judge(s, 400, body).status, 'pass');
  });

  it('absent probe: a 400 that does not name the field is inconclusive -> warn', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent/assistant_prefill/non-stream');
    const v = judge(s, 400, '{"error":{"message":"max_tokens: must be at least 1024"}}');
    assert.equal(v.status, 'warn');
    assert.match(v.detail, /does not name/);
  });

  it('absent probe: a rejection while the baseline also failed is inconclusive -> warn', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent/assistant_prefill/non-stream');
    const body = '{"error":{"message":"prefill not supported"}}';
    assert.equal(judge(s, 400, body, { baselineOk: false }).status, 'warn');
    assert.equal(judge(s, 400, body, { baselineOk: true }).status, 'pass');
  });

  it('undeclared feature that works -> warn, not fail', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent/tool_choice/non-stream');
    const body = chat({ tool_calls: [{ type: 'function', function: { name: 'get_time', arguments: '{}' } }] });
    const v = judge(s, 200, body);
    assert.equal(v.status, 'warn');
    assert.match(v.detail, /undeclared/);
  });

  it('undeclared tool_choice: voluntary get_weather call is not evidence -> pass', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent/tool_choice/non-stream');
    const body = chat({ tool_calls: [{ type: 'function', function: { name: 'get_weather', arguments: '{}' } }] });
    assert.equal(judge(s, 200, body).status, 'pass');
  });

  it('undeclared feature accepted but ignored -> pass', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent/tool_choice/non-stream');
    assert.equal(judge(s, 200, chat({ content: 'sunny' })).status, 'pass');
  });

  it('absent probe: auth or not-found means the probe could not run -> fail', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent/assistant_prefill/non-stream');
    for (const code of [401, 403, 404]) assert.equal(judge(s, code, '{}').status, 'fail', String(code));
  });

  it('absent probe: 429 / 5xx after retries is transient -> warn, not fail', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent/assistant_prefill/non-stream');
    for (const code of [429, 500, 503]) assert.equal(judge(s, code, '{}').status, 'warn', String(code));
    assert.ok(isTransient(429) && isTransient(502) && !isTransient(400));
  });

  it('absent probe: OpenRouter 404 "no endpoints support" counts as rejected', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent/tool_choice/non-stream');
    const body = '{"error":{"message":"No endpoints found that support tool use."}}';
    assert.equal(judge(s, 404, body).status, 'pass');
    assert.equal(judge(s, 404, '{"error":{"message":"model not found"}}').status, 'fail');
  });

  it('absent json_output: 400 demanding "json" in the prompt is inconclusive -> warn', () => {
    const s = scenario(FOUNDRY_OPUS_55, 'chat/absent/json_output/non-stream');
    const body = "{\"error\":{\"message\":\"'messages' must contain the word 'json' in some form\"}}";
    assert.equal(judge(s, 400, body).status, 'warn');
    assert.equal(judge(s, 400, '{"error":{"message":"response_format is not supported"}}').status, 'pass');
  });

  it('declared tool_choice: 200 without the forced tool call -> fail', () => {
    const s = scenario(FOUNDRY_OPUS_55, 'chat/tool_choice/non-stream');
    const v = judge(s, 200, chat({ content: 'It is sunny in Paris.' }));
    assert.equal(v.status, 'fail');
    assert.match(v.detail, /get_time/);
  });

  it('declared tool_choice forces a tool the prompt does not ask for', () => {
    const body = scenario(FOUNDRY_OPUS_55, 'chat/tool_choice/non-stream').body as Record<string, unknown>;
    assert.deepEqual(body.tool_choice, { type: 'function', function: { name: 'get_time' } });
    assert.equal((body.tools as unknown[]).length, 2);
  });

  it('truncated at the token cap with no evidence -> warn, not fail', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/json_output/non-stream');
    const body = JSON.stringify({ choices: [{ message: { content: '' }, finish_reason: 'length' }] });
    const v = judge(s, 200, body);
    assert.equal(v.status, 'warn');
    assert.match(v.detail, /inconclusive/);
  });

  it('declared parallel_function_calling with one call -> warn', () => {
    const s = scenario({ ...ANTHROPIC_OPUS_55_FIXED, features: ['parallel_function_calling'] }, 'chat/parallel_function_calling/non-stream');
    const body = chat({ tool_calls: [{ type: 'function', function: { name: 'get_weather', arguments: '{}' } }] });
    assert.equal(judge(s, 200, body).status, 'warn');
  });

  it('feature probes get room to answer; reasoning models more', () => {
    const plain = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/json_output/non-stream').body as Record<string, unknown>;
    const thinking = scenario({ ...ANTHROPIC_OPUS_55_FIXED, thinking: true }, 'chat/json_output/non-stream').body as Record<string, unknown>;
    assert.equal(plain.max_tokens, 256);
    assert.equal(thinking.max_tokens, 1024);
    const baseline = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/baseline/non-stream').body as Record<string, unknown>;
    assert.equal(baseline.max_tokens, 64);
  });

  it('absent json_output prompt does not ask for JSON in words', () => {
    const body = scenario(FOUNDRY_OPUS_55, 'chat/absent/json_output/non-stream').body as {
      messages: { content: string }[];
    };
    assert.ok(!/json/i.test(body.messages[0]!.content));
  });

  it('JSON after a lead-in sentence means response_format was ignored -> fail', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/json_output/non-stream');
    assert.equal(judge(s, 200, chat({ content: 'Here is the JSON: {"answer":"ok"}' })).status, 'fail');
  });

  it('declared structured_output: JSON that breaks the schema -> fail', () => {
    const s = scenario({ ...ANTHROPIC_OPUS_55_FIXED, features: ['structured_output'] }, 'chat/structured_output/non-stream');
    assert.equal(judge(s, 200, chat({ content: '{"answer":"ok","extra":1}' })).status, 'fail');
    assert.equal(judge(s, 200, chat({ content: '{"result":"ok"}' })).status, 'fail');
    assert.equal(judge(s, 200, chat({ content: '{"answer":"ok"}' })).status, 'pass');
  });

  it('declared function_calling answered in text (tool_choice auto) -> warn, not fail', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/function_calling/non-stream');
    assert.equal(judge(s, 200, chat({ content: 'It is sunny.' })).status, 'warn');
  });

  it('declared json_output: 200 with non-JSON content -> fail; JSON -> pass', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/json_output/non-stream');
    assert.equal(judge(s, 200, chat({ content: 'answer: ok' })).status, 'fail');
    assert.equal(judge(s, 200, chat({ content: '{"answer":"ok"}' })).status, 'pass');
  });

  it('json content inside a markdown fence still counts as JSON', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/json_output/non-stream');
    assert.equal(judge(s, 200, chat({ content: '```json\n{"answer":"ok"}\n```' })).status, 'pass');
  });

  it('stream scenarios keep the 2xx bar (SSE body is not parsed)', () => {
    const s = scenario(FOUNDRY_OPUS_55, 'chat/tool_choice/stream');
    assert.equal(judge(s, 200, 'data: {}\n\n').status, 'pass');
  });

  it('plans absent-param probes: undeclared reasoning_effort and every removeParams entry', () => {
    const ids = planScenarios({ ...ANTHROPIC_OPUS_55_FIXED, removeParams: ['seed', 'top_p', 'max_tokens'] }).map((s) => s.id);
    assert.ok(ids.includes('chat/absent-param/reasoning_effort/non-stream'));
    assert.ok(ids.includes('chat/absent-param/seed/non-stream'));
    assert.ok(ids.includes('chat/absent-param/top_p/non-stream'));
    // the SDK rewrites max_tokens / max_completion_tokens itself, so a probe proves nothing
    assert.ok(!ids.includes('chat/absent-param/max_tokens/non-stream'));
    const declared = planScenarios({
      ...ANTHROPIC_OPUS_55_FIXED,
      params: [{ key: 'reasoning_effort', defaultValue: 'medium' }],
    }).map((s) => s.id);
    assert.ok(!declared.includes('chat/absent-param/reasoning_effort/non-stream'));
  });

  it('absent-param probe sends the param with room to think', () => {
    const body = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent-param/reasoning_effort/non-stream').body as Record<string, unknown>;
    assert.equal(body.reasoning_effort, 'low');
    assert.equal(body.max_tokens, 4096);
  });

  it('undeclared reasoning_effort that produces reasoning tokens -> warn; ignored -> pass', () => {
    const s = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent-param/reasoning_effort/non-stream');
    const worked = JSON.stringify({
      choices: [{ message: { content: '391' } }],
      usage: { completion_tokens: 200, completion_tokens_details: { reasoning_tokens: 180 } },
    });
    const v = judge(s, 200, worked);
    assert.equal(v.status, 'warn');
    assert.match(v.detail, /add reasoning_effort to params/);
    assert.equal(judge(s, 200, chat({ content: '391' })).status, 'pass');
    assert.equal(judge(s, 400, '{"error":{"message":"reasoning_effort is not supported"}}').status, 'pass');
  });

  it('skips params the SDK drops for base gpt-5 (would read as accepted)', () => {
    const ids = planScenarios({ provider: 'openai', model: 'gpt-5-mini', mode: 'chat', removeParams: ['temperature', 'seed'] }).map((s) => s.id);
    assert.ok(!ids.includes('chat/absent-param/temperature/non-stream'));
    assert.ok(ids.includes('chat/absent-param/seed/non-stream'));
    const later = planScenarios({ provider: 'openai', model: 'gpt-5.6', mode: 'chat', removeParams: ['temperature'] }).map((s) => s.id);
    assert.ok(later.includes('chat/absent-param/temperature/non-stream'));
  });

  it('a sampling param accepted with no observable effect -> pass, not warn', () => {
    const s = scenario({ ...ANTHROPIC_OPUS_55_FIXED, removeParams: ['seed'] }, 'chat/absent-param/seed/non-stream');
    assert.equal(judge(s, 200, chat({ content: '391' })).status, 'pass');
  });

  it('hints are narrow: unrelated tool-schema or thinking-budget 400s are inconclusive', () => {
    const tc = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent/tool_choice/non-stream');
    const schema = "{\"error\":{\"message\":\"Invalid schema for function 'get_time' ('tools', 1)\"}}";
    assert.equal(judge(tc, 400, schema).status, 'warn');
    assert.equal(judge(tc, 400, '{"error":{"message":"tool_choice type tool is not supported"}}').status, 'pass');
    const re = scenario(ANTHROPIC_OPUS_55_FIXED, 'chat/absent-param/reasoning_effort/non-stream');
    const budget = '{"error":{"message":"max_tokens must be greater than thinking.budget_tokens"}}';
    assert.equal(judge(re, 400, budget).status, 'warn');
  });

  it('withDeclaredParam adds to params and lifts removeParams, without mutating', () => {
    const model = { ...ANTHROPIC_OPUS_55_FIXED, removeParams: ['max_tokens'] };
    const base = { anthropic: { 'claude-opus-5-5': model } };
    const copy = withDeclaredParam(base as never, model, 'max_tokens') as unknown as typeof base & {
      anthropic: { 'claude-opus-5-5': { params: { key: string }[]; removeParams: string[] } };
    };
    assert.deepEqual(copy.anthropic['claude-opus-5-5'].removeParams, []);
    assert.ok(copy.anthropic['claude-opus-5-5'].params.some((p) => p.key === 'max_tokens'));
    assert.deepEqual(model.removeParams, ['max_tokens']);
  });

  it('withDeclaredFeature copies; the base catalogue is untouched', () => {
    const base = { anthropic: { 'claude-opus-5-5': { ...ANTHROPIC_OPUS_55_FIXED } } };
    const probe = withDeclaredFeature(base as never, ANTHROPIC_OPUS_55_FIXED, 'assistant_prefill') as typeof base;
    assert.ok(probe.anthropic['claude-opus-5-5'].features.includes('assistant_prefill'));
    assert.ok(!base.anthropic['claude-opus-5-5'].features.includes('assistant_prefill'));
    assert.ok(!ANTHROPIC_OPUS_55_FIXED.features.includes('assistant_prefill'));
  });

  it('declared scenario non-2xx -> fail with status in detail', () => {
    const s = scenario(FOUNDRY_OPUS_55, 'chat/baseline/non-stream');
    const v = judge(s, 500, 'boom');
    assert.equal(v.status, 'fail');
    assert.match(v.detail, /HTTP 500/);
  });
});

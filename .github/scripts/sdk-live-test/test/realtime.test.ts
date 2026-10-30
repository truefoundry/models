import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import type { CatalogueModel } from '../src/catalogue.js';
import { classifyRealtimeMessage, realtimeHandshake } from '../src/realtime.js';
import { planScenarios } from '../src/scenarios.js';

const model = (over: Partial<CatalogueModel>): CatalogueModel => ({
  provider: 'openai',
  model: 'gpt-realtime-2.1',
  mode: 'realtime',
  ...over,
});

describe('realtime planning', () => {
  it('plans baseline and turn for openai and google-gemini', () => {
    for (const provider of ['openai', 'google-gemini']) {
      assert.deepEqual(planScenarios(model({ provider })).map((s) => s.id), [
        'realtime/baseline',
        'realtime/turn',
      ]);
    }
  });
  it('plans a tools check when the model lists function_calling', () => {
    const ids = planScenarios(model({ features: ['function_calling'] })).map((s) => s.id);
    assert.deepEqual(ids, ['realtime/baseline', 'realtime/turn', 'realtime/tools']);
  });
  it('stays unsupported for other realtime providers', () => {
    assert.deepEqual(planScenarios(model({ provider: 'azure-open-ai' })).map((s) => s.id), [
      'unsupported/realtime',
    ]);
  });
});

describe('realtimeHandshake', () => {
  it('uses the key as a subprotocol for openai', () => {
    const h = realtimeHandshake(model({}), 'k');
    assert.equal(h.url, 'wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1');
    assert.deepEqual(h.protocols, ['realtime', 'openai-insecure-api-key.k']);
  });
  it('requests AUDIO for gemini even when the catalogue lists text output', () => {
    const live = model({
      provider: 'google-gemini',
      model: 'gemini-3.8-live',
      modalities: { output: ['text', 'audio'] },
    });
    const h = realtimeHandshake(live, 'k');
    assert.deepEqual((h.setup as any).setup.generationConfig.responseModalities, ['AUDIO']);
    assert.equal((h.setup as any).setup.model, 'models/gemini-3.8-live');
  });
});

describe('realtimeHandshake follow-ups', () => {
  const gemini = model({ provider: 'google-gemini', model: 'gemini-3.8-live-extended-thinking' });
  const config = (h: ReturnType<typeof realtimeHandshake>) => (h.setup as any).setup;
  it('sends thinkingLevel from the model-level reasoning_effort default', () => {
    const withEffort = { ...gemini, params: [{ key: 'reasoning_effort', defaultValue: 'medium' }] };
    assert.deepEqual(config(realtimeHandshake(withEffort, 'k')).generationConfig.thinkingConfig, {
      thinkingLevel: 'medium',
    });
    assert.equal(config(realtimeHandshake(gemini, 'k')).generationConfig.thinkingConfig, undefined);
    const removed = { ...withEffort, removeParams: ['reasoning_effort'] };
    assert.equal(config(realtimeHandshake(removed, 'k')).generationConfig.thinkingConfig, undefined);
  });
  it('sends a text turn for the turn check', () => {
    assert.equal(realtimeHandshake(gemini, 'k').followUp?.length, 0);
    const turn = realtimeHandshake(gemini, 'k', 'turn').followUp as any[];
    assert.equal(turn[0].clientContent.turnComplete, true);
    const openai = realtimeHandshake(model({}), 'k', 'turn').followUp as any[];
    assert.deepEqual(openai.map((m) => m.type), ['conversation.item.create', 'response.create']);
  });
  it('declares a function tool for the tools check', () => {
    const g = realtimeHandshake(gemini, 'k', 'tools');
    assert.equal(config(g).tools[0].functionDeclarations[0].name, 'get_weather');
    const o = realtimeHandshake(model({}), 'k', 'tools').followUp as any[];
    assert.equal(o[0].type, 'session.update');
    assert.equal(o[0].session.tools[0].name, 'get_weather');
  });
});

describe('classifyRealtimeMessage', () => {
  it('detects openai ready and error events', () => {
    assert.equal(classifyRealtimeMessage('openai', { type: 'session.created' }).kind, 'ready');
    assert.equal(classifyRealtimeMessage('openai', { type: 'error', error: { code: 'x' } }).kind, 'error');
    assert.equal(classifyRealtimeMessage('openai', { type: 'other' }).kind, 'other');
  });
  it('detects the done events for turn and tools checks', () => {
    const done = { type: 'response.done', response: { status: 'completed' } };
    assert.equal(classifyRealtimeMessage('openai', done, 'turn').kind, 'done');
    assert.equal(
      classifyRealtimeMessage('openai', { type: 'response.done', response: { status: 'failed' } }, 'turn').kind,
      'error',
    );
    assert.equal(classifyRealtimeMessage('openai', { type: 'session.updated' }, 'tools').kind, 'done');
    assert.equal(classifyRealtimeMessage('openai', done, 'baseline').kind, 'other');
    const turnComplete = { serverContent: { turnComplete: true } };
    assert.equal(classifyRealtimeMessage('google-gemini', turnComplete, 'turn').kind, 'done');
  });
  it('detects gemini setupComplete and error', () => {
    assert.equal(classifyRealtimeMessage('google-gemini', { setupComplete: {} }).kind, 'ready');
    assert.equal(classifyRealtimeMessage('google-gemini', { error: { message: 'x' } }).kind, 'error');
  });
});

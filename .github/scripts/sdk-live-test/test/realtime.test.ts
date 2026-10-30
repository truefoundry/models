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
  it('plans a baseline handshake for openai and google-gemini', () => {
    for (const provider of ['openai', 'google-gemini']) {
      assert.deepEqual(planScenarios(model({ provider })).map((s) => s.id), ['realtime/baseline']);
    }
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
  it('picks TEXT only when the catalogue lists text output for gemini', () => {
    const live = model({ provider: 'google-gemini', model: 'gemini-3.8-live' });
    const text = realtimeHandshake({ ...live, modalities: { output: ['text', 'audio'] } }, 'k');
    const audio = realtimeHandshake({ ...live, modalities: { output: ['audio'] } }, 'k');
    assert.deepEqual((text.setup as any).setup.generationConfig.responseModalities, ['TEXT']);
    assert.deepEqual((audio.setup as any).setup.generationConfig.responseModalities, ['AUDIO']);
    assert.equal((text.setup as any).setup.model, 'models/gemini-3.8-live');
  });
});

describe('classifyRealtimeMessage', () => {
  it('detects openai ready and error events', () => {
    assert.equal(classifyRealtimeMessage('openai', { type: 'session.created' }).kind, 'ready');
    assert.equal(classifyRealtimeMessage('openai', { type: 'error', error: { code: 'x' } }).kind, 'error');
    assert.equal(classifyRealtimeMessage('openai', { type: 'other' }).kind, 'other');
  });
  it('detects gemini setupComplete and error', () => {
    assert.equal(classifyRealtimeMessage('google-gemini', { setupComplete: {} }).kind, 'ready');
    assert.equal(classifyRealtimeMessage('google-gemini', { error: { message: 'x' } }).kind, 'error');
  });
});

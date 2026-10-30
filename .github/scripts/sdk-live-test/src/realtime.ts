/**
 * Realtime (WebSocket) checks. The SDK only translates HTTP, so this connects
 * to the provider directly.
 *
 * baseline: openai `session.created` / google-gemini `setupComplete`
 * turn:     send one text turn, expect a finished response (gemini: audio + `turnComplete`)
 * tools:    declare a function tool, expect the session to accept it
 */
import type { CatalogueModel } from './catalogue.js';

export const REALTIME_PROVIDERS = new Set(['openai', 'google-gemini']);

export type RealtimeKind = 'baseline' | 'turn' | 'tools';

const TIMEOUT_MS = 30_000;
const GEMINI_WS =
  'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent';

const WEATHER_TOOL = {
  name: 'get_weather',
  description: 'Get weather for a city',
  parameters: { type: 'object', properties: { city: { type: 'string' } }, required: ['city'] },
};

type Handshake = {
  url: string;
  protocols?: string[];
  /** Sent right after the socket opens. */
  setup?: Record<string, unknown>;
  /** Sent once the session is ready; the check then waits for a `done` event. */
  followUp?: Record<string, unknown>[];
};

export function realtimeHandshake(
  model: CatalogueModel,
  apiKey: string,
  kind: RealtimeKind = 'baseline',
): Handshake {
  if (model.provider === 'openai') {
    const followUp: Record<string, unknown>[] = [];
    if (kind === 'turn') {
      followUp.push(
        {
          type: 'conversation.item.create',
          item: { type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Say hi' }] },
        },
        { type: 'response.create' },
      );
    } else if (kind === 'tools') {
      followUp.push({
        type: 'session.update',
        session: { type: 'realtime', tools: [{ type: 'function', ...WEATHER_TOOL }] },
      });
    }
    return {
      url: `wss://api.openai.com/v1/realtime?model=${encodeURIComponent(model.model)}`,
      protocols: ['realtime', `openai-insecure-api-key.${apiKey}`],
      followUp,
    };
  }
  // Native-audio Live models close the socket on the first turn when asked for TEXT.
  const generationConfig: Record<string, unknown> = { responseModalities: ['AUDIO'] };
  // Extended-thinking Live models reject setup without a level; only a model-level param is verified.
  const effort = model.params?.find((p) => p.key === 'reasoning_effort');
  if (effort?.defaultValue != null && !model.removeParams?.includes('reasoning_effort')) {
    generationConfig.thinkingConfig = { thinkingLevel: effort.defaultValue };
  }
  const setup: Record<string, unknown> = { model: `models/${model.model}`, generationConfig };
  if (kind === 'tools') setup.tools = [{ functionDeclarations: [WEATHER_TOOL] }];
  return {
    url: `${GEMINI_WS}?key=${encodeURIComponent(apiKey)}`,
    setup: { setup },
    followUp:
      kind === 'turn'
        ? [{ clientContent: { turns: [{ role: 'user', parts: [{ text: 'Say hi' }] }], turnComplete: true } }]
        : [],
  };
}

export function classifyRealtimeMessage(
  provider: string,
  msg: Record<string, unknown>,
  kind: RealtimeKind = 'baseline',
): { kind: 'ready' | 'done' | 'error' | 'other'; detail: string } {
  if (provider === 'openai') {
    if (msg.type === 'session.created') return { kind: 'ready', detail: 'session.created' };
    if (msg.type === 'error') return { kind: 'error', detail: JSON.stringify(msg.error ?? msg) };
    if (kind === 'tools' && msg.type === 'session.updated') {
      return { kind: 'done', detail: 'session.updated' };
    }
    if (kind === 'turn' && msg.type === 'response.done') {
      const status = (msg.response as { status?: string } | undefined)?.status;
      return status === 'completed'
        ? { kind: 'done', detail: 'response.done' }
        : { kind: 'error', detail: `response ${status}: ${JSON.stringify(msg.response).slice(0, 300)}` };
    }
    return { kind: 'other', detail: String(msg.type) };
  }
  if ('setupComplete' in msg) return { kind: 'ready', detail: 'setupComplete' };
  if ('error' in msg) return { kind: 'error', detail: JSON.stringify(msg.error) };
  if ((msg.serverContent as { turnComplete?: boolean } | undefined)?.turnComplete) {
    return { kind: 'done', detail: 'turnComplete' };
  }
  return { kind: 'other', detail: Object.keys(msg).join(',') };
}

function hasGeminiAudio(msg: Record<string, unknown>): boolean {
  const parts = (msg.serverContent as { modelTurn?: { parts?: { inlineData?: unknown }[] } } | undefined)
    ?.modelTurn?.parts;
  return parts?.some((p) => p.inlineData != null) ?? false;
}

async function frameText(data: unknown): Promise<string> {
  if (typeof data === 'string') return data;
  if (data instanceof Blob) return data.text();
  return new TextDecoder().decode(data as ArrayBuffer);
}

/** Resolves with the final event name; rejects on error event, close, or timeout. */
export function runRealtime(
  model: CatalogueModel,
  apiKey: string,
  kind: RealtimeKind = 'baseline',
): Promise<string> {
  const handshake = realtimeHandshake(model, apiKey, kind);
  const waitsForDone = (handshake.followUp?.length ?? 0) > 0;
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(handshake.url, handshake.protocols);
    let sawAudio = false;
    const finish = (settle: () => void) => {
      clearTimeout(timer);
      ws.close();
      settle();
    };
    const timer = setTimeout(
      () => finish(() => reject(new Error(`no ${waitsForDone ? 'done' : 'ready'} event within ${TIMEOUT_MS / 1000}s`))),
      TIMEOUT_MS,
    );
    ws.onopen = () => {
      if (handshake.setup) ws.send(JSON.stringify(handshake.setup));
    };
    ws.onmessage = async (event) => {
      const msg = JSON.parse(await frameText(event.data)) as Record<string, unknown>;
      if (model.provider === 'google-gemini' && hasGeminiAudio(msg)) sawAudio = true;
      const { kind: eventKind, detail } = classifyRealtimeMessage(model.provider, msg, kind);
      if (eventKind === 'error') return finish(() => reject(new Error(detail)));
      if (eventKind === 'ready') {
        if (!waitsForDone) return finish(() => resolve(detail));
        for (const message of handshake.followUp ?? []) ws.send(JSON.stringify(message));
      } else if (eventKind === 'done') {
        if (kind === 'turn' && model.provider === 'google-gemini' && !sawAudio) {
          return finish(() => reject(new Error('turnComplete without audio output')));
        }
        finish(() => resolve(detail));
      }
    };
    ws.onerror = () => finish(() => reject(new Error('websocket error')));
    // Gemini reports bad model/key by closing with a reason.
    ws.onclose = (event) =>
      finish(() => reject(new Error(`closed ${event.code}: ${event.reason.slice(0, 300)}`)));
  });
}

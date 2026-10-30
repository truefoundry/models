/**
 * Realtime (WebSocket) handshake check. The SDK only translates HTTP, so this
 * connects to the provider directly and passes once the session is ready.
 *
 * openai:        wss .../v1/realtime?model=… → `session.created`
 * google-gemini: BidiGenerateContent + `setup` → `setupComplete`
 */
import type { CatalogueModel } from './catalogue.js';

export const REALTIME_PROVIDERS = new Set(['openai', 'google-gemini']);

const TIMEOUT_MS = 30_000;
const GEMINI_WS =
  'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent';

type Handshake = {
  url: string;
  protocols?: string[];
  /** Sent right after the socket opens. */
  setup?: Record<string, unknown>;
};

export function realtimeHandshake(model: CatalogueModel, apiKey: string): Handshake {
  if (model.provider === 'openai') {
    return {
      url: `wss://api.openai.com/v1/realtime?model=${encodeURIComponent(model.model)}`,
      protocols: ['realtime', `openai-insecure-api-key.${apiKey}`],
    };
  }
  // Native-audio Live models close the socket on the first turn when asked for TEXT.
  return {
    url: `${GEMINI_WS}?key=${encodeURIComponent(apiKey)}`,
    setup: {
      setup: {
        model: `models/${model.model}`,
        generationConfig: { responseModalities: ['AUDIO'] },
      },
    },
  };
}

export function classifyRealtimeMessage(
  provider: string,
  msg: Record<string, unknown>,
): { kind: 'ready' | 'error' | 'other'; detail: string } {
  if (provider === 'openai') {
    if (msg.type === 'session.created') return { kind: 'ready', detail: 'session.created' };
    if (msg.type === 'error') return { kind: 'error', detail: JSON.stringify(msg.error ?? msg) };
    return { kind: 'other', detail: String(msg.type) };
  }
  if ('setupComplete' in msg) return { kind: 'ready', detail: 'setupComplete' };
  if ('error' in msg) return { kind: 'error', detail: JSON.stringify(msg.error) };
  return { kind: 'other', detail: Object.keys(msg).join(',') };
}

async function frameText(data: unknown): Promise<string> {
  if (typeof data === 'string') return data;
  if (data instanceof Blob) return data.text();
  return new TextDecoder().decode(data as ArrayBuffer);
}

/** Resolves with the ready event name; rejects on error event, close, or timeout. */
export function runRealtime(model: CatalogueModel, apiKey: string): Promise<string> {
  const handshake = realtimeHandshake(model, apiKey);
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(handshake.url, handshake.protocols);
    const finish = (settle: () => void) => {
      clearTimeout(timer);
      ws.close();
      settle();
    };
    const timer = setTimeout(
      () => finish(() => reject(new Error(`no ready event within ${TIMEOUT_MS / 1000}s`))),
      TIMEOUT_MS,
    );
    ws.onopen = () => {
      if (handshake.setup) ws.send(JSON.stringify(handshake.setup));
    };
    ws.onmessage = async (event) => {
      const msg = JSON.parse(await frameText(event.data)) as Record<string, unknown>;
      const { kind, detail } = classifyRealtimeMessage(model.provider, msg);
      if (kind === 'ready') finish(() => resolve(detail));
      else if (kind === 'error') finish(() => reject(new Error(detail)));
    };
    ws.onerror = () => finish(() => reject(new Error('websocket error')));
    // Gemini reports bad model/key by closing with a reason.
    ws.onclose = (event) =>
      finish(() => reject(new Error(`closed ${event.code}: ${event.reason.slice(0, 300)}`)));
  });
}

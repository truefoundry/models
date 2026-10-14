import type { Endpoint } from '@truefoundry/ai-gateway-sdk';
import type { CatalogueModel } from './catalogue.js';
import { sampleImageDataUrl, samplePdfBase64 } from './fixtures.js';

export type Scenario = {
  /** e.g. chat/json_output/stream or embed/baseline */
  id: string;
  endpoint: Endpoint;
  path: string;
  body: Record<string, unknown> | FormData;
};

const FEATURE_KEYS = [
  'structured_output',
  'json_output',
  'function_calling',
  'parallel_function_calling',
  'tool_choice',
  'system_messages',
  'assistant_prefill',
  'mid_conversation_system_messages',
  'prompt_caching',
  'cache_control',
] as const;

/** Features whose chat body still applies after stripping `messages` for Responses. */
const RESPONSES_FEATURE_KEYS = new Set([
  'structured_output',
  'json_output',
  'function_calling',
  'parallel_function_calling',
  'tool_choice',
  'reasoning',
]);

const STREAMING_MODES = new Set(['chat', 'completion', 'responses']);

const PARAM_KEYS = new Set([
  'max_tokens',
  'max_completion_tokens',
  'temperature',
  'top_p',
  'top_k',
  'seed',
  'verbosity',
  'n',
  'stop',
  'min_tokens',
  'reasoning_effort',
]);

const WEATHER_TOOLS = [
  {
    type: 'function',
    function: {
      name: 'get_weather',
      description: 'Get weather for a city',
      parameters: {
        type: 'object',
        properties: { city: { type: 'string' } },
        required: ['city'],
      },
    },
  },
];

const CACHE_PAD = 'Cache pad. '.repeat(200);

/** ~0.1s of silence; enough for whisper-style transcription. */
function minimalWavBytes(): Uint8Array {
  const sampleRate = 8000;
  const numSamples = 800;
  const dataSize = numSamples * 2;
  const buf = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buf);
  const writeStr = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
  };
  writeStr(0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, 'WAVE');
  writeStr(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, 'data');
  view.setUint32(40, dataSize, true);
  return new Uint8Array(buf);
}

function wavBase64(): string {
  const wav = minimalWavBytes();
  return Buffer.from(wav.buffer, wav.byteOffset, wav.byteLength).toString('base64');
}

function streamFlags(mode: string): boolean[] {
  return STREAMING_MODES.has(mode) ? [false, true] : [false];
}

function label(kind: string, stream: boolean): string {
  return stream ? `${kind}/stream` : `${kind}/non-stream`;
}

function mergeParams(model: CatalogueModel): Record<string, unknown> {
  const merged: Record<string, unknown> = {};
  for (const p of model.defaultProviderParams?.params ?? []) {
    if (PARAM_KEYS.has(p.key) && p.defaultValue != null) merged[p.key] = p.defaultValue;
  }
  for (const p of model.params ?? []) {
    if (PARAM_KEYS.has(p.key) && p.defaultValue != null) merged[p.key] = p.defaultValue;
  }
  for (const key of model.removeParams ?? []) delete merged[key];
  if (typeof merged.max_tokens === 'number') merged.max_tokens = Math.min(merged.max_tokens, 64);
  if (typeof merged.max_completion_tokens === 'number') {
    merged.max_completion_tokens = Math.min(merged.max_completion_tokens, 64);
  }
  if (typeof merged.n === 'number') merged.n = Math.min(merged.n, 1);
  return merged;
}

function withCap(body: Record<string, unknown>): Record<string, unknown> {
  return { max_tokens: 64, ...body };
}

function cacheControlMessages(modelId: string): Record<string, unknown> {
  return withCap({
    model: modelId,
    messages: [
      {
        role: 'system',
        content: [{ type: 'text', text: CACHE_PAD, cache_control: { type: 'ephemeral' } }],
      },
      { role: 'user', content: 'Reply with the single word: ok' },
    ],
  });
}

function chatFeatureBody(modelId: string, feature: string): Record<string, unknown> {
  switch (feature) {
    case 'baseline':
      return withCap({
        model: modelId,
        messages: [{ role: 'user', content: 'Reply with the single word: ok' }],
      });
    case 'json_output':
      return withCap({
        model: modelId,
        messages: [{ role: 'user', content: 'Return JSON with key answer set to ok' }],
        response_format: { type: 'json_object' },
      });
    case 'structured_output':
      return withCap({
        model: modelId,
        messages: [{ role: 'user', content: 'Return answer=ok' }],
        response_format: {
          type: 'json_schema',
          json_schema: {
            name: 'answer',
            strict: true,
            schema: {
              type: 'object',
              properties: { answer: { type: 'string' } },
              required: ['answer'],
              additionalProperties: false,
            },
          },
        },
      });
    case 'function_calling':
      return withCap({
        model: modelId,
        messages: [{ role: 'user', content: 'What is the weather in Paris? Use the tool.' }],
        tools: WEATHER_TOOLS,
        tool_choice: 'auto',
      });
    case 'parallel_function_calling':
      return withCap({
        model: modelId,
        messages: [
          { role: 'user', content: 'Weather in Paris and London. Call the tool for each.' },
        ],
        tools: WEATHER_TOOLS,
        tool_choice: 'auto',
        parallel_tool_calls: true,
      });
    case 'tool_choice':
      return withCap({
        model: modelId,
        messages: [{ role: 'user', content: 'What is the weather in Paris?' }],
        tools: WEATHER_TOOLS,
        tool_choice: { type: 'function', function: { name: 'get_weather' } },
      });
    case 'system_messages':
      return withCap({
        model: modelId,
        messages: [
          { role: 'system', content: 'You reply with a single word.' },
          { role: 'user', content: 'Say ok' },
        ],
      });
    case 'assistant_prefill':
      return withCap({
        model: modelId,
        messages: [
          { role: 'user', content: 'Complete with the word ok only.' },
          { role: 'assistant', content: 'ok' },
        ],
      });
    case 'mid_conversation_system_messages':
      return withCap({
        model: modelId,
        messages: [
          { role: 'user', content: 'Hi' },
          { role: 'system', content: 'Reply with a single word.' },
          { role: 'user', content: 'Say ok' },
        ],
      });
    case 'prompt_caching':
    case 'cache_control':
      return cacheControlMessages(modelId);
    case 'reasoning':
      return withCap({
        model: modelId,
        messages: [{ role: 'user', content: 'What is 2+2? Reply with the number only.' }],
        reasoning_effort: 'low',
      });
    default:
      throw new Error(`unknown chat feature ${feature}`);
  }
}

function chatFeatureNames(model: CatalogueModel): string[] {
  const ids = ['baseline'];
  const seen = new Set<string>(ids);
  for (const f of model.features ?? []) {
    if ((FEATURE_KEYS as readonly string[]).includes(f) && !seen.has(f)) {
      // prompt_caching and cache_control share one body; run once.
      if (f === 'cache_control' && seen.has('prompt_caching')) continue;
      if (f === 'prompt_caching' && seen.has('cache_control')) continue;
      ids.push(f);
      seen.add(f);
    }
  }
  if (model.thinking && !(model.removeParams ?? []).includes('reasoning_effort')) {
    ids.push('reasoning');
  }
  return ids;
}

function inputModalities(model: CatalogueModel): Set<string> {
  return new Set(model.modalities?.input ?? []);
}

function visionBody(modelId: string): Record<string, unknown> {
  return withCap({
    model: modelId,
    messages: [
      {
        role: 'user',
        content: [
          { type: 'text', text: 'What text do you see in this image? Reply briefly.' },
          { type: 'image_url', image_url: { url: sampleImageDataUrl() } },
        ],
      },
    ],
  });
}

function pdfBody(modelId: string): Record<string, unknown> {
  return withCap({
    model: modelId,
    messages: [
      {
        role: 'user',
        content: [
          { type: 'text', text: 'Summarize this PDF in one short sentence.' },
          {
            type: 'file',
            file: {
              file_data: samplePdfBase64(),
              filename: 'sample.pdf',
              mime_type: 'application/pdf',
            },
          },
        ],
      },
    ],
  });
}

function audioChatBody(modelId: string): Record<string, unknown> {
  return withCap({
    model: modelId,
    messages: [
      {
        role: 'user',
        content: [
          { type: 'text', text: 'Transcribe or describe this audio briefly.' },
          {
            type: 'input_audio',
            input_audio: { data: wavBase64(), format: 'wav' },
          },
        ],
      },
    ],
  });
}

function pushModalitySmokes(
  out: Scenario[],
  model: CatalogueModel,
  endpoint: Endpoint,
  path: string,
  toBody: (chatBody: Record<string, unknown>) => Record<string, unknown>,
): void {
  const inputs = inputModalities(model);
  if (inputs.has('image')) {
    out.push({
      id: `${model.mode}/vision/non-stream`,
      endpoint,
      path,
      body: toBody(visionBody(model.model)),
    });
  }
  if (inputs.has('pdf') || inputs.has('doc')) {
    const kind = inputs.has('pdf') ? 'pdf' : 'doc';
    out.push({
      id: `${model.mode}/${kind}/non-stream`,
      endpoint,
      path,
      body: toBody(pdfBody(model.model)),
    });
  }
  if (inputs.has('audio')) {
    out.push({
      id: `${model.mode}/audio/non-stream`,
      endpoint,
      path,
      body: toBody(audioChatBody(model.model)),
    });
  }
}

function pushChatLike(
  out: Scenario[],
  model: CatalogueModel,
  endpoint: Endpoint,
  path: string,
  buildBody: (feature: string, stream: boolean) => Record<string, unknown>,
): void {
  for (const feature of chatFeatureNames(model)) {
    for (const stream of streamFlags(model.mode)) {
      out.push({
        id: label(`${model.mode}/${feature}`, stream),
        endpoint,
        path,
        body: buildBody(feature, stream),
      });
    }
  }
  const params = mergeParams(model);
  if (Object.keys(params).length > 0) {
    for (const stream of streamFlags(model.mode)) {
      const body = buildBody('baseline', stream);
      out.push({
        id: label(`${model.mode}/params`, stream),
        endpoint,
        path,
        body: { ...body, ...params },
      });
    }
  }

  pushModalitySmokes(out, model, endpoint, path, (b) => b);
}

function audioForm(modelId: string): FormData {
  const fd = new FormData();
  fd.set('model', modelId);
  const wav = minimalWavBytes();
  fd.set(
    'file',
    new Blob([wav.buffer.slice(wav.byteOffset, wav.byteOffset + wav.byteLength)], { type: 'audio/wav' }),
    'sample.wav',
  );
  return fd;
}

function decisionBody(model: CatalogueModel): Record<string, unknown> {
  const modelId = model.model;
  // OpenAI Decisions dialect; System One for openrouter / perplexity-ai.
  if (model.provider === 'openai') {
    return {
      model: modelId,
      input: 'Say whether this is a greeting: hello',
      questions: [
        {
          type: 'predicate',
          name: 'is_greeting',
          instructions: 'Is the input a greeting?',
        },
      ],
    };
  }
  return {
    model: modelId,
    state: 'Say whether this is a greeting: hello',
    questions: {
      is_greeting: {
        type: 'noul',
        instructions: 'Is the input a greeting?',
        criteria: { true: 'yes', false: 'no' },
      },
    },
  };
}

function responsesModalityBody(chatBody: Record<string, unknown>): Record<string, unknown> {
  const { messages, max_tokens: _t, model, ...rest } = chatBody;
  return {
    ...rest,
    model,
    input: messages,
    max_output_tokens: 64,
  };
}

/**
 * Build the full SDK-live scenario matrix for a catalogue model.
 * Unsupported modes return a single fail-marker scenario (id starts with unsupported/).
 */
export function planScenarios(model: CatalogueModel): Scenario[] {
  const modelId = model.model;
  const mode = model.mode;
  const out: Scenario[] = [];

  switch (mode) {
    case 'chat':
      pushChatLike(out, model, 'chatComplete', '/v1/chat/completions', (feature, stream) => ({
        ...chatFeatureBody(modelId, feature),
        ...(stream ? { stream: true } : {}),
      }));
      return out;

    case 'completion':
      for (const stream of streamFlags(mode)) {
        out.push({
          id: label('completion/baseline', stream),
          endpoint: 'complete',
          path: '/v1/completions',
          body: withCap({
            model: modelId,
            prompt: 'Say ok',
            ...(stream ? { stream: true } : {}),
          }),
        });
      }
      {
        const params = mergeParams(model);
        if (Object.keys(params).length > 0) {
          for (const stream of streamFlags(mode)) {
            out.push({
              id: label('completion/params', stream),
              endpoint: 'complete',
              path: '/v1/completions',
              body: withCap({
                model: modelId,
                prompt: 'Say ok',
                ...params,
                ...(stream ? { stream: true } : {}),
              }),
            });
          }
        }
      }
      return out;

    case 'responses':
      for (const stream of streamFlags(mode)) {
        out.push({
          id: label('responses/baseline', stream),
          endpoint: 'createModelResponse',
          path: '/v1/responses',
          body: {
            model: modelId,
            input: 'Reply with the single word: ok',
            max_output_tokens: 64,
            ...(stream ? { stream: true } : {}),
          },
        });
      }
      for (const feature of chatFeatureNames(model).filter(
        (f) => f !== 'baseline' && RESPONSES_FEATURE_KEYS.has(f),
      )) {
        for (const stream of streamFlags(mode)) {
          const chat = chatFeatureBody(modelId, feature);
          const { messages: _m, max_tokens: _t, ...rest } = chat;
          out.push({
            id: label(`responses/${feature}`, stream),
            endpoint: 'createModelResponse',
            path: '/v1/responses',
            body: {
              ...rest,
              model: modelId,
              input: 'ok',
              max_output_tokens: 64,
              ...(stream ? { stream: true } : {}),
            },
          });
        }
      }
      {
        const params = mergeParams(model);
        if (Object.keys(params).length > 0) {
          for (const stream of streamFlags(mode)) {
            out.push({
              id: label('responses/params', stream),
              endpoint: 'createModelResponse',
              path: '/v1/responses',
              body: {
                model: modelId,
                input: 'Reply with the single word: ok',
                max_output_tokens: 64,
                ...params,
                ...(stream ? { stream: true } : {}),
              },
            });
          }
        }
      }
      pushModalitySmokes(out, model, 'createModelResponse', '/v1/responses', responsesModalityBody);
      return out;

    case 'embedding':
      out.push({
        id: 'embedding/baseline',
        endpoint: 'embed',
        path: '/v1/embeddings',
        body: { model: modelId, input: 'hello embeddings' },
      });
      {
        const inputs = inputModalities(model);
        if (inputs.has('image')) {
          out.push({
            id: 'embedding/image',
            endpoint: 'embed',
            path: '/v1/embeddings',
            body: {
              model: modelId,
              input: [{ image: { base64: sampleImageDataUrl() } }],
            },
          });
        }
        if (inputs.has('pdf')) {
          out.push({
            id: 'embedding/pdf',
            endpoint: 'embed',
            path: '/v1/embeddings',
            body: {
              model: modelId,
              input: [{ image: { base64: `data:application/pdf;base64,${samplePdfBase64()}` } }],
            },
          });
        }
      }
      return out;

    case 'rerank':
      out.push({
        id: 'rerank/baseline',
        endpoint: 'rerank',
        path: '/v1/rerank',
        body: {
          model: modelId,
          query: 'best programming language',
          documents: ['TypeScript', 'Python'],
          top_n: 1,
        },
      });
      return out;

    case 'text_to_speech':
      out.push({
        id: 'text_to_speech/baseline',
        endpoint: 'createSpeech',
        path: '/v1/audio/speech',
        body: { model: modelId, input: 'hello', voice: 'alloy' },
      });
      return out;

    case 'audio_transcription':
      out.push({
        id: 'audio_transcription/baseline',
        endpoint: 'createTranscription',
        path: '/v1/audio/transcriptions',
        body: audioForm(modelId),
      });
      return out;

    case 'audio_translation':
      out.push({
        id: 'audio_translation/baseline',
        endpoint: 'createTranslation',
        path: '/v1/audio/translations',
        body: audioForm(modelId),
      });
      return out;

    case 'image':
      out.push({
        id: 'image/baseline',
        endpoint: 'imageGenerate',
        path: '/v1/images/generations',
        body: { model: modelId, prompt: 'a red square', n: 1 },
      });
      return out;

    case 'moderation':
      out.push({
        id: 'moderation/baseline',
        endpoint: 'createModeration',
        path: '/v1/moderations',
        body: { model: modelId, input: 'hello' },
      });
      return out;

    case 'decision':
      out.push({
        id: 'decision/baseline',
        endpoint: 'decision',
        path: '/v1/decisions',
        body: decisionBody(model),
      });
      return out;

    default:
      out.push({
        id: `unsupported/${mode}`,
        endpoint: 'chatComplete',
        path: '/v1/chat/completions',
        body: { model: modelId },
      });
      return out;
  }
}

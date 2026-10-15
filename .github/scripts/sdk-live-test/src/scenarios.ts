/**
 * Build the live request matrix for one catalogue model.
 *
 * Chat example (features: [json_output], params include reasoning_effort):
 *   chat/baseline/{non-stream,stream}
 *   chat/json_output/{non-stream,stream}
 *   chat/reasoning/{non-stream,stream}
 *   chat/params/{…} when catalogue params have defaults
 *   chat/vision|pdf|audio/non-stream when modalities.input declares them
 *
 * Unsupported modes (realtime, video, …) return id `unsupported/<mode>` → fail in run.ts.
 */
import type { Endpoint } from '@truefoundry/ai-gateway-sdk';
import type { CatalogueModel, ModelParam } from './catalogue.js';
import {
  sampleImageDataUrl,
  samplePdfBase64,
  sampleWavBase64,
  sampleWavBytes,
} from './fixtures.js';

export type Scenario = {
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

/** Responses API has no `messages`; only these chat features map cleanly onto `input`. */
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

function streamFlags(mode: string): boolean[] {
  return STREAMING_MODES.has(mode) ? [false, true] : [false];
}

function label(kind: string, stream: boolean): string {
  return stream ? `${kind}/stream` : `${kind}/non-stream`;
}

function findParam(model: CatalogueModel, key: string): ModelParam | undefined {
  return (
    model.params?.find((p) => p.key === key) ??
    model.defaultProviderParams?.params?.find((p) => p.key === key)
  );
}

/** Effort for reasoning scenario; requires catalogue `thinking: true` (not default.yaml alone). */
function reasoningEffortValue(model: CatalogueModel): string | undefined {
  if (!model.thinking) return undefined;
  if ((model.removeParams ?? []).includes('reasoning_effort')) return undefined;
  const param = findParam(model, 'reasoning_effort');
  if (!param) return undefined;
  if (param.defaultValue != null) return String(param.defaultValue);
  return param.supportedValues?.[0];
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

/** Cheap output cap; honor removeParams (gpt-4.1* → max_completion_tokens). */
function withCap(model: CatalogueModel, body: Record<string, unknown>): Record<string, unknown> {
  const removed = new Set(model.removeParams ?? []);
  const cap: Record<string, number> = {};
  if (!removed.has('max_tokens')) cap.max_tokens = 64;
  else if (!removed.has('max_completion_tokens')) cap.max_completion_tokens = 64;
  return { ...cap, ...body };
}

function cacheControlMessages(model: CatalogueModel): Record<string, unknown> {
  return withCap(model, {
    model: model.model,
    messages: [
      {
        role: 'system',
        content: [{ type: 'text', text: CACHE_PAD, cache_control: { type: 'ephemeral' } }],
      },
      { role: 'user', content: 'Reply with the single word: ok' },
    ],
  });
}

function chatFeatureBody(model: CatalogueModel, feature: string): Record<string, unknown> {
  const modelId = model.model;
  switch (feature) {
    case 'baseline':
      return withCap(model, {
        model: modelId,
        messages: [{ role: 'user', content: 'Reply with the single word: ok' }],
      });
    case 'json_output':
      return withCap(model, {
        model: modelId,
        messages: [{ role: 'user', content: 'Return JSON with key answer set to ok' }],
        response_format: { type: 'json_object' },
      });
    case 'structured_output':
      return withCap(model, {
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
      return withCap(model, {
        model: modelId,
        messages: [{ role: 'user', content: 'What is the weather in Paris? Use the tool.' }],
        tools: WEATHER_TOOLS,
        tool_choice: 'auto',
      });
    case 'parallel_function_calling':
      return withCap(model, {
        model: modelId,
        messages: [
          { role: 'user', content: 'Weather in Paris and London. Call the tool for each.' },
        ],
        tools: WEATHER_TOOLS,
        tool_choice: 'auto',
        parallel_tool_calls: true,
      });
    case 'tool_choice':
      return withCap(model, {
        model: modelId,
        messages: [{ role: 'user', content: 'What is the weather in Paris?' }],
        tools: WEATHER_TOOLS,
        tool_choice: { type: 'function', function: { name: 'get_weather' } },
      });
    case 'system_messages':
      return withCap(model, {
        model: modelId,
        messages: [
          { role: 'system', content: 'You reply with a single word.' },
          { role: 'user', content: 'Say ok' },
        ],
      });
    case 'assistant_prefill':
      return withCap(model, {
        model: modelId,
        messages: [
          { role: 'user', content: 'Complete with the word ok only.' },
          { role: 'assistant', content: 'ok' },
        ],
      });
    case 'mid_conversation_system_messages':
      return withCap(model, {
        model: modelId,
        messages: [
          { role: 'user', content: 'Hi' },
          { role: 'system', content: 'Reply with a single word.' },
          { role: 'user', content: 'Say ok' },
        ],
      });
    case 'prompt_caching':
    case 'cache_control':
      return cacheControlMessages(model);
    case 'reasoning': {
      const effort = reasoningEffortValue(model);
      if (effort == null) throw new Error(`reasoning scenario without reasoning_effort for ${modelId}`);
      return withCap(model, {
        model: modelId,
        messages: [{ role: 'user', content: 'What is 2+2? Reply with the number only.' }],
        reasoning_effort: effort,
      });
    }
    default:
      throw new Error(`unknown chat feature ${feature}`);
  }
}

function chatFeatureNames(model: CatalogueModel): string[] {
  const ids = ['baseline'];
  const seen = new Set<string>(ids);
  for (const f of model.features ?? []) {
    if (!(FEATURE_KEYS as readonly string[]).includes(f) || seen.has(f)) continue;
    // Same request body for both catalogue names — emit one feature id.
    if (f === 'cache_control' && seen.has('prompt_caching')) continue;
    if (f === 'prompt_caching' && seen.has('cache_control')) continue;
    ids.push(f);
    seen.add(f);
  }
  if (reasoningEffortValue(model) != null) ids.push('reasoning');
  return ids;
}

function inputModalities(model: CatalogueModel): Set<string> {
  return new Set(model.modalities?.input ?? []);
}

function visionBody(model: CatalogueModel): Record<string, unknown> {
  return withCap(model, {
    model: model.model,
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

function pdfBody(model: CatalogueModel): Record<string, unknown> {
  return withCap(model, {
    model: model.model,
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

function audioChatBody(model: CatalogueModel): Record<string, unknown> {
  return withCap(model, {
    model: model.model,
    messages: [
      {
        role: 'user',
        content: [
          { type: 'text', text: 'Transcribe or describe this audio briefly.' },
          {
            type: 'input_audio',
            input_audio: { data: sampleWavBase64(), format: 'wav' },
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
      body: toBody(visionBody(model)),
    });
  }
  if (inputs.has('pdf') || inputs.has('doc')) {
    const kind = inputs.has('pdf') ? 'pdf' : 'doc';
    out.push({
      id: `${model.mode}/${kind}/non-stream`,
      endpoint,
      path,
      body: toBody(pdfBody(model)),
    });
  }
  if (inputs.has('audio')) {
    out.push({
      id: `${model.mode}/audio/non-stream`,
      endpoint,
      path,
      body: toBody(audioChatBody(model)),
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
      out.push({
        id: label(`${model.mode}/params`, stream),
        endpoint,
        path,
        body: { ...buildBody('baseline', stream), ...params },
      });
    }
  }

  pushModalitySmokes(out, model, endpoint, path, (b) => b);
}

function audioForm(modelId: string): FormData {
  const fd = new FormData();
  fd.set('model', modelId);
  const wav = sampleWavBytes();
  fd.set(
    'file',
    new Blob([wav.buffer.slice(wav.byteOffset, wav.byteOffset + wav.byteLength)], {
      type: 'audio/wav',
    }),
    'sample.wav',
  );
  return fd;
}

function decisionBody(model: CatalogueModel): Record<string, unknown> {
  const modelId = model.model;
  // openai → Decisions API; openrouter / perplexity-ai → System One (`state` + noul).
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

/** Chat-shaped body → Responses API (`messages` → `input`). */
function responsesModalityBody(chatBody: Record<string, unknown>): Record<string, unknown> {
  const {
    messages,
    max_tokens: _t,
    max_completion_tokens: _c,
    model,
    ...rest
  } = chatBody;
  return {
    ...rest,
    model,
    input: messages,
    max_output_tokens: 64,
  };
}

export function planScenarios(model: CatalogueModel): Scenario[] {
  const modelId = model.model;
  const mode = model.mode;
  const out: Scenario[] = [];

  switch (mode) {
    case 'chat':
      pushChatLike(out, model, 'chatComplete', '/v1/chat/completions', (feature, stream) => ({
        ...chatFeatureBody(model, feature),
        ...(stream ? { stream: true } : {}),
      }));
      return out;

    case 'completion':
      for (const stream of streamFlags(mode)) {
        out.push({
          id: label('completion/baseline', stream),
          endpoint: 'complete',
          path: '/v1/completions',
          body: withCap(model, {
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
              body: withCap(model, {
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
          out.push({
            id: label(`responses/${feature}`, stream),
            endpoint: 'createModelResponse',
            path: '/v1/responses',
            body: {
              ...responsesModalityBody(chatFeatureBody(model, feature)),
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

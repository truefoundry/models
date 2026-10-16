/**
 * Build the live request matrix for one catalogue model.
 *
 * Chat example (features: [json_output], params include reasoning_effort):
 *   chat/baseline/{non-stream,stream}
 *   chat/json_output/{non-stream,stream}
 *   chat/reasoning/<effort>/non-stream for each catalogue supportedValues (or defaultValue alone)
 *   chat/params/{…} when catalogue params have defaults
 *   chat/vision|pdf|audio/non-stream when modalities.input declares them
 *
 * Plans every harnessed mode in `mode` ∪ `supportedModes` (e.g. chat+responses).
 * Unharnessed extras (realtime, video, ocr, …) are skipped when another mode runs;
 * if none are harnessed, returns id `unsupported/<mode>` → fail in run.ts.
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
  /** Chat feature this scenario exercises (FEATURE_KEYS), when there is one. */
  feature?: string;
  stream?: boolean;
  /** Request param this scenario probes (absent-param probes only). */
  param?: string;
  /** `absent`: the catalogue does NOT declare `feature` / `param`; see expectations.ts. */
  expect?: 'absent';
};

/**
 * Params worth probing when the catalogue says the model does not take them: undeclared
 * `reasoning_effort`, and anything listed in `removeParams`.
 *
 * Not here: `max_tokens` / `max_completion_tokens`. The SDK always rewrites one into the other
 * from the catalogue (`normalizeMaxTokensParam`), so a probe through it never reaches the
 * provider as sent; a wrong choice already shows up as a failed baseline call.
 */
const PARAM_PROBE_VALUES: Record<string, unknown> = {
  reasoning_effort: 'low',
  temperature: 0.5,
  top_p: 0.9,
  top_k: 40,
  seed: 1,
  stop: ['\n\n'],
};

/**
 * Mirror of the SDK's `isBaseGpt5ReasoningModel` + `GPT5_UNSUPPORTED_SAMPLING_PARAMS`
 * (dist/globals.js, not exported): the SDK drops these params for that family, so probing
 * them would report "accepted" for a param that never left the gateway.
 */
const GPT5_SDK_DROPPED = new Set(['temperature', 'top_p', 'presence_penalty', 'stop']);
function sdkDropsParam(model: CatalogueModel, param: string): boolean {
  const id = model.model;
  const baseGpt5 = id.includes('gpt-5') && !/gpt-5\.\d/.test(id) && !id.includes('gpt-5-chat');
  return baseGpt5 && GPT5_SDK_DROPPED.has(param);
}

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
] as const;

/** A 2xx on these says nothing about support (caching is silent), so they are never probed as absent. */
const NO_ABSENT_PROBE = new Set(['prompt_caching']);

/** Responses API has no `messages`; only these chat features map cleanly onto `input`. */
const RESPONSES_FEATURE_KEYS = new Set([
  'structured_output',
  'json_output',
  'function_calling',
  'parallel_function_calling',
  'tool_choice',
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

/** Second tool the prompt never asks for: forcing it is the only way to see tool_choice honored. */
const TIME_TOOL = {
  type: 'function',
  function: {
    name: 'get_time',
    description: 'Get local time for a city',
    parameters: {
      type: 'object',
      properties: { city: { type: 'string' } },
      required: ['city'],
    },
  },
};

const CACHE_PAD = 'Cache pad. '.repeat(200);

/** Feature probes need room for the evidence; reasoning models spend the cap on thinking first. */
function featureCap(model: CatalogueModel): number {
  return model.thinking ? 1024 : 256;
}

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

/** Requires catalogue `thinking: true`. All `supportedValues`, else `defaultValue` alone. */
function reasoningEffortValues(model: CatalogueModel): string[] {
  if (!model.thinking) return [];
  if ((model.removeParams ?? []).includes('reasoning_effort')) return [];
  const param = findParam(model, 'reasoning_effort');
  if (!param) return [];
  if (param.supportedValues?.length) return [...param.supportedValues];
  if (param.defaultValue != null) return [String(param.defaultValue)];
  return [];
}

function parseReasoningFeature(feature: string): string | undefined {
  return feature.startsWith('reasoning:') ? feature.slice('reasoning:'.length) : undefined;
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
  // Own scenario; bundling it enables thinking and conflicts with temperature/top_k.
  delete merged.reasoning_effort;
  // Several providers reject temperature + top_p in one request.
  if (merged.temperature != null && merged.top_p != null) delete merged.top_p;
  if (typeof merged.max_tokens === 'number') merged.max_tokens = Math.min(merged.max_tokens, 64);
  if (typeof merged.max_completion_tokens === 'number') {
    merged.max_completion_tokens = Math.min(merged.max_completion_tokens, 64);
  }
  if (typeof merged.n === 'number') merged.n = Math.min(merged.n, 1);
  return merged;
}

/** Cheap output cap; honor removeParams (gpt-4.1* → max_completion_tokens). */
function withCap(
  model: CatalogueModel,
  body: Record<string, unknown>,
  tokens = 64,
): Record<string, unknown> {
  const removed = new Set(model.removeParams ?? []);
  const cap: Record<string, number> = {};
  if (!removed.has('max_tokens')) cap.max_tokens = tokens;
  else if (!removed.has('max_completion_tokens')) cap.max_completion_tokens = tokens;
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

function chatFeatureBody(
  model: CatalogueModel,
  feature: string,
  absent = false,
): Record<string, unknown> {
  const modelId = model.model;
  const cap = featureCap(model);
  switch (feature) {
    case 'baseline':
      return withCap(model, {
        model: modelId,
        messages: [{ role: 'user', content: 'Reply with the single word: ok' }],
      });
    case 'json_output':
      return withCap(
        model,
        {
          model: modelId,
          // Absent probe must not ask for JSON in words, or any model "passes" without response_format.
          messages: [
            {
              role: 'user',
              content: absent ? 'Name the capital of France.' : 'Return JSON with key answer set to ok',
            },
          ],
          response_format: { type: 'json_object' },
        },
        cap,
      );
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
      }, cap);
    case 'function_calling':
      return withCap(model, {
        model: modelId,
        messages: [{ role: 'user', content: 'What is the weather in Paris? Use the tool.' }],
        tools: WEATHER_TOOLS,
        tool_choice: 'auto',
      }, cap);
    case 'parallel_function_calling':
      return withCap(model, {
        model: modelId,
        messages: [
          { role: 'user', content: 'Weather in Paris and London. Call the tool for each.' },
        ],
        tools: WEATHER_TOOLS,
        tool_choice: 'auto',
        parallel_tool_calls: true,
      }, cap);
    case 'tool_choice':
      // Forces get_time on a weather question: a model that ignores tool_choice calls get_weather.
      return withCap(model, {
        model: modelId,
        messages: [{ role: 'user', content: 'What is the weather in Paris?' }],
        tools: [...WEATHER_TOOLS, TIME_TOOL],
        tool_choice: { type: 'function', function: { name: 'get_time' } },
      }, cap);
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
      return cacheControlMessages(model);
    default: {
      const effort = parseReasoningFeature(feature);
      if (effort != null) {
        // Must exceed provider thinking.budget_tokens (withCap default 64 is too small).
        return withCap(model, {
          model: modelId,
          messages: [{ role: 'user', content: 'What is 2+2? Reply with the number only.' }],
          reasoning_effort: effort,
          max_tokens: 4096,
        });
      }
      throw new Error(`unknown chat feature ${feature}`);
    }
  }
}

function chatFeatureNames(model: CatalogueModel): string[] {
  const ids = ['baseline'];
  const seen = new Set<string>(ids);
  for (const raw of model.features ?? []) {
    const f = raw === 'cache_control' ? 'prompt_caching' : raw;
    if (!(FEATURE_KEYS as readonly string[]).includes(f) || seen.has(f)) continue;
    ids.push(f);
    seen.add(f);
  }
  for (const effort of reasoningEffortValues(model)) {
    ids.push(`reasoning:${effort}`);
  }
  return ids;
}

/** Chat features the catalogue does not declare; each gets one non-stream probe. */
function absentFeatureNames(model: CatalogueModel): string[] {
  const declared = new Set(
    (model.features ?? []).map((f) => (f === 'cache_control' ? 'prompt_caching' : f)),
  );
  return FEATURE_KEYS.filter((f) => !declared.has(f) && !NO_ABSENT_PROBE.has(f));
}

/** Params the catalogue says the model does not take; each gets one non-stream probe. */
export function absentParamNames(model: CatalogueModel): string[] {
  const removed = new Set(model.removeParams ?? []);
  const out = [...removed].filter((k) => k in PARAM_PROBE_VALUES);
  if (!removed.has('reasoning_effort') && !findParam(model, 'reasoning_effort')) out.push('reasoning_effort');
  return out.filter((k) => !sdkDropsParam(model, k));
}

function paramProbeBody(model: CatalogueModel, param: string): Record<string, unknown> {
  const body = withCap(
    model,
    {
      model: model.model,
      messages: [{ role: 'user', content: 'What is 17 * 23? Reply with the number only.' }],
    },
    // Must exceed the provider's thinking budget, as the declared reasoning probe does.
    param === 'reasoning_effort' ? 4096 : 64,
  );
  return { ...body, [param]: PARAM_PROBE_VALUES[param] };
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
              file_data: `data:application/pdf;base64,${samplePdfBase64()}`,
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
  buildBody: (feature: string, stream: boolean, absent?: boolean) => Record<string, unknown>,
): void {
  for (const feature of chatFeatureNames(model)) {
    const effort = parseReasoningFeature(feature);
    // Effort matrix: non-stream only (stream × N efforts is too costly).
    const streams = effort != null ? [false] : streamFlags(model.mode);
    for (const stream of streams) {
      const kind =
        effort != null ? `${model.mode}/reasoning/${effort}` : `${model.mode}/${feature}`;
      out.push({
        id: label(kind, stream),
        endpoint,
        path,
        body: buildBody(feature, stream),
        ...(effort == null && feature !== 'baseline' ? { feature } : {}),
        stream,
      });
    }
  }

  for (const feature of absentFeatureNames(model)) {
    out.push({
      id: label(`${model.mode}/absent/${feature}`, false),
      endpoint,
      path,
      body: buildBody(feature, false, true),
      feature,
      stream: false,
      expect: 'absent',
    });
  }

  if (model.mode === 'chat') {
    for (const param of absentParamNames(model)) {
      out.push({
        id: label(`${model.mode}/absent-param/${param}`, false),
        endpoint,
        path,
        body: paramProbeBody(model, param),
        param,
        stream: false,
        expect: 'absent',
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

/** Chat Completions → Responses: flatten nested `function` tools. */
function toResponsesTools(tools: unknown): unknown {
  if (!Array.isArray(tools)) return tools;
  return tools.map((tool: any) => {
    const fn = tool?.type === 'function' ? tool.function : undefined;
    if (!fn) return tool;
    return {
      type: 'function',
      name: fn.name,
      description: fn.description,
      parameters: fn.parameters,
      strict: fn.strict ?? false,
    };
  });
}

/** Chat Completions → Responses: `{ type, function: { name } }` → `{ type, name }`. */
function toResponsesToolChoice(toolChoice: unknown): unknown {
  if (toolChoice == null || typeof toolChoice === 'string') return toolChoice;
  const named = toolChoice as { type?: string; function?: { name?: string } };
  if (named.type === 'function' && named.function?.name) {
    return { type: 'function', name: named.function.name };
  }
  return toolChoice;
}

/** Chat Completions → Responses: `response_format` → `text.format`. */
function toResponsesText(responseFormat: unknown): { format: Record<string, unknown> } | undefined {
  const rf = responseFormat as {
    type?: string;
    json_schema?: { name?: string; schema?: unknown; strict?: boolean };
  } | null;
  if (!rf?.type) return undefined;
  if (rf.type === 'json_schema' && rf.json_schema) {
    return {
      format: {
        type: 'json_schema',
        name: rf.json_schema.name || 'response',
        schema: rf.json_schema.schema,
        strict: rf.json_schema.strict ?? false,
      },
    };
  }
  return { format: { type: rf.type } };
}

/** Chat message content parts → Responses `input_*` parts. */
function toResponsesContentPart(part: any): Record<string, unknown> {
  switch (part?.type) {
    case 'text':
      return { type: 'input_text', text: part.text ?? '' };
    case 'image_url':
      return { type: 'input_image', image_url: part.image_url?.url };
    case 'file':
      return {
        type: 'input_file',
        filename: part.file?.filename,
        file_data: part.file?.file_data,
        file_id: part.file?.file_id,
      };
    default:
      return part;
  }
}

function toResponsesInput(messages: unknown): unknown {
  if (!Array.isArray(messages)) return messages;
  return messages.map((msg: any) => {
    if (typeof msg.content === 'string') {
      return { type: 'message', role: msg.role, content: msg.content };
    }
    if (Array.isArray(msg.content)) {
      return {
        type: 'message',
        role: msg.role,
        content: msg.content.map(toResponsesContentPart),
      };
    }
    return msg;
  });
}

function setIfDefined(target: Record<string, unknown>, key: string, value: unknown): void {
  if (value != null) target[key] = value;
}

/** Chat Completions body → Responses API body. */
function responsesModalityBody(chat: Record<string, unknown>): Record<string, unknown> {
  const maxOut = Math.max(Number(chat.max_completion_tokens ?? chat.max_tokens ?? 64), 16);
  const body: Record<string, unknown> = {
    model: chat.model,
    input: toResponsesInput(chat.messages),
    max_output_tokens: maxOut,
  };

  setIfDefined(body, 'stream', chat.stream);
  setIfDefined(body, 'parallel_tool_calls', chat.parallel_tool_calls);
  setIfDefined(body, 'temperature', chat.temperature);
  setIfDefined(body, 'top_p', chat.top_p);
  setIfDefined(body, 'user', chat.user);

  if (chat.tools != null) body.tools = toResponsesTools(chat.tools);
  if (chat.tool_choice != null) body.tool_choice = toResponsesToolChoice(chat.tool_choice);
  if (chat.response_format != null) setIfDefined(body, 'text', toResponsesText(chat.response_format));
  if (chat.reasoning_effort != null) body.reasoning = { effort: chat.reasoning_effort };

  return body;
}

const HARNESSED_MODES = new Set([
  'chat',
  'completion',
  'responses',
  'embedding',
  'rerank',
  'text_to_speech',
  'audio_transcription',
  'audio_translation',
  'image',
  'moderation',
  'decision',
]);

/** Primary `mode` first, then any extra `supportedModes` (deduped). */
function modesToPlan(model: CatalogueModel): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const mode of [model.mode, ...(model.supportedModes ?? [])]) {
    if (!mode || seen.has(mode)) continue;
    seen.add(mode);
    out.push(mode);
  }
  return out;
}

function planOneMode(model: CatalogueModel, mode: string): Scenario[] {
  // Scope mode so scenario ids / stream flags match the planned mode (not primary catalogue mode).
  model = { ...model, mode };
  const modelId = model.model;
  const out: Scenario[] = [];

  switch (mode) {
    case 'chat':
      pushChatLike(out, model, 'chatComplete', '/v1/chat/completions', (feature, stream, absent) => ({
        ...chatFeatureBody(model, feature, absent),
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
        (f) => f !== 'baseline' && (RESPONSES_FEATURE_KEYS.has(f) || parseReasoningFeature(f) != null),
      )) {
        const effort = parseReasoningFeature(feature);
        const streams = effort != null ? [false] : streamFlags(mode);
        for (const stream of streams) {
          const kind = effort != null ? `responses/reasoning/${effort}` : `responses/${feature}`;
          out.push({
            id: label(kind, stream),
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
                ...responsesModalityBody(
                  withCap(model, {
                    model: modelId,
                    messages: [{ role: 'user', content: 'Reply with the single word: ok' }],
                    ...params,
                  }),
                ),
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
      return [];
  }
}

export function planScenarios(model: CatalogueModel): Scenario[] {
  const out: Scenario[] = [];
  for (const mode of modesToPlan(model)) {
    if (!HARNESSED_MODES.has(mode)) continue;
    out.push(...planOneMode(model, mode));
  }
  if (out.length > 0) return out;
  return [
    {
      id: `unsupported/${model.mode}`,
      endpoint: 'chatComplete',
      path: '/v1/chat/completions',
      body: { model: model.model },
    },
  ];
}

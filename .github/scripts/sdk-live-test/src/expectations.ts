/**
 * Turn one HTTP outcome into pass / warn / fail, given what the catalogue declares.
 *
 * Declared feature (non-stream): 2xx is not enough when the response can show the feature
 * was honored. `tool_choice` forcing `get_time` on a weather question, answered with a
 * `get_weather` call, means the provider ignored it; that is a fail, because the gateway
 * will promise it to users.
 *
 * Absent feature or param (`expect: 'absent'`): the catalogue says unsupported.
 *   400 / 422 naming the field, baseline ok → pass (rejected, as declared)
 *   OpenRouter 404 "no endpoints found that support" → pass
 *   any other rejection   → warn (inconclusive: the 400 may be about something else)
 *   429 / 5xx after retry → warn (inconclusive: transient)
 *   2xx, feature visible  → warn (works but undeclared; add it to the catalogue)
 *   2xx, ignored          → pass (accepted and ignored)
 *   2xx, no detector      → feature: warn (a role/prefill the API accepted is support);
 *                           param: pass (a sampling param leaves no trace to judge)
 * Warn never fails the job: a missing feature hides capability, a wrong one breaks requests.
 *
 * A response cut at the token cap with no evidence either way is a warn ("inconclusive"),
 * never a fail. Stream scenarios keep the plain 2xx bar; the SSE body is not parsed here.
 */
import type { Scenario } from './scenarios.js';

export type Verdict = { status: 'pass' | 'warn' | 'fail'; detail: string };

/** What the run already knows about this model, e.g. whether its plain baseline call worked. */
export type JudgeContext = { baselineOk?: boolean };

type ChatMessage = {
  content?: unknown;
  tool_calls?: { function?: { name?: string } }[];
  reasoning_content?: unknown;
  reasoning?: unknown;
};
type ChatChoice = { message?: ChatMessage; finish_reason?: string };
type ChatBody = {
  choices?: ChatChoice[];
  usage?: { completion_tokens?: number; completion_tokens_details?: { reasoning_tokens?: number } };
};

const REJECTED = new Set([400, 422]);

/** Words a provider's error uses when it rejects this field; a 400 without them is about something else. */
const FIELD_HINTS: Record<string, RegExp> = {
  // Narrow on purpose: a bare /assistant/ or /tool/ matches unrelated schema errors.
  assistant_prefill: /prefill|last message|final message|ends? with/i,
  tool_choice: /tool[_ ]?choice|forced|named tool/i,
  function_calling: /tool|function/i,
  parallel_function_calling: /parallel|tool|function/i,
  json_output: /response[_ ]?format|json/i,
  structured_output: /response[_ ]?format|json[_ ]?schema|schema|structured/i,
  system_messages: /system/i,
  mid_conversation_system_messages: /system/i,
  // Not /thinking/: "max_tokens must exceed thinking.budget_tokens" proves support, not rejection.
  reasoning_effort: /reasoning[_ ]?effort|reasoning is not|does not support reasoning/i,
};

function fieldOf(scenario: Scenario): string | undefined {
  return scenario.param ?? scenario.feature;
}

function namesField(scenario: Scenario, text: string): boolean {
  const field = fieldOf(scenario);
  if (!field) return false;
  const hint = FIELD_HINTS[field] ?? new RegExp(field.replace(/_/g, '[_ ]?'), 'i');
  return hint.test(text);
}

export function isTransient(httpStatus: number): boolean {
  return httpStatus === 429 || httpStatus >= 500;
}

function parseBody(text: string): ChatBody | undefined {
  try {
    return JSON.parse(text) as ChatBody;
  } catch {
    return undefined;
  }
}

function contentText(message: ChatMessage): string {
  if (typeof message.content === 'string') return message.content;
  if (Array.isArray(message.content)) {
    return message.content
      .map((part) => (typeof part === 'object' && part && 'text' in part ? String(part.text) : ''))
      .join('');
  }
  return '';
}

/** The whole reply is one JSON object (a markdown fence is tolerated, prose around it is not). */
function strictJson(content: string): Record<string, unknown> | undefined {
  const unfenced = content.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  try {
    const v = JSON.parse(unfenced);
    return typeof v === 'object' && v !== null && !Array.isArray(v) ? v : undefined;
  } catch {
    return undefined;
  }
}

type Evidence = { ok: boolean | 'partial'; why: string };

/** Evidence the feature or param was honored. Undefined = nothing in the reply can tell. */
function evidence(scenario: Scenario, body: ChatBody): Evidence | undefined {
  const message = body.choices?.[0]?.message;
  if (!message) return undefined;
  const calls = message.tool_calls ?? [];
  if (scenario.param === 'reasoning_effort') {
    const tokens = body.usage?.completion_tokens_details?.reasoning_tokens ?? 0;
    const visible = message.reasoning_content ?? message.reasoning;
    return tokens > 0 || visible
      ? { ok: true, why: tokens > 0 ? `${tokens} reasoning tokens` : 'reasoning returned' }
      : { ok: false, why: 'no reasoning tokens' };
  }
  if (scenario.param) return undefined;
  switch (scenario.feature) {
    case 'json_output':
      return strictJson(contentText(message))
        ? { ok: true, why: 'reply is a JSON object' }
        : { ok: false, why: 'reply is not a bare JSON object' };
    case 'structured_output': {
      const v = strictJson(contentText(message));
      const keys = v ? Object.keys(v) : [];
      return v && keys.length === 1 && typeof v.answer === 'string'
        ? { ok: true, why: 'reply matches the schema' }
        : { ok: false, why: v ? `keys ${JSON.stringify(keys)} do not match the schema` : 'reply is not JSON' };
    }
    case 'function_calling':
      // tool_choice 'auto' may legitimately answer in text, so a missing call is partial.
      return calls.length > 0
        ? { ok: true, why: `${calls.length} tool call(s)` }
        : { ok: 'partial', why: 'answered in text, no tool call' };
    case 'parallel_function_calling':
      if (calls.length > 1) return { ok: true, why: `${calls.length} tool calls` };
      if (calls.length === 1) return { ok: 'partial', why: '1 tool call, expected 2+' };
      return { ok: 'partial', why: 'no tool_calls' };
    case 'tool_choice':
      return calls.some((c) => c.function?.name === 'get_time')
        ? { ok: true, why: 'forced get_time call present' }
        : { ok: false, why: 'forced tool get_time was not called' };
    default:
      return undefined;
  }
}

function judgeAbsent(scenario: Scenario, httpStatus: number, text: string, ctx: JudgeContext): Verdict {
  const http = `HTTP ${httpStatus}`;
  const field = fieldOf(scenario);
  const openRouterNoEndpoint = httpStatus === 404 && /no endpoints found that support/i.test(text);
  if (openRouterNoEndpoint) return { status: 'pass', detail: `${http}: no upstream supports ${field}` };
  // OpenAI-compatible APIs 400 a json_object request whose messages never say "json"; the absent
  // probe keeps the word out on purpose, so that 400 says nothing about support.
  if (scenario.feature === 'json_output' && /must contain the word/i.test(text)) {
    return { status: 'warn', detail: `${http}: inconclusive, provider wants "json" in the prompt` };
  }
  if (REJECTED.has(httpStatus)) {
    if (ctx.baselineOk && namesField(scenario, text)) {
      return { status: 'pass', detail: `${http}: ${field} rejected, as declared` };
    }
    const why = ctx.baselineOk ? `error does not name ${field}` : 'baseline call also failed';
    return { status: 'warn', detail: `${http}: inconclusive, ${why}: ${text.slice(0, 160)}` };
  }
  if (isTransient(httpStatus)) return { status: 'warn', detail: `${http}: inconclusive, transient after retries` };
  if (httpStatus < 200 || httpStatus >= 300) {
    return { status: 'fail', detail: `${http}: probe could not run: ${text.slice(0, 200)}` };
  }
  const body = parseBody(text);
  const e = body ? evidence(scenario, body) : undefined;
  // A sampling param (temperature, seed, …) leaves no trace in the reply; accepted is all we know.
  if (!e && scenario.param) return { status: 'pass', detail: `${http}: accepted, effect not observable` };
  if (e && e.ok !== true) {
    if (body?.choices?.[0]?.finish_reason === 'length') {
      return { status: 'warn', detail: `${http}: inconclusive, cut at token cap` };
    }
    return { status: 'pass', detail: `${http}: accepted but ignored (${e.why})` };
  }
  const where = scenario.param ? 'params' : 'features';
  return {
    status: 'warn',
    detail: `${http}: works but undeclared${e ? ` (${e.why})` : ''}; add ${field} to ${where}?`,
  };
}

export function judge(
  scenario: Scenario,
  httpStatus: number,
  text: string,
  ctx: JudgeContext = { baselineOk: true },
): Verdict {
  if (scenario.expect === 'absent') return judgeAbsent(scenario, httpStatus, text, ctx);

  const http = `HTTP ${httpStatus}`;
  if (httpStatus < 200 || httpStatus >= 300) return { status: 'fail', detail: `${http}: ${text.slice(0, 400)}` };
  if (!scenario.feature || scenario.stream) return { status: 'pass', detail: http };
  const body = parseBody(text);
  const e = body ? evidence(scenario, body) : undefined;
  if (!e) return { status: 'pass', detail: http };
  if (e.ok === true) return { status: 'pass', detail: `${http}, ${e.why}` };
  if (body?.choices?.[0]?.finish_reason === 'length') {
    return { status: 'warn', detail: `${http}: inconclusive, cut at token cap (${e.why})` };
  }
  if (e.ok === 'partial') return { status: 'warn', detail: `${http}: ${e.why}` };
  return { status: 'fail', detail: `${http} but ${e.why}: ${scenario.feature} declared, not honored` };
}

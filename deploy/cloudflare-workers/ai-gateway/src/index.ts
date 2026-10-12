export interface Env {
  AI: Ai;
  INTERNAL_TOKEN: string;
}

const allowedModels = new Set([
  "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
  "@cf/meta/llama-4-scout-17b-16e-instruct",
  "@cf/google/gemma-4-26b-a4b-it",
  "@cf/openai/whisper",
  "@cf/deepgram/aura-2-es",
]);

function json(data: unknown, status = 200): Response {
  return Response.json(data, { status, headers: { "Cache-Control": "no-store" } });
}

function sameToken(provided: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  return Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]).then(([a, b]) => {
    const subtle = crypto.subtle as unknown as { timingSafeEqual: (left: ArrayBuffer, right: ArrayBuffer) => boolean };
    return subtle.timingSafeEqual(a, b);
  });
}

async function authorized(request: Request, env: Env): Promise<boolean> {
  const header = request.headers.get("authorization") || "";
  return header.startsWith("Bearer ") && !!env.INTERNAL_TOKEN &&
    sameToken(header.slice(7), env.INTERNAL_TOKEN);
}

function modelAllowed(model: unknown): model is string {
  return typeof model === "string" && allowedModels.has(model);
}

function textFromResult(result: unknown): string {
  if (typeof result === "string") return result;
  if (result && typeof result === "object" && "choices" in result) {
    const choices = (result as { choices: { message?: { content?: unknown } }[] }).choices;
    const content = choices?.[0]?.message?.content;
    if (typeof content === "string") return content;
  }
  if (result && typeof result === "object" && "response" in result) {
    const response = (result as { response: unknown }).response;
    return typeof response === "string" ? response : JSON.stringify(response);
  }
  return JSON.stringify(result);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function chatOptions(body: Record<string, unknown>, model: string): Record<string, unknown> {
  const options: Record<string, unknown> = {
    messages: body.messages,
    temperature: body.temperature,
    max_tokens: body.max_tokens,
    stream: false,
  };
  for (const name of ["response_format", "chat_template_kwargs", "max_completion_tokens", "reasoning_effort"]) {
    if (body[name] !== undefined) options[name] = body[name];
  }
  if (model === "@cf/google/gemma-4-26b-a4b-it") {
    const kwargs = isRecord(body.chat_template_kwargs) ? body.chat_template_kwargs : {};
    options.chat_template_kwargs = { enable_thinking: false, ...kwargs };
  }
  return options;
}

function chatCompletion(result: unknown): Record<string, unknown> {
  if (isRecord(result) && Array.isArray(result.choices)) return result;
  const completion: Record<string, unknown> = {
    choices: [{
      index: 0,
      message: { role: "assistant", content: textFromResult(result) },
      finish_reason: isRecord(result) ? result.finish_reason ?? null : null,
    }],
  };
  if (isRecord(result) && result.usage !== undefined) completion.usage = result.usage;
  return completion;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
    if (!(await authorized(request, env))) return json({ error: "unauthorized" }, 401);
    const url = new URL(request.url);
    const body = await request.json().catch(() => null) as Record<string, unknown> | null;
    if (!body) return json({ error: "invalid_json" }, 400);

    if (url.pathname === "/v1/chat/completions") {
      const model = body.model;
      if (!modelAllowed(model)) return json({ error: "model_not_allowed" }, 400);
      const result = await env.AI.run(model as never, chatOptions(body, model));
      return json(chatCompletion(result));
    }

    if (url.pathname === "/v1/audio/speech") {
      const model = body.model;
      if (model !== "@cf/deepgram/aura-2-es") return json({ error: "model_not_allowed" }, 400);
      const result = await env.AI.run(model as never, {
        text: body.input,
        speaker: body.voice,
        encoding: body.response_format === "opus" ? "opus" : "mp3",
      });
      return new Response(result as unknown as ReadableStream, { headers: { "Content-Type": "audio/mpeg" } });
    }

    if (url.pathname === "/v1/transcriptions") {
      const model = "@cf/openai/whisper";
      const audio = body.audio;
      if (typeof audio !== "string") return json({ error: "audio_required" }, 400);
      const result = await env.AI.run(model, { audio: Array.from(atob(audio), c => c.charCodeAt(0)) });
      return json(result);
    }
    return json({ error: "not_found" }, 404);
  },
} satisfies ExportedHandler<Env>;

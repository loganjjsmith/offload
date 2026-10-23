import type { Config, Role } from "./config.ts";
import { ensureLoaded } from "./lmstudio.ts";

/** `cut` is true when the answer stopped at the token limit rather than ending by itself. */
export type Reply = { text: string; promptTokens: number; completionTokens: number; seconds: number; cut: boolean };

/**
 * One chat request to the local OpenAI-compatible endpoint. The timeout is long on purpose: a careful-mode
 * answer can take more than ten minutes, and a short client timeout silently loses it.
 */
export async function chat(cfg: Config, r: Role, prompt: string): Promise<Reply> {
  await ensureLoaded(cfg, r);
  const body: Record<string, unknown> = {
    model: r.model,
    messages: [{ role: "user", content: prompt }],
    max_tokens: r.maxAnswerTokens ?? (r.thinking ? cfg.maxAnswerTokens * 4 : cfg.maxAnswerTokens),
  };
  if (!r.thinking) body.reasoning_effort = "none";
  const started = performance.now();
  const res = await fetch(`${cfg.endpoint.replace(/\/$/, "")}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(cfg.requestTimeoutSeconds * 1000),
  });
  if (!res.ok) throw new Error(`Local model returned ${res.status}: ${(await res.text()).slice(0, 300)}`);
  const out = await res.json() as {
    choices: { message: { content?: string | null }; finish_reason?: string | null }[];
    usage?: { prompt_tokens?: number; completion_tokens?: number };
  };
  const text = (out.choices[0]?.message.content ?? "").replace(/<think>[\s\S]*?<\/think>/g, "").trim();
  return {
    text,
    promptTokens: out.usage?.prompt_tokens ?? 0,
    completionTokens: out.usage?.completion_tokens ?? 0,
    seconds: (performance.now() - started) / 1000,
    cut: out.choices[0]?.finish_reason === "length",
  };
}

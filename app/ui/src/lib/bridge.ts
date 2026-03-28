const BRIDGE_URL = "http://127.0.0.1:5161";

// ── Types ──

export type TemplateType = "community_read" | "news_explainer" | "reddit_translation" | "ranking_list" | "origin_story" | "vs_comparison" | "myth_buster" | "tutorial_steps" | "before_after" | "hot_take";
export type TonePreset = "casual_heyo" | "commentary" | "banmal" | "story" | "formal_soft";

export interface BridgeHealth {
  bridge: string;
  vectcut: string;
  tts_providers: string[];
  pexels: string;
  klipy: string;
  groq: string;
  gemini: string;
  template_types: TemplateType[];
  tone_presets: Record<string, string>;
  capcut_draft_dir: string;
  capcut_draft_dir_exists: boolean;
}

export interface Scene {
  scene_num: number;
  narration: string;
  display_text: string;
  image_prompt: string;
  emotion: string;
  duration: number;
  has_image: boolean;
  rank: number | null;
  _tts_url?: string | null;
  is_commentary?: boolean;
  transition?: string;
}

export interface DraftResult {
  ok: boolean;
  draft_id?: string;
  draft_path?: string | null;
  template_type?: TemplateType;
  scenes?: Scene[];
  tts_provider?: string;
  total_duration?: number;
  steps?: string[];
  message?: string;
  error?: string;
}

export interface ThumbnailResult {
  ok: boolean;
  thumbnail_path?: string;
  error?: string;
}

export interface DubResult {
  ok: boolean;
  dubbed_path?: string;
  error?: string;
  [key: string]: unknown;
}

export interface RedditPost {
  title: string;
  subreddit: string;
  score: number;
  url: string;
}

export interface RedditPostsResult {
  ok: boolean;
  posts?: RedditPost[];
  error?: string;
}

export interface RedditAutoResult extends DraftResult {
  source_post?: { title: string; subreddit: string; score: number; url: string };
}

export interface NewsArticle {
  title: string;
  source: string;
  url: string;
}

export interface NewsArticlesResult {
  ok: boolean;
  articles?: NewsArticle[];
  error?: string;
}

export interface NewsAutoResult extends DraftResult {
  source_article?: { title: string; source: string; url: string };
}

export interface BatchCreateResult {
  ok: boolean;
  batch_id?: string;
  error?: string;
}

export interface BatchStatus {
  ok: boolean;
  batch_id: string;
  topic: string;
  variants: number;
  completed: number;
  failed: number;
  progress?: number;
  total?: number;
  results: DraftResult[];
  error?: string;
}

export interface BatchListResult {
  ok: boolean;
  batches?: BatchStatus[];
  error?: string;
}

export interface JobSubmitResult {
  ok: boolean;
  job_id?: string;
  error?: string;
}

export interface JobStatus {
  ok: boolean;
  job_id: string;
  status: "queued" | "pending" | "running" | "completed" | "failed";
  prompt?: string;
  result?: DraftResult | null;
  error?: string;
}

export interface JobListResult {
  ok: boolean;
  jobs?: JobStatus[];
  error?: string;
}

// ── Internal helper ──

async function _apiFetch<T extends { ok: boolean; error?: string }>(
  path: string,
  init?: RequestInit & { timeout?: number },
): Promise<T> {
  const timeout = init?.timeout ?? 15_000;
  const { timeout: _, ...fetchInit } = init ?? {};
  try {
    const resp = await fetch(`${BRIDGE_URL}${path}`, {
      ...fetchInit,
      signal: AbortSignal.timeout(timeout),
    });
    if (!resp.ok) {
      try {
        return (await resp.json()) as T;
      } catch {
        return { ok: false, error: `HTTP ${resp.status}` } as T;
      }
    }
    return (await resp.json()) as T;
  } catch {
    return { ok: false, error: "Bridge connection failed" } as T;
  }
}

function _buildQuery(params: Record<string, string | number | undefined>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

function _post<T extends { ok: boolean; error?: string }>(
  path: string,
  body: Record<string, unknown>,
  timeout?: number,
): Promise<T> {
  return _apiFetch<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    timeout,
  });
}

// ── Health ──

export async function checkHealth(): Promise<BridgeHealth | null> {
  try {
    const resp = await fetch(`${BRIDGE_URL}/api/health`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) return null;
    return resp.json();
  } catch {
    return null;
  }
}

// ── Draft ──

export function createDraft(
  prompt: string,
  lang: string,
  ttsProvider: string,
  voiceGender: string,
  templateType: TemplateType = "news_explainer",
  subtitleStyle: string = "",
  tone: TonePreset = "casual_heyo",
  targetDuration: string = "30s",
  customInstruction: string = "",
): Promise<DraftResult> {
  return _post<DraftResult>("/api/create-draft", {
    prompt, lang, tts_provider: ttsProvider, voice_gender: voiceGender,
    template_type: templateType, subtitle_style: subtitleStyle, tone,
    target_duration: targetDuration,
    ...(customInstruction ? { custom_instruction: customInstruction } : {}),
  }, 300_000);
}

// ── Thumbnail ──

export function generateThumbnail(
  sourcePath: string,
  text?: string,
  timestampSec?: number,
): Promise<ThumbnailResult> {
  return _post<ThumbnailResult>("/api/thumbnail", {
    source_path: sourcePath, text, timestamp_sec: timestampSec,
  }, 30_000);
}

// ── Dubbing ──

export function dubAudio(
  sourcePath: string,
  targetLang = "ko",
  ttsProvider = "edge",
  voiceGender = "female",
  whisperModel = "base",
  style = "natural",
): Promise<DubResult> {
  return _post<DubResult>("/api/dub", {
    source_path: sourcePath, target_lang: targetLang, tts_provider: ttsProvider,
    voice_gender: voiceGender, whisper_model: whisperModel, style,
  }, 300_000);
}

// ── Reddit ──

export function fetchRedditPosts(
  subreddit?: string,
  sort?: string,
  limit?: number,
): Promise<RedditPostsResult> {
  const q = _buildQuery({ subreddit, sort, limit });
  return _apiFetch<RedditPostsResult>(`/api/sources/reddit${q}`);
}

export function autoRedditDraft(opts: {
  subreddit?: string;
  lang?: string;
  tts_provider?: string;
  voice_gender?: string;
  tone?: string;
  subtitle_style?: string;
}): Promise<RedditAutoResult> {
  return _post<RedditAutoResult>("/api/sources/reddit/auto", opts, 300_000);
}

// ── News ──

export function fetchNewsHeadlines(
  q?: string,
  country?: string,
  category?: string,
): Promise<NewsArticlesResult> {
  const qs = _buildQuery({ q, country, category });
  return _apiFetch<NewsArticlesResult>(`/api/sources/news${qs}`);
}

export function autoNewsDraft(opts: {
  q?: string;
  country?: string;
  category?: string;
  lang?: string;
  tts_provider?: string;
  voice_gender?: string;
  tone?: string;
  subtitle_style?: string;
}): Promise<NewsAutoResult> {
  return _post<NewsAutoResult>("/api/sources/news/auto", opts, 300_000);
}

// ── Batch ──

export function createBatch(opts: {
  prompt: string;
  variants?: number;
  template_type?: string;
  lang?: string;
  tts_provider?: string;
  voice_gender?: string;
  subtitle_style?: string;
  tone?: string;
  target_duration?: string;
  custom_instruction?: string;
}): Promise<BatchCreateResult> {
  return _post<BatchCreateResult>("/api/batch/create", opts, 30_000);
}

export function getBatchStatus(batchId: string): Promise<BatchStatus> {
  return _apiFetch<BatchStatus>(`/api/batch/${encodeURIComponent(batchId)}`, { timeout: 10_000 });
}

export function listBatches(): Promise<BatchListResult> {
  return _apiFetch<BatchListResult>("/api/batch", { timeout: 10_000 });
}

export function deleteBatch(batchId: string): Promise<{ ok: boolean; error?: string }> {
  return _apiFetch(`/api/batch/${encodeURIComponent(batchId)}`, { method: "DELETE", timeout: 10_000 });
}

// ── Jobs ──

export function submitJob(opts: {
  prompt: string;
  lang?: string;
  tts_provider?: string;
  voice_gender?: string;
  template_type?: string;
  tone?: string;
  subtitle_style?: string;
  target_duration?: string;
  custom_instruction?: string;
}): Promise<JobSubmitResult> {
  return _post<JobSubmitResult>("/api/jobs", opts, 30_000);
}

export function getJobStatus(jobId: string): Promise<JobStatus> {
  return _apiFetch<JobStatus>(`/api/jobs/${encodeURIComponent(jobId)}`, { timeout: 10_000 });
}

export function listJobs(): Promise<JobListResult> {
  return _apiFetch<JobListResult>("/api/jobs", { timeout: 10_000 });
}

export function deleteJob(jobId: string): Promise<{ ok: boolean; error?: string }> {
  return _apiFetch(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE", timeout: 10_000 });
}

export function deleteDraft(draftId: string): Promise<{ ok: boolean; error?: string }> {
  return _apiFetch(`/api/draft/${encodeURIComponent(draftId)}`, { method: "DELETE", timeout: 10_000 });
}

// ── URL helpers ──

export function getTtsUrl(filename: string): string {
  return `${BRIDGE_URL}/api/tts/${encodeURIComponent(filename)}`;
}

export function getBgmUrl(filename: string): string {
  return `${BRIDGE_URL}/api/bgm/${encodeURIComponent(filename)}`;
}

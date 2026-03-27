const BRIDGE_URL = "http://127.0.0.1:5161";

export type TemplateType = "community_read" | "news_explainer" | "reddit_translation" | "ranking_list" | "origin_story";

export interface BridgeHealth {
  bridge: string;
  vectcut: string;
  tts_providers: string[];
  pexels: string;
  klipy: string;
  gemini: string;
  template_types: TemplateType[];
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

export async function checkHealth(): Promise<BridgeHealth | null> {
  try {
    const resp = await fetch(`${BRIDGE_URL}/api/health`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) return null;
    return resp.json();
  } catch {
    return null;
  }
}

export async function createDraft(
  prompt: string,
  lang: string,
  ttsProvider: string,
  voiceGender: string,
  templateType: TemplateType = "news_explainer",
): Promise<DraftResult> {
  const resp = await fetch(`${BRIDGE_URL}/api/create-draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      lang,
      tts_provider: ttsProvider,
      voice_gender: voiceGender,
      template_type: templateType,
    }),
    signal: AbortSignal.timeout(300_000), // 5 min — pipeline can be slow
  });
  if (!resp.ok) {
    try {
      const err = await resp.json();
      return { ok: false, error: err.error || `HTTP ${resp.status}` };
    } catch {
      return { ok: false, error: `Bridge returned HTTP ${resp.status}` };
    }
  }
  return resp.json();
}

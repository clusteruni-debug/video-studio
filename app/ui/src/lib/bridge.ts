const BRIDGE_URL = "http://127.0.0.1:5161";

export interface BridgeHealth {
  bridge: string;
  vectcut: string;
  tts_providers: string[];
  pexels: string;
  gemini: string;
  capcut_draft_dir: string;
  capcut_draft_dir_exists: boolean;
}

export interface Scene {
  scene_num: number;
  narration: string;
  image_prompt: string;
  duration: number;
  has_image: boolean;
}

export interface DraftResult {
  ok: boolean;
  draft_id?: string;
  draft_path?: string | null;
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
): Promise<DraftResult> {
  const resp = await fetch(`${BRIDGE_URL}/api/create-draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, lang, tts_provider: ttsProvider, voice_gender: voiceGender }),
  });
  return resp.json();
}

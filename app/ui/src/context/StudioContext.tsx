import { createContext, useContext, useEffect, useMemo, useReducer, useRef } from "react";
import {
  checkHealth, createDraft as apiCreateDraft, submitJob as apiSubmitJob,
  createBatch as apiCreateBatch, getBatchStatus, listBatches as apiListBatches,
  listJobs as apiListJobs, deleteBatch as apiDeleteBatch, deleteJob as apiDeleteJob,
  regenerateSceneTts as apiRegenerateTts, generateImage as apiGenerateImage,
  fetchUsageStats,
  type BridgeHealth, type DraftResult, type Scene, type TemplateType, type TonePreset,
  type BatchStatus, type JobStatus, type UsageStats,
} from "../lib/bridge";
import { type QueueItem, ImageGenerationQueue } from "../lib/image-queue";
import { loadStoredProjects, saveStoredProjects } from "../lib/storage";
import type { StudioProjectRecord } from "../lib/planner";
import type { BridgeStatus } from "../components/shared";

// ── Tab type ──

export type StudioTab = "storyboard" | "images" | "sources" | "batch" | "jobs";

// ── State ──

export interface StudioState {
  bridgeStatus: BridgeStatus;
  bridgeHealth: BridgeHealth | null;
  availableProviders: string[];
  availableTemplates: TemplateType[];

  prompt: string;
  lang: "ko" | "en";
  templateType: TemplateType;
  tone: TonePreset;
  ttsProvider: string;
  voiceGender: "female" | "male";
  subtitleStyle: string;
  targetDuration: "30s" | "1min" | "custom";
  customInstruction: string;

  activeTab: StudioTab;
  selectedSceneIndex: number | null;
  debugOpen: boolean;

  creating: boolean;
  error: string | null;
  draftResult: DraftResult | null;

  projects: StudioProjectRecord[];
  activeProjectId: string | null;

  imageItems: QueueItem[];
  imageQueueProcessing: boolean;

  activeBatchId: string | null;
  batchStatus: BatchStatus | null;
  batches: BatchStatus[];

  jobs: JobStatus[];

  usageStats: UsageStats | null;

  paidConfirmDialog: {
    provider: string;
    action: string;
    estimatedCost: string;
    freeAlternative: string;
    pendingAction: "regenerate-image";
    pendingIndex: number;
  } | null;
}

const initialState: StudioState = {
  bridgeStatus: "checking",
  bridgeHealth: null,
  availableProviders: ["edge"],
  availableTemplates: ["community_read", "news_explainer", "reddit_translation", "ranking_list", "origin_story", "vs_comparison", "myth_buster", "tutorial_steps", "before_after", "hot_take"],

  prompt: "",
  lang: "ko",
  templateType: "news_explainer",
  tone: "casual_heyo",
  ttsProvider: "edge",
  voiceGender: "female",
  subtitleStyle: "",
  targetDuration: "30s",
  customInstruction: "",

  activeTab: "storyboard",
  selectedSceneIndex: null,
  debugOpen: false,

  creating: false,
  error: null,
  draftResult: null,

  projects: [],
  activeProjectId: null,

  imageItems: [],
  imageQueueProcessing: false,

  activeBatchId: null,
  batchStatus: null,
  batches: [],

  jobs: [],

  usageStats: null,

  paidConfirmDialog: null,
};

// ── Reducer ──

type Action =
  | { type: "SET_FIELD"; field: keyof StudioState; value: unknown }
  | { type: "BRIDGE_READY"; health: BridgeHealth }
  | { type: "BRIDGE_OFFLINE" }
  | { type: "DRAFT_START" }
  | { type: "DRAFT_OK"; result: DraftResult }
  | { type: "DRAFT_FAIL"; error: string }
  | { type: "SET_PROJECTS"; projects: StudioProjectRecord[] }
  | { type: "DELETE_PROJECT"; id: string }
  | { type: "IMAGE_QUEUE_UPDATE"; items: QueueItem[]; processing: boolean }
  | { type: "BATCH_UPDATE"; status: BatchStatus }
  | { type: "BATCHES_LOADED"; batches: BatchStatus[] }
  | { type: "JOBS_LOADED"; jobs: JobStatus[] }
  | { type: "EDIT_SCENE"; index: number; field: keyof Scene; value: unknown }
  | { type: "DELETE_SCENE"; index: number }
  | { type: "ADD_SCENE"; afterIndex: number }
  | { type: "REORDER_SCENE"; fromIndex: number; toIndex: number }
  | { type: "USAGE_STATS_LOADED"; stats: UsageStats }
  | { type: "SHOW_PAID_CONFIRM"; dialog: NonNullable<StudioState["paidConfirmDialog"]> }
  | { type: "CLOSE_PAID_CONFIRM" };

function reducer(state: StudioState, action: Action): StudioState {
  switch (action.type) {
    case "SET_FIELD":
      return { ...state, [action.field]: action.value };
    case "BRIDGE_READY":
      return {
        ...state,
        bridgeStatus: "connected",
        bridgeHealth: action.health,
        availableProviders: action.health.tts_providers ?? ["edge"],
        availableTemplates: (action.health.template_types?.length ? action.health.template_types : state.availableTemplates),
      };
    case "BRIDGE_OFFLINE":
      return { ...state, bridgeStatus: "offline", bridgeHealth: null };
    case "DRAFT_START":
      return { ...state, creating: true, error: null, draftResult: null, selectedSceneIndex: null };
    case "DRAFT_OK":
      return { ...state, creating: false, draftResult: action.result };
    case "DRAFT_FAIL":
      return { ...state, creating: false, error: action.error };
    case "SET_PROJECTS":
      return { ...state, projects: action.projects };
    case "DELETE_PROJECT":
      return { ...state, projects: state.projects.filter((p) => p.id !== action.id) };
    case "IMAGE_QUEUE_UPDATE":
      return { ...state, imageItems: action.items, imageQueueProcessing: action.processing };
    case "BATCH_UPDATE":
      return { ...state, batchStatus: action.status };
    case "BATCHES_LOADED":
      return { ...state, batches: action.batches };
    case "JOBS_LOADED":
      return { ...state, jobs: action.jobs };
    case "EDIT_SCENE": {
      if (!state.draftResult?.scenes) return state;
      const scenes = [...state.draftResult.scenes];
      scenes[action.index] = { ...scenes[action.index], [action.field]: action.value };
      return { ...state, draftResult: { ...state.draftResult, scenes } };
    }
    case "DELETE_SCENE": {
      if (!state.draftResult?.scenes || state.draftResult.scenes.length <= 1) return state;
      const scenes = state.draftResult.scenes
        .filter((_, i) => i !== action.index)
        .map((s, i) => ({ ...s, scene_num: i + 1 }));
      const sel = state.selectedSceneIndex;
      let newSel: number | null = sel;
      if (sel !== null) {
        if (sel === action.index) newSel = null;
        else if (sel > action.index) newSel = sel - 1;
        if (newSel !== null && newSel >= scenes.length) newSel = scenes.length - 1;
      }
      return { ...state, draftResult: { ...state.draftResult, scenes }, selectedSceneIndex: newSel };
    }
    case "ADD_SCENE": {
      if (!state.draftResult?.scenes) return state;
      const raw = [...state.draftResult.scenes];
      const newScene: Scene = {
        scene_num: 0, narration: "", display_text: "", image_prompt: "",
        emotion: "neutral", duration: 4, has_image: false, rank: null,
        _tts_url: null, is_commentary: false, transition: "Dissolve",
      };
      raw.splice(action.afterIndex + 1, 0, newScene);
      const scenes = raw.map((s, i) => ({ ...s, scene_num: i + 1 }));
      return { ...state, draftResult: { ...state.draftResult, scenes }, selectedSceneIndex: action.afterIndex + 1 };
    }
    case "REORDER_SCENE": {
      if (!state.draftResult?.scenes) return state;
      if (action.fromIndex === action.toIndex) return state;
      const raw = [...state.draftResult.scenes];
      const [moved] = raw.splice(action.fromIndex, 1);
      raw.splice(action.toIndex, 0, moved);
      const scenes = raw.map((s, i) => ({ ...s, scene_num: i + 1 }));
      return { ...state, draftResult: { ...state.draftResult, scenes }, selectedSceneIndex: action.toIndex };
    }
    case "USAGE_STATS_LOADED":
      return { ...state, usageStats: action.stats };
    case "SHOW_PAID_CONFIRM":
      return { ...state, paidConfirmDialog: action.dialog };
    case "CLOSE_PAID_CONFIRM":
      return { ...state, paidConfirmDialog: null };
    default:
      return state;
  }
}

// ── Actions interface ──

export interface StudioActions {
  setPrompt(v: string): void;
  setLang(v: "ko" | "en"): void;
  setTemplateType(v: TemplateType): void;
  setTone(v: TonePreset): void;
  setTtsProvider(v: string): void;
  setVoiceGender(v: "female" | "male"): void;
  setSubtitleStyle(v: string): void;
  setTargetDuration(v: "30s" | "1min" | "custom"): void;
  setCustomInstruction(v: string): void;
  setActiveTab(tab: StudioTab): void;
  selectScene(index: number | null): void;
  toggleDebug(): void;
  handleCreate(): Promise<void>;
  setDraftResult(result: DraftResult): void;
  recheckBridge(): Promise<void>;
  enqueueImages(scenes: Scene[]): void;
  retryImage(id: string): void;
  clearImages(): void;
  editScene(index: number, field: keyof Scene, value: unknown): void;
  deleteScene(index: number): void;
  addScene(afterIndex: number): void;
  reorderScene(fromIndex: number, toIndex: number): void;
  clearDraft(): void;
  deleteBatch(batchId: string): Promise<void>;
  deleteJob(jobId: string): Promise<void>;
  uploadSceneImage(index: number, file: File): void;
  regenerateSceneImage(index: number): Promise<void>;
  regenerateSceneTts(index: number): Promise<void>;
  deleteProject(id: string): void;
  startBatch(variants: number): Promise<string | null>;
  refreshBatches(): Promise<void>;
  submitJob(): Promise<string | null>;
  refreshJobs(): Promise<void>;
  refreshUsageStats(): Promise<void>;
  confirmPaidProceed(): Promise<void>;
  confirmPaidUseFree(): Promise<void>;
  closePaidConfirm(): void;
}

// ── Contexts ──

const StateCtx = createContext<StudioState>(initialState);
const ActionsCtx = createContext<StudioActions>(null!);

export function useStudioState() { return useContext(StateCtx); }
export function useStudioActions() { return useContext(ActionsCtx); }

// ── Provider ──

export function StudioProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState, (init) => ({
    ...init,
    projects: loadStoredProjects(),
  }));

  const stateRef = useRef(state);
  stateRef.current = state;

  // Image queue ref
  const queueRef = useRef<ImageGenerationQueue | null>(null);
  if (!queueRef.current) {
    queueRef.current = new ImageGenerationQueue({
      onItemUpdate(items) {
        dispatch({ type: "IMAGE_QUEUE_UPDATE", items: [...items], processing: true });
      },
      onComplete() {
        dispatch({ type: "IMAGE_QUEUE_UPDATE", items: queueRef.current?.getItems() ?? [], processing: false });
      },
      async bridgeGenerateImage(input) {
        const source = ["pexels", "imagen", "tenor"].includes(input.model) ? input.model : "imagen";
        const res = await apiGenerateImage(input.prompt, source, input.emotion);
        if (!res.ok || !res.image_url) {
          throw new Error(res.error || "브리지에서 이미지 생성 실패");
        }
        // Fetch the image and convert to base64 (chunked to avoid OOM on large images)
        const resp = await fetch(res.image_url, { signal: AbortSignal.timeout(30_000) });
        if (!resp.ok) throw new Error(`이미지 다운로드 실패 (HTTP ${resp.status})`);
        const blob = await resp.blob();
        const buffer = await blob.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        const CHUNK = 8192;
        const parts: string[] = [];
        for (let i = 0; i < bytes.length; i += CHUNK) {
          parts.push(String.fromCharCode(...bytes.subarray(i, i + CHUNK)));
        }
        return { imageBase64: btoa(parts.join("")), mimeType: blob.type || "image/png" };
      },
    });
  }

  // Persist projects
  const prevProjectsRef = useRef(state.projects);
  useEffect(() => {
    if (state.projects !== prevProjectsRef.current) {
      prevProjectsRef.current = state.projects;
      saveStoredProjects(state.projects);
    }
  }, [state.projects]);

  // Bridge health on mount
  useEffect(() => {
    checkHealth().then((h) => {
      if (h) dispatch({ type: "BRIDGE_READY", health: h });
      else dispatch({ type: "BRIDGE_OFFLINE" });
    });
  }, []);

  // Usage stats polling — every 30s when bridge is connected
  useEffect(() => {
    if (state.bridgeStatus !== "connected") return;
    // Fetch immediately on connect
    fetchUsageStats().then((s) => {
      if (s.ok) dispatch({ type: "USAGE_STATS_LOADED", stats: s });
    });
    const id = setInterval(async () => {
      if (!document.hidden) {
        const s = await fetchUsageStats();
        if (s.ok) dispatch({ type: "USAGE_STATS_LOADED", stats: s });
      }
    }, 30_000);
    return () => clearInterval(id);
  }, [state.bridgeStatus]);

  // Batch polling — use stateRef to avoid stale closure
  useEffect(() => {
    if (!state.activeBatchId) return;
    const batchId = state.activeBatchId;
    const id = setInterval(async () => {
      const s = await getBatchStatus(batchId);
      if (s.ok) {
        dispatch({ type: "BATCH_UPDATE", status: s });
        // Use progress/total (backend) with completed/failed as fallback
        const done = (s.completed ?? s.progress ?? 0) + (s.failed ?? 0);
        const total = s.variants ?? s.total ?? 1;
        if (done >= total) {
          dispatch({ type: "SET_FIELD", field: "activeBatchId", value: null });
        }
      }
    }, 3000);
    return () => clearInterval(id);
  }, [state.activeBatchId]);

  // Actions
  const actions = useMemo<StudioActions>(() => {
    async function _doGenerateImage(index: number, source: string) {
      const scene = stateRef.current.draftResult?.scenes?.[index];
      if (!scene?.image_prompt) return;
      try {
        const res = await apiGenerateImage(scene.image_prompt, source, scene.emotion);
        if (res.ok && res.image_url) {
          const oldPreview = scene._upload_preview;
          if (oldPreview) {
            URL.revokeObjectURL(oldPreview);
            dispatch({ type: "EDIT_SCENE", index, field: "_upload_preview", value: null });
          }
          dispatch({ type: "EDIT_SCENE", index, field: "_image_url", value: res.image_url });
          dispatch({ type: "EDIT_SCENE", index, field: "has_image", value: true });
          if (res.source) dispatch({ type: "EDIT_SCENE", index, field: "image_source", value: res.source });
        } else {
          dispatch({ type: "SET_FIELD", field: "error", value: res.error || "이미지 생성 실패" });
        }
      } catch (e: unknown) {
        dispatch({ type: "SET_FIELD", field: "error", value: e instanceof Error ? e.message : "이미지 생성 연결 실패" });
      }
    }

    return ({
    setPrompt(v) { dispatch({ type: "SET_FIELD", field: "prompt", value: v }); },
    setLang(v) { dispatch({ type: "SET_FIELD", field: "lang", value: v }); },
    setTemplateType(v) { dispatch({ type: "SET_FIELD", field: "templateType", value: v }); },
    setTone(v) { dispatch({ type: "SET_FIELD", field: "tone", value: v }); },
    setTtsProvider(v) { dispatch({ type: "SET_FIELD", field: "ttsProvider", value: v }); },
    setVoiceGender(v) { dispatch({ type: "SET_FIELD", field: "voiceGender", value: v }); },
    setSubtitleStyle(v) { dispatch({ type: "SET_FIELD", field: "subtitleStyle", value: v }); },
    setTargetDuration(v) { dispatch({ type: "SET_FIELD", field: "targetDuration", value: v }); },
    setCustomInstruction(v) { dispatch({ type: "SET_FIELD", field: "customInstruction", value: v }); },
    setActiveTab(tab) { dispatch({ type: "SET_FIELD", field: "activeTab", value: tab }); },
    selectScene(index) { dispatch({ type: "SET_FIELD", field: "selectedSceneIndex", value: index }); },
    toggleDebug() {
      dispatch({ type: "SET_FIELD", field: "debugOpen", value: !stateRef.current.debugOpen });
    },

    async handleCreate() {
      const s = stateRef.current;
      if (!s.prompt.trim() || s.creating) return;
      dispatch({ type: "DRAFT_START" });
      try {
        const result = await apiCreateDraft(s.prompt, s.lang, s.ttsProvider, s.voiceGender, s.templateType, s.subtitleStyle, s.tone, s.targetDuration, s.customInstruction);
        if (result.ok) {
          dispatch({ type: "DRAFT_OK", result });
          // Refresh usage stats after a successful creation
          fetchUsageStats().then((stats) => {
            if (stats.ok) dispatch({ type: "USAGE_STATS_LOADED", stats });
          });
        } else {
          dispatch({ type: "DRAFT_FAIL", error: result.error || "Failed to create draft" });
        }
      } catch (e: unknown) {
        dispatch({ type: "DRAFT_FAIL", error: e instanceof Error ? e.message : "Bridge connection failed" });
      }
    },

    setDraftResult(result) {
      dispatch({ type: "DRAFT_OK", result });
    },

    async recheckBridge() {
      dispatch({ type: "SET_FIELD", field: "bridgeStatus", value: "checking" });
      const h = await checkHealth();
      if (h) dispatch({ type: "BRIDGE_READY", health: h });
      else dispatch({ type: "BRIDGE_OFFLINE" });
    },

    enqueueImages(scenes) {
      const q = queueRef.current!;
      for (const scene of scenes) {
        if (scene.image_prompt) {
          q.enqueue({
            id: `scene-${scene.scene_num}-${Date.now()}`,
            prompt: scene.image_prompt,
            originalPrompt: scene.image_prompt,
            width: 1080,
            height: 1920,
            engine: scene.image_source || "imagen",
            emotion: scene.emotion || "neutral",
            filename: `scene_${scene.scene_num}.webp`,
          });
        }
      }
      q.start();
    },

    retryImage(id) {
      queueRef.current?.retry(id);
    },

    clearImages() {
      queueRef.current?.stop();
      queueRef.current?.clear();
      dispatch({ type: "IMAGE_QUEUE_UPDATE", items: [], processing: false });
    },

    editScene(index, field, value) {
      dispatch({ type: "EDIT_SCENE", index, field, value });
    },
    deleteScene(index) {
      dispatch({ type: "DELETE_SCENE", index });
    },
    addScene(afterIndex) {
      dispatch({ type: "ADD_SCENE", afterIndex });
    },
    reorderScene(fromIndex, toIndex) {
      dispatch({ type: "REORDER_SCENE", fromIndex, toIndex });
    },
    uploadSceneImage(index, file) {
      const oldPreview = stateRef.current.draftResult?.scenes?.[index]?._upload_preview;
      if (oldPreview) URL.revokeObjectURL(oldPreview);
      const previewUrl = URL.createObjectURL(file);
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_preview", value: previewUrl });
      dispatch({ type: "EDIT_SCENE", index, field: "image_source", value: "upload" });
      dispatch({ type: "EDIT_SCENE", index, field: "has_image", value: true });
    },
    async regenerateSceneImage(index) {
      const scene = stateRef.current.draftResult?.scenes?.[index];
      if (!scene?.image_prompt) return;
      const source = scene.image_source === "upload" ? "" : (scene.image_source ?? "");
      const PAID_PROVIDERS = ["imagen", "dalle3", "veo3", "sora2", "elevenlabs", "openai-tts", "suno"];
      if (source && PAID_PROVIDERS.includes(source)) {
        dispatch({
          type: "SHOW_PAID_CONFIRM",
          dialog: {
            provider: "Imagen 4",
            action: "이미지 1장 재생성",
            estimatedCost: "$0.02",
            freeAlternative: "Pexels 검색으로 대체",
            pendingAction: "regenerate-image",
            pendingIndex: index,
          },
        });
        return;
      }
      await _doGenerateImage(index, source);
    },
    async regenerateSceneTts(index) {
      const s = stateRef.current;
      const scene = s.draftResult?.scenes?.[index];
      if (!scene) return;
      try {
        const res = await apiRegenerateTts(scene.narration, scene.scene_num, s.lang, s.ttsProvider, s.voiceGender);
        if (res.ok && res._tts_url) {
          dispatch({ type: "EDIT_SCENE", index, field: "_tts_url", value: res._tts_url });
          if (res.duration) dispatch({ type: "EDIT_SCENE", index, field: "duration", value: res.duration });
        } else if (!res.ok) {
          dispatch({ type: "SET_FIELD", field: "error", value: res.error || "TTS 재생성 실패" });
        }
      } catch (e: unknown) {
        dispatch({ type: "SET_FIELD", field: "error", value: e instanceof Error ? e.message : "TTS 연결 실패" });
      }
    },
    clearDraft() {
      const scenes = stateRef.current.draftResult?.scenes;
      if (scenes) {
        for (const s of scenes) {
          if (s._upload_preview) URL.revokeObjectURL(s._upload_preview);
        }
      }
      dispatch({ type: "SET_FIELD", field: "draftResult", value: null });
      dispatch({ type: "SET_FIELD", field: "selectedSceneIndex", value: null });
    },
    async deleteBatch(batchId) {
      await apiDeleteBatch(batchId);
      if (stateRef.current.activeBatchId === batchId) {
        dispatch({ type: "SET_FIELD", field: "activeBatchId", value: null });
      }
      const res = await apiListBatches();
      if (res.ok && res.batches) dispatch({ type: "BATCHES_LOADED", batches: res.batches });
    },
    async deleteJob(jobId) {
      await apiDeleteJob(jobId);
      const res = await apiListJobs();
      if (res.ok && res.jobs) dispatch({ type: "JOBS_LOADED", jobs: res.jobs });
    },
    deleteProject(id) {
      dispatch({ type: "DELETE_PROJECT", id });
    },

    async startBatch(variants) {
      const s = stateRef.current;
      if (!s.prompt.trim()) return null;
      const res = await apiCreateBatch({
        prompt: s.prompt, variants,
        template_type: s.templateType, lang: s.lang,
        tts_provider: s.ttsProvider, voice_gender: s.voiceGender,
        subtitle_style: s.subtitleStyle, tone: s.tone,
        target_duration: s.targetDuration,
        ...(s.customInstruction ? { custom_instruction: s.customInstruction } : {}),
      });
      if (res.ok && res.batch_id) {
        dispatch({ type: "SET_FIELD", field: "activeBatchId", value: res.batch_id });
        return res.batch_id;
      }
      dispatch({ type: "DRAFT_FAIL", error: res.error || "Batch creation failed" });
      return null;
    },

    async refreshBatches() {
      const res = await apiListBatches();
      if (res.ok && res.batches) dispatch({ type: "BATCHES_LOADED", batches: res.batches });
    },

    async submitJob() {
      const s = stateRef.current;
      if (!s.prompt.trim()) return null;
      const res = await apiSubmitJob({
        prompt: s.prompt, lang: s.lang, tts_provider: s.ttsProvider,
        voice_gender: s.voiceGender, template_type: s.templateType,
        tone: s.tone, subtitle_style: s.subtitleStyle,
        target_duration: s.targetDuration,
        ...(s.customInstruction ? { custom_instruction: s.customInstruction } : {}),
      });
      if (res.ok) {
        const list = await apiListJobs();
        if (list.ok && list.jobs) dispatch({ type: "JOBS_LOADED", jobs: list.jobs });
        return res.job_id ?? null;
      }
      dispatch({ type: "DRAFT_FAIL", error: res.error || "Job submission failed" });
      return null;
    },

    async refreshJobs() {
      const res = await apiListJobs();
      if (res.ok && res.jobs) {
        dispatch({ type: "JOBS_LOADED", jobs: res.jobs });
      }
    },

    async refreshUsageStats() {
      const stats = await fetchUsageStats();
      if (stats.ok) dispatch({ type: "USAGE_STATS_LOADED", stats });
    },

    async confirmPaidProceed() {
      const dialog = stateRef.current.paidConfirmDialog;
      if (!dialog) return;
      dispatch({ type: "CLOSE_PAID_CONFIRM" });
      if (dialog.pendingAction === "regenerate-image") {
        const scene = stateRef.current.draftResult?.scenes?.[dialog.pendingIndex];
        const source = scene?.image_source === "upload" ? "" : (scene?.image_source ?? "");
        await _doGenerateImage(dialog.pendingIndex, source);
      }
    },

    async confirmPaidUseFree() {
      const dialog = stateRef.current.paidConfirmDialog;
      if (!dialog) return;
      dispatch({ type: "CLOSE_PAID_CONFIRM" });
      if (dialog.pendingAction === "regenerate-image") {
        await _doGenerateImage(dialog.pendingIndex, "pexels");
      }
    },

    closePaidConfirm() {
      dispatch({ type: "CLOSE_PAID_CONFIRM" });
    },
  }); }, []);

  return (
    <StateCtx.Provider value={state}>
      <ActionsCtx.Provider value={actions}>
        {children}
      </ActionsCtx.Provider>
    </StateCtx.Provider>
  );
}

import { useState, useRef, useCallback, useEffect } from "react";
import {
  X,
  ImagePlus,
  Search,
  Upload,
  Play,
  Square,
  RefreshCw,
  Copy,
  Clapperboard,
  Captions,
  WandSparkles,
  CheckCircle2,
  AlertTriangle,
  CircleHelp,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";
import type { GrokBatchUploadMode } from "../context/StudioContext";
import {
  fetchFreeAudioCandidates,
  getGrokCompanionCommand,
  importFreeAudioAsset,
} from "../lib/bridge";
import type { BgmAssetPayload, CaptionPreset, FreeAssetScenePlan, FreeAudioCandidate, FreeTemplateAudioPlan, GrokAuthProvider, GrokCodexChromeObservation, GrokCompanionCommand, GrokHandoffAsset, LocalVideoProvider, MediaAdapterHealth, PexelsVideoCandidate, TemplateType, VisualSource, VisualQualityVerdict } from "../lib/bridge";

type FreeAssetLayoutVariant = NonNullable<FreeAssetScenePlan["layoutVariants"]>[number];
type GrokReviewVisualVerdict = "pass" | "needs-retry" | "fail" | "";

interface GrokReviewQualityFields {
  visualQualityVerdict: GrokReviewVisualVerdict;
  shotLockMatch: boolean;
  sceneAssemblyOk: boolean;
  shotLockEvidenceNote: string;
  sceneAssemblyRoleNote: string;
  captionLayoutReviewNote: string;
  continuityNote: string;
  hookNote: string;
  layoutVariantNote: string;
  thumbnailReviewNote: string;
  audioMixReviewNote: string;
  platformComparisonNote: string;
  sourceProvenanceConfirmed: boolean;
  sourceProvenanceNote: string;
}

const GROK_REVIEW_REQUIRED_NOTE_MIN = 24;

const SOURCE_OPTIONS: Array<{ key: VisualSource; label: string; icon: typeof Search }> = [
  { key: "upload", label: "내 MP4", icon: Upload },
  { key: "grok", label: "Grok", icon: Clapperboard },
  { key: "pexels-video", label: "Pexels 영상", icon: Search },
  { key: "wan", label: "Wan", icon: WandSparkles },
  { key: "ltx-video", label: "LTX", icon: WandSparkles },
  { key: "hunyuan-video", label: "Hunyuan", icon: WandSparkles },
  { key: "pexels", label: "이미지 fallback", icon: ImagePlus },
];

const CAPTION_PRESETS: Array<{ key: CaptionPreset; label: string }> = [
  { key: "none", label: "no caption" },
  { key: "center-short", label: "center short" },
  { key: "top-hook", label: "top hook" },
  { key: "lower-info", label: "lower info" },
];

const VISUAL_VERDICT_OPTIONS: Array<{
  key: VisualQualityVerdict | "";
  label: string;
  icon: LucideIcon;
  title: string;
}> = [
  { key: "", label: "미검수", icon: CircleHelp, title: "아직 contact sheet/최종 MP4를 보고 판정하지 않음" },
  { key: "pass", label: "통과", icon: CheckCircle2, title: "주 피사체, 자막, 워터마크, 압축, 컷 연결을 보고 통과 처리" },
  { key: "needs-rework", label: "재작업", icon: AlertTriangle, title: "장면 교체 또는 자막/레이아웃 재작업 필요" },
  { key: "fail", label: "탈락", icon: AlertTriangle, title: "이 씬은 업로드 후보에서 제외" },
];

const GROK_AUTH_PROVIDER_OPTIONS: Array<{ key: GrokAuthProvider; label: string }> = [
  { key: "google", label: "Google" },
  { key: "x", label: "X" },
  { key: "email", label: "email" },
  { key: "apple", label: "Apple" },
  { key: "manual", label: "manual" },
];

const LOCAL_PROVIDER_BY_SOURCE: Partial<Record<VisualSource, "wan" | "ltx-video" | "hunyuan-video">> = {
  wan: "wan",
  "ltx-video": "ltx-video",
  "hunyuan-video": "hunyuan-video",
};

const LOCAL_MODEL_LABEL: Record<LocalVideoProvider, string> = {
  wan: "Wan",
  "ltx-video": "LTX",
  "hunyuan-video": "Hunyuan",
};

const LOCAL_MODEL_ENV_PREFIX: Record<LocalVideoProvider, string> = {
  wan: "VIDEO_STUDIO_WAN",
  "ltx-video": "VIDEO_STUDIO_LTX_VIDEO",
  "hunyuan-video": "VIDEO_STUDIO_HUNYUAN_VIDEO",
};

const TEMPLATE_SOURCE_GUIDANCE: Partial<Record<TemplateType, {
  sourceMix: string;
  freeAssets: string;
  proof: string;
  layout: string;
  avoid: string;
}>> = {
  news_explainer: {
    sourceMix: "Pexels/Pixabay/Wikimedia context cuts; first hook needs visible motion.",
    freeAssets: "Pexels Video, Pixabay Video, Wikimedia Commons, YouTube Audio Library",
    proof: "source URL/ID, creator, license/attribution note, why the cut matches the fact",
    layout: "top hook, then small lower facts inside the safe zone",
    avoid: "stock top-1 that only vaguely matches the narration",
  },
  ranking_list: {
    sourceMix: "One distinct clip per rank; no repeated B-roll loop.",
    freeAssets: "Pexels/Pixabay candidates per item; direct screenshots only with rights",
    proof: "selected candidate ID/source URL per rank and manual selection rationale",
    layout: "stable rank label, restrained captions, consistent cut rhythm",
    avoid: "same background reused across multiple ranks",
  },
  tutorial_steps: {
    sourceMix: "Direct screen/hand capture first; stock only as support.",
    freeAssets: "direct recording, CC0 icons, Pexels/Pixabay support clips",
    proof: "step action visible in the clip and caption does not cover the action",
    layout: "top step label plus lower-info detail",
    avoid: "explaining steps over unrelated lifestyle stock",
  },
  authentic_vlog: {
    sourceMix: "Direct MP4 first, then Pexels/Pixabay support B-roll.",
    freeAssets: "operator footage, Pexels/Pixabay, YouTube Audio Library or Mixkit BGM",
    proof: "where/why this moment was filmed or curated; ambient-first pacing note",
    layout: "full-frame motion, no caption or lower-info only",
    avoid: "over-large center captions and stock clips that feel like ads",
  },
  persona_story: {
    sourceMix: "Grok/SuperGrok or local Wan/LTX/Hunyuan hero, consistent bible.",
    freeAssets: "Grok app/web MP4, local model output, Pexels texture inserts",
    proof: "character/place/prop continuity and prompt/generation provenance",
    layout: "scene 1 top hook; later captions lower-info or none",
    avoid: "face/outfit/prop drift between scenes",
  },
  kculture_fandom: {
    sourceMix: "Copyright-safe substitute visuals, direct event footage only with rights.",
    freeAssets: "direct fan/event footage, CC/stock city-stage B-roll, YouTube Audio Library",
    proof: "rights-safe rationale and attribution/license note for every source",
    layout: "beat-friendly cuts, small safe-zone callouts",
    avoid: "original MV, drama, anime, broadcast, or commercial music footage",
  },
  podcast_clip: {
    sourceMix: "Owned long-form clip or TTS summary with B-roll/chapter cards.",
    freeAssets: "owned source clip, Freesound SFX, YouTube Audio Library bed",
    proof: "source ownership or summary-TTS rationale plus timestamp/chapter note",
    layout: "speaker crop/waveform/chapter card, lower captions only when needed",
    avoid: "imitating an unowned speaker with generated voice",
  },
  longform_deep_dive: {
    sourceMix: "Chapter cards, operator-made data/source cards, and manually selected evidence B-roll.",
    freeAssets: "Pexels/Pixabay/Wikimedia for context, YouTube Audio Library/Mixkit for low BGM",
    proof: "source URL/license for every evidence cut plus why each chart/card supports the chapter",
    layout: "chapter/title card rhythm, lower facts, no Shorts-sized center captions",
    avoid: "turning a long-form explainer into a fast stock montage",
  },
  interview_documentary: {
    sourceMix: "Owned interview/location footage first; TTS summary only when source audio rights are absent.",
    freeAssets: "direct interview, location B-roll, Freesound ambience, Wikimedia evidence images/video",
    proof: "interview ownership/timestamp or explicit TTS-summary fallback and attribution notes",
    layout: "speaker or hands stay visible; compact lower captions avoid faces and hands",
    avoid: "AI voice impersonation or stock actors pretending to be the interview subject",
  },
  live_recap: {
    sourceMix: "Direct event footage plus rights-safe venue/city/crowd context and ambient inserts.",
    freeAssets: "direct phone MP4, Mixkit/Pexels stage-light/city B-roll, YouTube Audio Library BGM",
    proof: "event footage ownership, no copyrighted performance audio, and BGM/license note",
    layout: "route/point chapter chips with small safe-zone callouts",
    avoid: "unlicensed concert audio, broadcast clips, MV/drama/anime inserts",
  },
};

const GROK_OPERATOR_WAIT_DEFAULT_SECONDS = 3600;
const GROK_OPERATOR_WAIT_MAX_SECONDS = 7200;

function isLocalModelSource(value: VisualSource): value is LocalVideoProvider {
  return value === "wan" || value === "ltx-video" || value === "hunyuan-video";
}

function localModelLabel(source: VisualSource): string {
  return isLocalModelSource(source) ? LOCAL_MODEL_LABEL[source] : "Local model";
}

function normalizeSource(value?: string): VisualSource {
  const mapped = value === "flux" || value === "imagen3" || value === "imagen"
    ? "pexels"
    : value;
  return SOURCE_OPTIONS.some((option) => option.key === mapped)
    ? (mapped as VisualSource)
    : "pexels-video";
}

function defaultGrokPrompt(scene: {
  image_prompt?: string;
  display_text?: string;
  narration?: string;
}): string {
  const rawBase = scene.image_prompt || scene.display_text || scene.narration || "cinematic short-form scene";
  const compactBase = rawBase.toLowerCase().replace(/\s+/g, "");
  const productionMetaSeed = [
    "이영상은",
    "이번영상은",
    "영상의의도",
    "어떤의도",
    "의도를설명",
    "시청자가지금무엇을봐야",
    "나레이션으로설명",
    "자막으로설명",
    "티티에스",
  ].some((term) => compactBase.includes(term))
    || /\b(tts|voiceover|narration|subtitle plan|caption plan|layout plan|checklist|render|production intent)\b/i.test(rawBase);
  const base = productionMetaSeed
    ? "A concrete visible action from this scene with a clear subject, place, prop, and camera move"
    : rawBase;
  return [
    base,
    "Create raw footage for editing, not a finished social video.",
    "Vertical 9:16 photorealistic MP4, 4-6 seconds, one continuous shot.",
    "Show one concrete visible action with motion starting in the first second.",
    "Do not explain the video's intent, narration plan, caption plan, or production checklist.",
    "Use natural camera movement, consistent subject, setting, props, palette, and caption-safe framing.",
    "Leave the lower third and right edge clean for later Video Studio captions and YouTube Shorts UI.",
    "No captions, logos, watermarks, UI overlay, explanatory title card, or baked-in text.",
  ].join(" ");
}

function defaultLocalModelPrompt(scene: {
  image_prompt?: string;
  display_text?: string;
  narration?: string;
}, source: LocalVideoProvider): string {
  const base = scene.image_prompt || scene.display_text || scene.narration || "cinematic short-form scene";
  return [
    base,
    `Generate a 9:16 vertical MP4 for ${LOCAL_MODEL_LABEL[source]}. Duration 4-6 seconds.`,
    "Use realistic motion, consistent subject/setting/props, stable camera movement, and no baked-in text.",
    "Export as MP4, then upload it back to this scene for subtitles, BGM, and final render.",
  ].join(" ");
}

function candidateLabel(candidate: PexelsVideoCandidate): string {
  return `${candidate.duration.toFixed(1)}s / ${candidate.width}x${candidate.height}`;
}

function grokCandidateLabel(candidate: GrokHandoffAsset): string {
  const probe = candidate.clipProbe;
  const dimensions = probe?.width && probe?.height ? `${probe.width}x${probe.height}` : "size ?";
  const fps = typeof probe?.fps === "number" ? `${probe.fps.toFixed(1)}fps` : "fps ?";
  const duration = typeof probe?.durationSec === "number" ? `${probe.durationSec.toFixed(1)}s` : "duration ?";
  const audio = probe?.hasAudio ? "audio" : "no audio";
  return `${dimensions} / ${fps} / ${duration} / ${audio}`;
}

function baseNameFromPath(path?: string | null): string {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";
}

function audioMimeFromPath(path?: string | null): string {
  const lower = String(path || "").toLowerCase();
  if (lower.endsWith(".wav")) return "audio/wav";
  if (lower.endsWith(".ogg")) return "audio/ogg";
  if (lower.endsWith(".m4a")) return "audio/mp4";
  if (lower.endsWith(".flac")) return "audio/flac";
  return "audio/mpeg";
}

function readAudioFileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Could not read audio file."));
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",", 2)[1] : result);
    };
    reader.readAsDataURL(file);
  });
}

function adapterReadinessLabel(status?: MediaAdapterHealth): string {
  if (!status) return "health unknown";
  if (status.ready) return "command ready";
  if (status.mode === "off") return "off";
  if (status.mode === "stub") return "request packet";
  return "not ready";
}

function adapterReadinessClass(status?: MediaAdapterHealth): string {
  if (status?.ready) return "ready";
  if (status?.mode === "off") return "off";
  return "stub";
}

function automationStatusLabel(status?: string): string {
  if (status === "imported") return "MP4 synced";
  if (status === "completed") return "completed";
  if (status === "running") return "running";
  if (status === "queued") return "queued";
  if (status === "waiting-for-operator") return "waiting for operator";
  if (status === "needs-operator") return "operator needed";
  if (status === "injected") return "prompt injected";
  if (status === "preflight") return "preflight";
  if (status === "failed") return "failed";
  return "approval gated";
}

function automationStatusClass(status?: string): string {
  if (status === "imported" || status === "completed") return "ready";
  if (status === "needs-operator" || status === "failed") return "blocked";
  if (status === "injected" || status === "preflight" || status === "queued" || status === "running" || status === "waiting-for-operator") return "active";
  return "stub";
}

function grokGateStatusLabel(status?: string): string {
  if (status === "accepted") return "accepted hero";
  if (status === "pending-operator-review") return "review pending";
  if (status === "technical-review") return "technical review";
  if (status === "source-review") return "source review";
  if (status === "rejected") return "rejected";
  if (status === "missing") return "MP4 missing";
  if (status === "review-recommended") return "review recommended";
  return "not synced";
}

function grokGateStatusClass(status?: string): string {
  if (status === "accepted") return "ready";
  if (status === "pending-operator-review" || status === "review-recommended") return "active";
  if (status === "missing" || status === "rejected" || status === "technical-review" || status === "source-review") return "blocked";
  return "stub";
}

function grokSourceProvenanceLabel(status?: string): string {
  if (status === "browser-native-original-download") return "direct/original import";
  if (status === "visible-video-fallback-proof-only") return "proof-only preview";
  if (status === "local-mp4-download-unverified") return "local MP4 - verify";
  if (status === "local-mp4-source-unverified") return "source unverified";
  return "source unknown";
}

function grokSourceProvenanceClass(status?: string, acceptAsMain?: boolean): string {
  if (status === "browser-native-original-download") return "pass";
  if (acceptAsMain === false || status === "visible-video-fallback-proof-only") return "fail";
  if (status === "local-mp4-download-unverified" || status === "local-mp4-source-unverified") return "neutral";
  return "neutral";
}

function grokSourceProvenanceConfirmationRequired(status?: string, acceptAsMain?: boolean): boolean {
  if (acceptAsMain === false) return false;
  return status === "local-mp4-download-unverified" || status === "local-mp4-source-unverified";
}

function isGenericGrokReviewEvidence(value?: string): boolean {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return true;
  return [
    "manual grok handoff clip for scene",
    "operator-approved grok web handoff mp4 synced",
    "uploaded operator-selected visual",
    "dashboard accepted grok handoff clip",
    "dashboard rejected grok handoff clip",
  ].some((prefix) => normalized.startsWith(prefix));
}

export default function SceneDetailPanel() {
  const { draftResult, selectedSceneIndex, grokHandoff, bridgeHealth, templateType, freeAssetPacket, selectedBgmAsset } = useStudioState();
  const actions = useStudioActions();
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [promptDraft, setPromptDraft] = useState("");
  const [editingNarration, setEditingNarration] = useState(false);
  const [narrationDraft, setNarrationDraft] = useState("");
  const [regenerating, setRegenerating] = useState(false);
  const [regeneratingImage, setRegeneratingImage] = useState(false);
  const [searchingPexels, setSearchingPexels] = useState(false);
  const [creatingAssetPacket, setCreatingAssetPacket] = useState(false);
  const [creatingGrokHandoff, setCreatingGrokHandoff] = useState(false);
  const [openingGrok, setOpeningGrok] = useState(false);
  const [syncingGrok, setSyncingGrok] = useState(false);
  const [renderingGrok, setRenderingGrok] = useState(false);
  const [loadingGrokPlan, setLoadingGrokPlan] = useState(false);
  const [focusingGrokOperator, setFocusingGrokOperator] = useState(false);
  const [cleaningGrokTabs, setCleaningGrokTabs] = useState(false);
  const [importingGrokDownloads, setImportingGrokDownloads] = useState(false);
  const [uploadingGrokMp4, setUploadingGrokMp4] = useState(false);
  const [watchingGrokDownloads, setWatchingGrokDownloads] = useState(false);
  const [startingGrokManualWatch, setStartingGrokManualWatch] = useState(false);
  const [startingGrokManualWatchAll, setStartingGrokManualWatchAll] = useState(false);
  const [runningGrokOperator, setRunningGrokOperator] = useState(false);
  const [runningGrokBrowserAutomation, setRunningGrokBrowserAutomation] = useState(false);
  const [startingGrokBackgroundAutomation, setStartingGrokBackgroundAutomation] = useState(false);
  const [startingNextGrokBackgroundAutomation, setStartingNextGrokBackgroundAutomation] = useState(false);
  const [restartingGrokBackgroundAutomation, setRestartingGrokBackgroundAutomation] = useState(false);
  const [attachingDefaultChromeGrok, setAttachingDefaultChromeGrok] = useState(false);
  const [resumingGrokAutomation, setResumingGrokAutomation] = useState(false);
  const [generatingLocalVideo, setGeneratingLocalVideo] = useState(false);
  const [importingLocalFolder, setImportingLocalFolder] = useState(false);
  const [savingGrokReview, setSavingGrokReview] = useState(false);
  const [grokDownloadDir, setGrokDownloadDir] = useState("");
  const [localFolderDir, setLocalFolderDir] = useState("");
  const [grokAuthWaitSeconds, setGrokAuthWaitSeconds] = useState(String(GROK_OPERATOR_WAIT_DEFAULT_SECONDS));
  const [grokAuthProvider, setGrokAuthProvider] = useState<GrokAuthProvider>("google");
  const [grokReviewOperatorNote, setGrokReviewOperatorNote] = useState("");
  const [grokCandidateSummary, setGrokCandidateSummary] = useState("");
  const [selectedGrokCandidateFileName, setSelectedGrokCandidateFileName] = useState("");
  const [grokReviewQualityFields, setGrokReviewQualityFields] = useState<GrokReviewQualityFields>({
    visualQualityVerdict: "",
    shotLockMatch: false,
    sceneAssemblyOk: false,
    shotLockEvidenceNote: "",
    sceneAssemblyRoleNote: "",
    captionLayoutReviewNote: "",
    continuityNote: "",
    hookNote: "",
    layoutVariantNote: "",
    thumbnailReviewNote: "",
    audioMixReviewNote: "",
    platformComparisonNote: "",
    sourceProvenanceConfirmed: false,
    sourceProvenanceNote: "",
  });
  const [grokReviewChecks, setGrokReviewChecks] = useState({
    firstTwoSecondHook: false,
    artifactFree: false,
    continuityOk: false,
    captionSafe: false,
  });
  const [copied, setCopied] = useState(false);
  const [audioCandidates, setAudioCandidates] = useState<FreeAudioCandidate[]>([]);
  const [audioPlan, setAudioPlan] = useState<FreeTemplateAudioPlan | null>(null);
  const [selectedAudioCandidateId, setSelectedAudioCandidateId] = useState("");
  const [audioImportPath, setAudioImportPath] = useState("");
  const [audioImportFile, setAudioImportFile] = useState<File | null>(null);
  const [voiceoverImportPath, setVoiceoverImportPath] = useState("");
  const [voiceoverImportFile, setVoiceoverImportFile] = useState<File | null>(null);
  const [searchingAudioCandidates, setSearchingAudioCandidates] = useState(false);
  const [importingAudioAsset, setImportingAudioAsset] = useState(false);
  const [importingVoiceoverAsset, setImportingVoiceoverAsset] = useState(false);
  const [audioCandidateError, setAudioCandidateError] = useState<string | null>(null);
  const [audioImportResult, setAudioImportResult] = useState<string | null>(null);
  const [voiceoverImportResult, setVoiceoverImportResult] = useState<string | null>(null);
  const [voiceoverImportError, setVoiceoverImportError] = useState<string | null>(null);
  const [loadingGrokFallbackAction, setLoadingGrokFallbackAction] = useState<string | null>(null);
  const [grokFallbackActionResult, setGrokFallbackActionResult] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const grokDownloadDirPrefillRef = useRef<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const grokUploadBatchModeRef = useRef<GrokBatchUploadMode>("auto");
  const audioImportFileRef = useRef<HTMLInputElement>(null);
  const voiceoverImportFileRef = useRef<HTMLInputElement>(null);
  const selectedScene = selectedSceneIndex !== null ? draftResult?.scenes?.[selectedSceneIndex] : null;
  const selectedHandoffSceneId = selectedScene
    ? `scene-${String(selectedScene.scene_num || (selectedSceneIndex ?? 0) + 1).padStart(2, "0")}`
    : null;
  const selectedGrokReviewDecision = selectedHandoffSceneId
    ? grokHandoff?.reviewDecisions?.[selectedHandoffSceneId]
    : undefined;
  const selectedHandoffGrokAsset = selectedHandoffSceneId
    ? grokHandoff?.assets?.find((item) => item.sceneId === selectedHandoffSceneId && item.status === "ready")
      || grokHandoff?.assets?.find((item) => item.sceneId === selectedHandoffSceneId)
    : undefined;
  const selectedHandoffCandidateAssets = selectedHandoffGrokAsset?.status === "ready"
    ? (
        selectedHandoffGrokAsset.candidateAssets?.length
          ? selectedHandoffGrokAsset.candidateAssets
          : [selectedHandoffGrokAsset]
      ).filter((item): item is GrokHandoffAsset => Boolean(item?.fileName))
    : [];
  const selectedHandoffCandidateKey = selectedHandoffCandidateAssets
    .map((item) => `${item.fileName || ""}:${item.selected ? "1" : "0"}`)
    .join("|");

  // Cleanup audio on scene switch or unmount
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = "";
        audioRef.current = null;
      }
      setPlaying(false);
    };
  }, [selectedSceneIndex]);

  const playTts = useCallback((url: string) => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current.src = ""; }
    const audio = new Audio(url);
    audioRef.current = audio;
    setPlaying(true);
    audio.play().catch(() => {});
    audio.addEventListener("ended", () => setPlaying(false), { once: true });
  }, []);

  const stopTts = useCallback(() => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current.src = ""; audioRef.current = null; }
    setPlaying(false);
  }, []);

  useEffect(() => {
    setGrokReviewOperatorNote(selectedGrokReviewDecision?.operatorNote || "");
    setGrokCandidateSummary(selectedGrokReviewDecision?.selectedCandidateSummary || selectedGrokReviewDecision?.singleCandidateJustification || "");
    setGrokReviewQualityFields({
      visualQualityVerdict: (selectedGrokReviewDecision?.visualQualityVerdict === "pass"
        || selectedGrokReviewDecision?.visualQualityVerdict === "needs-retry"
        || selectedGrokReviewDecision?.visualQualityVerdict === "fail")
        ? selectedGrokReviewDecision.visualQualityVerdict
        : "",
      shotLockMatch: selectedGrokReviewDecision?.shotLockMatch === true,
      sceneAssemblyOk: selectedGrokReviewDecision?.sceneAssemblyOk === true,
      shotLockEvidenceNote: selectedGrokReviewDecision?.shotLockEvidenceNote || "",
      sceneAssemblyRoleNote: selectedGrokReviewDecision?.sceneAssemblyRoleNote || "",
      captionLayoutReviewNote: selectedGrokReviewDecision?.captionLayoutReviewNote || "",
      continuityNote: selectedGrokReviewDecision?.continuityNote || "",
      hookNote: selectedGrokReviewDecision?.hookNote || "",
      layoutVariantNote: selectedGrokReviewDecision?.layoutVariantNote || "",
      thumbnailReviewNote: selectedGrokReviewDecision?.thumbnailReviewNote || "",
      audioMixReviewNote: selectedGrokReviewDecision?.audioMixReviewNote || "",
      platformComparisonNote: selectedGrokReviewDecision?.platformComparisonNote || "",
      sourceProvenanceConfirmed: selectedGrokReviewDecision?.sourceProvenanceConfirmed === true,
      sourceProvenanceNote: selectedGrokReviewDecision?.sourceProvenanceNote || "",
    });
    setGrokReviewChecks({
      firstTwoSecondHook: selectedGrokReviewDecision?.firstTwoSecondHook === true,
      artifactFree: selectedGrokReviewDecision?.artifactFree === true,
      continuityOk: selectedGrokReviewDecision?.continuityOk === true,
      captionSafe: selectedGrokReviewDecision?.captionSafe === true,
    });
  }, [
    selectedGrokReviewDecision?.operatorNote,
    selectedGrokReviewDecision?.selectedCandidateSummary,
    selectedGrokReviewDecision?.singleCandidateJustification,
    selectedGrokReviewDecision?.visualQualityVerdict,
    selectedGrokReviewDecision?.shotLockMatch,
    selectedGrokReviewDecision?.sceneAssemblyOk,
    selectedGrokReviewDecision?.shotLockEvidenceNote,
    selectedGrokReviewDecision?.sceneAssemblyRoleNote,
    selectedGrokReviewDecision?.captionLayoutReviewNote,
    selectedGrokReviewDecision?.continuityNote,
    selectedGrokReviewDecision?.hookNote,
    selectedGrokReviewDecision?.layoutVariantNote,
    selectedGrokReviewDecision?.thumbnailReviewNote,
    selectedGrokReviewDecision?.audioMixReviewNote,
    selectedGrokReviewDecision?.platformComparisonNote,
    selectedGrokReviewDecision?.sourceProvenanceConfirmed,
    selectedGrokReviewDecision?.sourceProvenanceNote,
    selectedGrokReviewDecision?.firstTwoSecondHook,
    selectedGrokReviewDecision?.artifactFree,
    selectedGrokReviewDecision?.continuityOk,
    selectedGrokReviewDecision?.captionSafe,
    selectedHandoffSceneId,
  ]);

  useEffect(() => {
    const candidateFileNames = selectedHandoffCandidateAssets
      .map((item) => item.fileName)
      .filter((item): item is string => Boolean(item));
    const preferred = selectedGrokReviewDecision?.selectedFileName
      || selectedHandoffCandidateAssets.find((item) => item.selected)?.fileName
      || candidateFileNames[0]
      || "";
    setSelectedGrokCandidateFileName((current) => {
      if (current && candidateFileNames.includes(current)) return current;
      return preferred;
    });
  }, [
    selectedHandoffCandidateKey,
    selectedGrokReviewDecision?.selectedFileName,
    selectedHandoffSceneId,
  ]);

  useEffect(() => {
    const defaultDownloadDir = grokHandoff?.defaultDownloadDir;
    const key = grokHandoff?.projectId && defaultDownloadDir
      ? `${grokHandoff.projectId}:${defaultDownloadDir}`
      : null;
    if (key && defaultDownloadDir && !grokDownloadDir && grokDownloadDirPrefillRef.current !== key) {
      grokDownloadDirPrefillRef.current = key;
      setGrokDownloadDir(defaultDownloadDir);
    }
  }, [grokDownloadDir, grokHandoff?.defaultDownloadDir, grokHandoff?.projectId]);

  if (selectedSceneIndex === null || !selectedScene) return null;

  const scene = selectedScene;
  const currentSource = normalizeSource(scene.image_source);
  const sourceGuidance = TEMPLATE_SOURCE_GUIDANCE[templateType];
  const isVideoUpload = scene._upload_kind === "video";
  const isLocalModel = isLocalModelSource(currentSource);
  const localAdapterStatus = isLocalModel ? bridgeHealth?.media?.[currentSource] : undefined;
  const localAdapterEnvPrefix = isLocalModel ? LOCAL_MODEL_ENV_PREFIX[currentSource] : "";
  const handoffSceneId = `scene-${String(scene.scene_num || selectedSceneIndex + 1).padStart(2, "0")}`;
  const grokHandoffScene = grokHandoff?.scenes?.find((item) => item.sceneId === handoffSceneId);
  const grokTakePrompts = grokHandoffScene?.takePrompts || [];
  const grokPromptQuality = grokHandoffScene?.promptQuality;
  const grokProductionProfile = grokHandoff?.shotBible?.productionProfile;
  const grokDefaultDownloadDir = grokHandoff?.defaultDownloadDir || "";
  const grokEffectiveDownloadDir = grokDownloadDir.trim() || grokDefaultDownloadDir;
  const grokSceneAsset = selectedHandoffGrokAsset;
  const grokCandidateAssets = selectedHandoffCandidateAssets;
  const grokSelectedCandidateAsset = grokCandidateAssets.find((item) => item.fileName === selectedGrokCandidateFileName)
    || grokCandidateAssets.find((item) => item.selected)
    || (grokSceneAsset?.status === "ready" ? grokSceneAsset : undefined);
  const grokSelectedSourceProvenance = grokSelectedCandidateAsset?.sourceProvenance || grokSceneAsset?.sourceProvenance;
  const grokSelectedSourceAcceptable = grokSelectedSourceProvenance?.acceptAsGrokMainSource !== false;
  const grokSelectedSourceStatus = grokSelectedSourceProvenance?.status || "";
  const grokSceneQualityGate = grokSceneAsset?.qualityGate;
  const grokScenePreview = currentSource === "grok" ? grokSelectedCandidateAsset?.previewUrl || grokSceneAsset?.previewUrl || null : null;
  const videoPreview = isVideoUpload
    ? scene._upload_preview
    : (grokScenePreview || scene._video_url || scene._selected_pexels_video?.url || null);
  const imagePreview = isVideoUpload ? null : (scene._upload_preview || scene._image_url || null);
  const captionPreset = scene.caption_preset || "lower-info";
  const assetScenePlan: FreeAssetScenePlan | undefined = freeAssetPacket?.scenes?.find((item) => item.sceneId === handoffSceneId);
  const grokReviewDecision = grokHandoff?.reviewDecisions?.[handoffSceneId];
  const canReviewGrokScene = Boolean(grokHandoff?.projectId && (videoPreview || grokSceneAsset?.status === "ready"));
  const grokSourceRationale = String(scene.source_rationale || "").trim();
  const grokQualityReviewNote = String(scene.quality_review_note || "").trim();
  const grokReviewEvidenceReady = !isGenericGrokReviewEvidence(grokSourceRationale)
    && grokSourceRationale.length >= 24
    && grokQualityReviewNote.length >= 24;
  const grokCandidateEvidenceRequired = Boolean(grokHandoff?.mainSourceGate?.required && currentSource === "grok");
  const grokCandidateTakeCountReady = !grokCandidateEvidenceRequired || grokCandidateAssets.length >= 2;
  const grokCandidateSummaryReady = !grokCandidateEvidenceRequired || grokCandidateSummary.trim().length >= 24;
  const grokCandidateEvidenceReady = grokCandidateTakeCountReady && grokCandidateSummaryReady;
  const grokSourceConfirmationRequired = grokCandidateEvidenceRequired && grokSourceProvenanceConfirmationRequired(
    grokSelectedSourceStatus,
    grokSelectedSourceProvenance?.acceptAsGrokMainSource,
  );
  const grokSourceConfirmationReady = !grokSourceConfirmationRequired
    || (
      grokReviewQualityFields.sourceProvenanceConfirmed
      && grokReviewQualityFields.sourceProvenanceNote.trim().length >= GROK_REVIEW_REQUIRED_NOTE_MIN
    );
  const grokDetailedReviewRequired = grokCandidateEvidenceRequired;
  const grokDetailedReviewMissing = [
    grokReviewQualityFields.visualQualityVerdict === "pass" ? "" : "visual pass",
    grokReviewQualityFields.shotLockMatch ? "" : "shot-lock match",
    grokReviewQualityFields.sceneAssemblyOk ? "" : "scene assembly",
    grokReviewQualityFields.shotLockEvidenceNote.trim().length >= GROK_REVIEW_REQUIRED_NOTE_MIN ? "" : "shot-lock evidence",
    grokReviewQualityFields.sceneAssemblyRoleNote.trim().length >= GROK_REVIEW_REQUIRED_NOTE_MIN ? "" : "scene role",
    grokReviewQualityFields.captionLayoutReviewNote.trim().length >= GROK_REVIEW_REQUIRED_NOTE_MIN ? "" : "caption/layout",
    grokReviewQualityFields.continuityNote.trim().length >= GROK_REVIEW_REQUIRED_NOTE_MIN ? "" : "continuity",
    grokReviewQualityFields.hookNote.trim().length >= GROK_REVIEW_REQUIRED_NOTE_MIN ? "" : "first 2s hook",
    grokReviewQualityFields.layoutVariantNote.trim().length >= GROK_REVIEW_REQUIRED_NOTE_MIN ? "" : "layout variant",
    grokReviewQualityFields.thumbnailReviewNote.trim().length >= GROK_REVIEW_REQUIRED_NOTE_MIN ? "" : "thumbnail",
    grokReviewQualityFields.audioMixReviewNote.trim().length >= GROK_REVIEW_REQUIRED_NOTE_MIN ? "" : "audio mix",
    grokReviewQualityFields.platformComparisonNote.trim().length >= GROK_REVIEW_REQUIRED_NOTE_MIN ? "" : "platform compare",
  ].filter(Boolean);
  const grokDetailedReviewReady = !grokDetailedReviewRequired || grokDetailedReviewMissing.length === 0;
  const grokReviewStatus = grokReviewDecision
    ? grokReviewDecision.accepted ? "accepted" : "rejected"
    : "unreviewed";
  const grokReviewAllRequiredChecks = Object.values(grokReviewChecks).every(Boolean);
  const grokReviewApprovalReady = grokReviewAllRequiredChecks
    && grokReviewEvidenceReady
    && grokCandidateEvidenceReady
    && grokDetailedReviewReady
    && grokSourceConfirmationReady
    && grokSelectedSourceAcceptable;
  const grokReviewStatusLabel = grokReviewStatus === "accepted"
    ? "승인"
    : grokReviewStatus === "rejected" ? "탈락" : "미검수";
  const grokAutomationStatus = grokHandoff?.automationStatus;
  const grokAutomationJob = grokHandoff?.automationJob;
  const grokManualDownloadWatchJob = grokHandoff?.manualDownloadWatchJob;
  const grokQualityGate = grokHandoff?.qualityGate;
  const grokMainSourceGate = grokHandoff?.mainSourceGate;
  const grokManualPrimaryPath = grokHandoff?.manualPrimaryPath;
  const grokMainPathStatus = grokHandoff?.mainPathStatus;
  const grokBrowserControlRail = grokHandoff?.browserControlPrimaryRail;
  const grokAssetAcquisition = grokHandoff?.grokAssetAcquisition || grokMainPathStatus?.assetAcquisition;
  const grokMainSourceDiagnosis = grokHandoff?.grokMainSourceDiagnosis;
  const grokCodexChromeObservation = (grokHandoff?.codexChromeObservation || grokMainPathStatus?.generationObservation) as GrokCodexChromeObservation | undefined;
  const grokObservedPostImportPlan = grokHandoff?.observedPostImportPlan || grokMainPathStatus?.observedPostImportPlan;
  const grokOriginalExportPlan = grokAssetAcquisition?.originalExportPlan || grokMainPathStatus?.originalExportPlan;
  const grokCandidateCurationPlan = grokAssetAcquisition?.candidateCurationPlan;
  const grokManualCurrentScene = grokManualPrimaryPath?.currentScene;
  const grokManualOperatorSteps = grokManualPrimaryPath?.operatorSteps || [];
  const grokManualQualityRules = grokManualPrimaryPath?.qualityRules || [];
  const grokPrimaryNextAction = grokBrowserControlRail?.operatorNextAction || grokHandoff?.primaryOperatorNextAction || grokManualPrimaryPath?.operatorNextAction;
  const grokGateRequired = grokQualityGate?.required || grokSceneQualityGate?.required || grokMainSourceGate?.required;
  const grokGateAcceptedCount = grokQualityGate?.readySceneIds?.length || 0;
  const grokGatePendingSceneIds = grokQualityGate?.pendingSceneIds || [];
  const grokGateRejectedSceneIds = grokQualityGate?.rejectedSceneIds || [];
  const grokGateMissingSceneIds = grokHandoff?.missingSceneIds || [];
  const grokGateBlockingSceneIds = Array.from(new Set([
    ...grokGateMissingSceneIds,
    ...grokGatePendingSceneIds,
    ...grokGateRejectedSceneIds,
    ...(grokMainSourceGate?.missingSceneIds || []),
    ...(grokMainSourceGate?.pendingSceneIds || []),
    ...(grokMainSourceGate?.rejectedSceneIds || []),
  ])).filter(Boolean);
  const grokMainAcceptedCount = grokMainSourceGate?.acceptedSceneIds?.length ?? grokGateAcceptedCount;
  const grokMainMinAccepted = grokMainSourceGate?.minAcceptedScenes ?? grokHandoff?.totalScenes;
  const grokMainPlannedCount = grokMainSourceGate?.plannedGrokScenes ?? grokHandoff?.totalScenes;
  const grokMainTotalCount = grokMainSourceGate?.sourceMixTotalScenes ?? grokHandoff?.totalScenes;
  const grokMainAdditionalAccepted = grokMainSourceGate?.additionalAcceptedScenesNeeded || 0;
  const grokMainAdditionalPlanned = grokMainSourceGate?.additionalPlannedScenesNeeded || 0;
  const grokMainPathStatusClass = grokMainPathStatus?.status === "ready"
    ? "ready"
    : grokMainPathStatus?.blocked ? "active" : "blocked";
  const grokHasPacket = Boolean(grokHandoff?.projectId);
  const nativeGrokDownloadFallbackBlocked = true;
  const nativeGrokDownloadFallbackTitle = "Blocked: Chrome/Grok Download/Save/Export prompts can stall until an operator clicks them. Use operator-owned local MP4 download/import or explicit batch upload.";
  const grokHasCurrentMp4 = grokSceneAsset?.status === "ready";
  const grokCurrentAccepted = grokSceneQualityGate?.status === "accepted" || selectedGrokReviewDecision?.accepted === true;
  const grokMainReady = grokMainSourceGate?.status === "ready";
  const grokPreviewReadyCount = (grokHandoff?.assets || []).filter(
    (asset) => asset.status === "ready" && asset.sourcePath,
  ).length;
  const grokPreviewReady = grokPreviewReadyCount > 0;
  const grokRailNeedsManualHandoff = true;
  const grokProductionRailSteps = [
    {
      key: "packet",
      label: "1. packet",
      state: grokHasPacket ? "pass" : "active",
      detail: grokHasPacket ? `active ${grokHandoff?.projectId}` : "create the scene packet first",
    },
    {
      key: "grok-generate",
      label: "2. Grok generate",
      state: grokHasCurrentMp4 ? "pass" : grokHasPacket ? "active" : "blocked",
      detail: grokHasCurrentMp4
        ? "MP4 imported for this scene"
        : "use logged-in Grok app/web, not the paid API",
    },
    {
      key: "import",
      label: "3. import",
      state: grokHasCurrentMp4 ? "pass" : grokHasPacket ? "active" : "blocked",
      detail: grokHasCurrentMp4
        ? grokSceneAsset?.fileName || "scene MP4 ready"
        : `expected ${grokHandoffScene?.expectedFileName || `${handoffSceneId}.grok.mp4`}`,
    },
    {
      key: "review",
      label: "4. review",
      state: grokCurrentAccepted ? "pass" : grokHasCurrentMp4 ? "active" : "blocked",
      detail: grokCurrentAccepted
        ? "accepted for render"
        : "first 2s hook, artifacts, continuity, caption-safe",
    },
    {
      key: "render",
      label: "5. render gate",
      state: grokMainReady ? "pass" : "blocked",
      detail: grokMainReady
        ? "Grok-main source mix ready"
        : `${grokMainAcceptedCount}/${grokMainMinAccepted || "?"} accepted Grok scenes`,
    },
  ];
  const isGrokBackgroundPolling = grokAutomationJob?.status === "queued"
    || grokAutomationJob?.status === "running"
    || grokAutomationJob?.status === "waiting-for-operator";
  const isGrokManualWatchPolling = (
    grokManualDownloadWatchJob?.status === "queued"
    || grokManualDownloadWatchJob?.status === "running"
  )
    && grokManualDownloadWatchJob?.activeThread !== false
    && grokManualDownloadWatchJob?.stale !== true
    && grokManualDownloadWatchJob?.restartAvailable !== true;
  const grokObservedPostSceneId = grokObservedPostImportPlan?.sceneId
    || grokCodexChromeObservation?.sceneId
    || grokMainPathStatus?.nextSceneId
    || handoffSceneId;
  const grokObservedPostExpectedFile = grokObservedPostImportPlan?.expectedFileName
    || grokCodexChromeObservation?.expectedFileName
    || grokMainPathStatus?.nextExpectedFileName
    || `${grokObservedPostSceneId}.grok.mp4`;
  const grokBestLocalCandidate = grokAssetAcquisition?.bestLocalCandidate;
  const grokPrimaryReplacementScene = String(grokMainPathStatus?.primaryNextAction || "")
    .match(/replace\s+(scene-\d+)/i)?.[1];
  const grokOriginalExpectedScene = grokMainPathStatus?.nextSceneId
    && !grokAssetAcquisition?.qualityBlocked
    ? grokMainPathStatus.nextSceneId
    : grokPrimaryReplacementScene
    || grokBestLocalCandidate?.sceneId
    || grokManualCurrentScene?.sceneId
    || grokHandoff?.nextMissingSceneId
    || handoffSceneId;
  const grokOriginalExpectedFile = grokPrimaryReplacementScene || grokBestLocalCandidate?.sceneId
    ? `${grokOriginalExpectedScene}.grok.mp4`
    : grokMainPathStatus?.nextExpectedFileName
    || grokManualCurrentScene?.expectedFileName
    || grokHandoff?.nextMissingExpectedFileName
    || `${grokOriginalExpectedScene}.grok.mp4`;
  const grokBestLocalDimensions = grokBestLocalCandidate?.width && grokBestLocalCandidate?.height
    ? `${grokBestLocalCandidate.width}x${grokBestLocalCandidate.height}`
    : "not probed";
  const grokBestLocalSourceStatus = grokBestLocalCandidate?.sourceProvenance?.status
    || grokSceneAsset?.sourceProvenance?.status
    || "";
  const grokBestLocalSourceLabel = grokSourceProvenanceLabel(grokBestLocalSourceStatus);
  const grokOriginalRunwayNeedsReplacement = Boolean(
    grokAssetAcquisition
      && (grokAssetAcquisition.qualityBlocked || grokAssetAcquisition.publishReadyLocalMp4 === false),
  );
  const grokOriginalRunwayChecklist = [
    `Scene: ${grokOriginalExpectedScene}`,
    `Expected MP4: ${grokOriginalExpectedFile}`,
    `Import/manual-upload folder: ${grokEffectiveDownloadDir || grokHandoff?.incomingDir || "set the Grok import folder first"}`,
    `Prompt: ${scene.grok_prompt || defaultGrokPrompt(scene)}`,
    "Make 2 Grok takes for this scene, then keep the better one only after review.",
    "Use existing signed-in Chrome browser-control for generation; then operator downloads/saves the MP4 and imports it locally. Do not use currentSrc/cache/visible-video fallback as the main source.",
    "No baked-in text, captions, logos, UI overlay, watermark, title card, or production-intent explanation.",
    `Quality floor: ${grokAssetAcquisition?.sourceQualityFloor || "vertical 9:16 original MP4, publishable resolution, visible motion in first second"}`,
  ].join("\n");
  const grokProductionQueueUrl = grokHandoff?.productionQueueUrl || grokManualPrimaryPath?.productionQueueUrl || "";
  const grokReviewPacketUrl = grokHandoff?.reviewPacketUrl || grokManualPrimaryPath?.reviewPacketUrl || "";
  const grokPrimaryTakeNumber = Number(
    grokManualCurrentScene?.recommendedTakeNumber
      || grokMainPathStatus?.recommendedTakeNumber
      || (grokTakePrompts.length > 1 ? 2 : 1),
  );
  const grokPrimaryTakePrompt = grokTakePrompts.find((take) => Number(take.takeNumber || 1) === grokPrimaryTakeNumber)
    || grokTakePrompts[1]
    || grokTakePrompts[0];
  const grokPrimaryTakeLabel = grokPrimaryTakePrompt?.label
    || grokManualCurrentScene?.recommendedTakeLabel
    || grokMainPathStatus?.recommendedTakeLabel
    || "best motion take";
  const grokPrimaryTakeFocus = grokPrimaryTakePrompt?.focus
    || grokManualCurrentScene?.recommendedTakeFocus
    || "visible motion, stable subject, no baked-in text";
  const grokPrimaryPromptText = grokPrimaryTakePrompt?.prompt
    || grokManualCurrentScene?.prompt
    || scene.grok_prompt
    || defaultGrokPrompt(scene);
  const grokPrimaryWatchFolders = Array.from(new Set([
    ...(grokManualDownloadWatchJob?.downloadDirs || []),
    grokManualDownloadWatchJob?.downloadDir,
    grokEffectiveDownloadDir,
    grokHandoff?.incomingDir,
  ].filter(Boolean) as string[]));
  const grokPrimaryBlocker = grokAssetAcquisition?.primaryBlocker
    || grokMainSourceDiagnosis?.currentBlocker
    || grokOriginalExportPlan?.currentBlocker
    || grokMainPathStatus?.primaryNextAction
    || grokPrimaryNextAction
    || "native Grok MP4 import required";
  const grokPrimaryActionClass = grokCurrentAccepted
    ? "ready"
    : grokHasCurrentMp4 ? "review" : isGrokManualWatchPolling ? "watching" : "blocked";
  const grokPrimaryActionTitle = grokCurrentAccepted
    ? "Grok scene accepted; continue render gate"
    : grokHasCurrentMp4
      ? "Review this Grok MP4 before render"
      : `Replace ${grokOriginalExpectedScene} with 2 native Grok MP4 takes`;
  const grokPrimaryPromptPacket = [
    "GROK MAIN SOURCE PACKET",
    `Scene: ${grokOriginalExpectedScene}`,
    `Take: ${grokPrimaryTakeNumber} / ${grokPrimaryTakeLabel}`,
    `Focus: ${grokPrimaryTakeFocus}`,
    `Import target: ${grokOriginalExpectedFile}`,
    `Watched folders: ${grokPrimaryWatchFolders.length ? grokPrimaryWatchFolders.join(" | ") : "Downloads/Desktop/Videos via Video Studio watcher"}`,
    "",
    "Prompt:",
    grokPrimaryPromptText,
    "",
    "Reject before saving if: text is baked into the image, UI/logo/watermark is visible, subject changes identity, camera is static, output looks like a cache/proxy preview, or vertical quality is below publish-ready 9:16.",
    "After generation: operator downloads/saves the MP4, then uses local import or manual batch upload. Do not use currentSrc/cache/visible-video fallback as final footage.",
    "Import rule: preserve two takes for this scene, then select the better one in review.",
  ].join("\n");
  const grokObservedAssetUrl = String(grokCodexChromeObservation?.videoUrl || "").trim();
  const grokObservedManualRunwayReady = Boolean(
    grokHasPacket
      && grokObservedPostImportPlan?.observedAssetManualRunwayUrl
      && grokEffectiveDownloadDir
      && !startingGrokManualWatch
      && !openingGrok,
  );
  const grokObservedPostReady = Boolean(
    grokHasPacket
      && grokObservedPostImportPlan?.postUrl
      && grokEffectiveDownloadDir
      && !startingGrokManualWatch
      && !isGrokManualWatchPolling
      && !renderingGrok,
  );
  const grokObservedPostRecoveryReady = Boolean(
    grokHasPacket
      && grokObservedPostImportPlan?.observedPostDownloadConsoleSnippet
      && !loadingGrokFallbackAction,
  );
  const grokOperatorReadyWait = grokAutomationStatus?.operatorReadyWait as {
    attempts?: number;
    elapsedSeconds?: number;
    ready?: boolean;
    timedOut?: boolean;
  } | undefined;
  const grokJobElapsedSeconds = typeof grokAutomationJob?.elapsedSeconds === "number"
    ? Math.round(grokAutomationJob.elapsedSeconds)
    : null;
  const grokJobRemainingSeconds = typeof grokAutomationJob?.operatorWaitRemainingSeconds === "number"
    ? Math.round(grokAutomationJob.operatorWaitRemainingSeconds)
    : null;
  const grokManualWatchRemainingSeconds = typeof grokManualDownloadWatchJob?.remainingSeconds === "number"
    ? Math.round(grokManualDownloadWatchJob.remainingSeconds)
    : null;
  const recommendedAudioMood = freeAssetPacket?.bgmPlan?.recommendedMood
    || freeAssetPacket?.recommendedBgmMood
    || freeAssetPacket?.audioMood
    || "";
  const selectedAudioCandidate = audioCandidates.find((candidate) => candidate.id === selectedAudioCandidateId)
    || audioCandidates[0]
    || null;

  const handleSourceChange = (src: VisualSource) => {
    actions.editScene(selectedSceneIndex, "image_source", src);
    if (LOCAL_PROVIDER_BY_SOURCE[src]) {
      actions.editScene(selectedSceneIndex, "local_video_provider", LOCAL_PROVIDER_BY_SOURCE[src]);
    }
    if (src === "grok" && !scene.grok_prompt) {
      actions.editScene(selectedSceneIndex, "grok_prompt", defaultGrokPrompt(scene));
    }
    if (isLocalModelSource(src) && !scene.grok_prompt) {
      actions.editScene(selectedSceneIndex, "grok_prompt", defaultLocalModelPrompt(scene, src));
    }
    if (src === "upload") fileInputRef.current?.click();
  };

  const handlePromptEdit = () => {
    setPromptDraft(scene.image_prompt || "");
    setEditingPrompt(true);
  };

  const commitPrompt = () => {
    setEditingPrompt(false);
    if (promptDraft !== scene.image_prompt) {
      actions.editScene(selectedSceneIndex, "image_prompt", promptDraft);
    }
  };

  const handleNarrationEdit = () => {
    setNarrationDraft(scene.narration || "");
    setEditingNarration(true);
  };

  const commitNarration = () => {
    setEditingNarration(false);
    if (narrationDraft !== scene.narration) {
      actions.editScene(selectedSceneIndex, "narration", narrationDraft);
    }
  };

  const handleRegenTts = async () => {
    setRegenerating(true);
    try {
      await actions.regenerateSceneTts(selectedSceneIndex);
    } finally {
      setRegenerating(false);
    }
  };

  const handleRegenImage = async () => {
    setRegeneratingImage(true);
    try {
      await actions.regenerateSceneImage(selectedSceneIndex);
    } finally {
      setRegeneratingImage(false);
    }
  };

  const handleSearchPexels = async () => {
    setSearchingPexels(true);
    try {
      await actions.searchPexelsVideos(selectedSceneIndex);
    } finally {
      setSearchingPexels(false);
    }
  };

  const handleCreateAssetPacket = async () => {
    setCreatingAssetPacket(true);
    try {
      await actions.createFreeAssetSourcingPacket();
    } finally {
      setCreatingAssetPacket(false);
    }
  };

  const handleApplyLayoutVariant = (variant: FreeAssetLayoutVariant) => {
    const label = variant.label || variant.key;
    const note = [variant.scenePattern, variant.captionPlan].filter(Boolean).join(" / ");
    actions.editScene(selectedSceneIndex, "layout_variant_key", variant.key);
    actions.editScene(selectedSceneIndex, "layout_variant_label", label);
    actions.editScene(selectedSceneIndex, "layout_variant_note", note);
  };

  const handleFetchFreeAudioCandidates = async () => {
    setSearchingAudioCandidates(true);
    setAudioCandidateError(null);
    setAudioImportResult(null);
    try {
      const result = await fetchFreeAudioCandidates({
        templateType,
        variantKey: scene.layout_variant_key || undefined,
        mood: recommendedAudioMood || undefined,
        includeRisky: true,
        limit: 8,
      });
      if (!result.ok || !result.candidates?.length) {
        setAudioCandidates([]);
        setSelectedAudioCandidateId("");
        setAudioPlan(result.templateAudioPlan || null);
        setAudioCandidateError(result.error || "No free audio candidates returned.");
        return;
      }
      setAudioCandidates(result.candidates);
      setSelectedAudioCandidateId(result.candidates[0].id);
      setAudioPlan(result.templateAudioPlan || null);
    } catch (error) {
      setAudioPlan(null);
      setAudioCandidateError(error instanceof Error ? error.message : String(error));
    } finally {
      setSearchingAudioCandidates(false);
    }
  };

  const handleCopyAudioSource = async () => {
    if (!selectedAudioCandidate?.sourceUrl) return;
    try {
      await navigator.clipboard.writeText(selectedAudioCandidate.sourceUrl);
      setAudioImportResult("source URL copied");
    } catch {
      setAudioImportResult(selectedAudioCandidate.sourceUrl);
    }
  };

  const handleImportFreeAudioCandidate = async () => {
    if (!selectedAudioCandidate) {
      setAudioCandidateError("Select a free audio candidate first.");
      return;
    }
    const sourcePath = audioImportPath.trim();
    if (!sourcePath && !audioImportFile) {
      setAudioCandidateError("Downloaded audio file or local path is required.");
      return;
    }
    setImportingAudioAsset(true);
    setAudioCandidateError(null);
    setAudioImportResult(null);
    try {
      const sidecar = selectedAudioCandidate.sidecarTemplate || {};
      const targetRole = selectedAudioCandidate.importPayloadTemplate?.targetRole
        || (selectedAudioCandidate.kind === "sfx" || selectedAudioCandidate.kind === "sfx-pack" ? "sfx" : "bgm");
      const fileBase64 = audioImportFile ? await readAudioFileBase64(audioImportFile) : undefined;
      const result = await importFreeAudioAsset({
        operatorApproved: true,
        sourcePath: audioImportFile ? undefined : sourcePath,
        fileBase64,
        fileName: audioImportFile?.name,
        candidateId: selectedAudioCandidate.id,
        targetRole,
        mood: selectedAudioCandidate.importPayloadTemplate?.mood || selectedAudioCandidate.mood || recommendedAudioMood || "calm",
        provider: sidecar.provider || selectedAudioCandidate.provider,
        title: sidecar.title || selectedAudioCandidate.title,
        artist: sidecar.artist || selectedAudioCandidate.artist,
        sourceUrl: sidecar.sourceUrl || selectedAudioCandidate.sourceUrl,
        sourceLicense: sidecar.sourceLicense || selectedAudioCandidate.sourceLicense,
        licenseUrl: sidecar.licenseUrl || selectedAudioCandidate.licenseUrl,
        attribution: sidecar.attribution || selectedAudioCandidate.attribution,
        attributionRequired: sidecar.attributionRequired ?? selectedAudioCandidate.attributionRequired,
        kind: sidecar.kind || selectedAudioCandidate.kind,
        durationSec: sidecar.durationSec ?? selectedAudioCandidate.durationSec,
        editNotes: sidecar.editNotes || selectedAudioCandidate.editNotes,
        riskNote: sidecar.riskNote || selectedAudioCandidate.riskNote,
        templateFamilies: sidecar.templateFamilies || selectedAudioCandidate.templateFamilies,
      });
      if (!result.ok || !result.asset) {
        setAudioCandidateError(result.error || "Free audio import failed.");
        return;
      }
      if (result.asset.role === "sfx") {
        const importedSidecar = result.sidecar || {};
        const importedName = baseNameFromPath(result.asset.path) || result.asset.title || selectedAudioCandidate.title;
        const sourceLicense = result.asset.sourceLicense
          || String(importedSidecar.sourceLicense || importedSidecar.license || importedSidecar.licenseUrl || selectedAudioCandidate.sourceLicense || "");
        const licenseUrl = String(importedSidecar.licenseUrl || selectedAudioCandidate.licenseUrl || "");
        const attribution = String(importedSidecar.attribution || selectedAudioCandidate.attribution || "");
        actions.editScene(selectedSceneIndex, "_sfx_asset_path", result.asset.path);
        actions.editScene(selectedSceneIndex, "_sfx_asset_name", importedName);
        actions.editScene(selectedSceneIndex, "_sfx_asset_mime", audioMimeFromPath(result.asset.path));
        actions.editScene(selectedSceneIndex, "_sfx_asset_title", result.asset.title || String(importedSidecar.title || selectedAudioCandidate.title || importedName));
        actions.editScene(selectedSceneIndex, "_sfx_asset_provider", result.asset.provider || String(importedSidecar.provider || selectedAudioCandidate.provider || ""));
        actions.editScene(selectedSceneIndex, "_sfx_asset_source_url", result.asset.sourceUrl || String(importedSidecar.sourceUrl || selectedAudioCandidate.sourceUrl || ""));
        actions.editScene(selectedSceneIndex, "_sfx_asset_source_license", sourceLicense);
        actions.editScene(selectedSceneIndex, "_sfx_asset_license_url", licenseUrl);
        actions.editScene(selectedSceneIndex, "_sfx_asset_attribution", attribution);
        actions.editScene(selectedSceneIndex, "_sfx_asset_kind", result.asset.kind || String(importedSidecar.kind || selectedAudioCandidate.kind || "sfx"));
        setAudioImportResult(`SFX attached to this scene: ${result.asset.path} / ${result.asset.sidecarPath}`);
      } else {
        const importedSidecar = result.sidecar || {};
        const title = result.asset.title || String(importedSidecar.title || selectedAudioCandidate.title || baseNameFromPath(result.asset.path) || "Pinned BGM");
        const sourceProvider = result.asset.provider || String(importedSidecar.provider || selectedAudioCandidate.provider || "");
        const pinnedAsset: BgmAssetPayload = {
          role: "bgm",
          path: result.asset.path,
          sidecarPath: result.asset.sidecarPath,
          provider: "local-bgm",
          sourceProvider,
          sourceUrl: result.asset.sourceUrl || String(importedSidecar.sourceUrl || selectedAudioCandidate.sourceUrl || ""),
          sourceLicense: result.asset.sourceLicense || String(importedSidecar.sourceLicense || importedSidecar.license || selectedAudioCandidate.sourceLicense || ""),
          licenseUrl: result.asset.licenseUrl || String(importedSidecar.licenseUrl || selectedAudioCandidate.licenseUrl || ""),
          attribution: result.asset.attribution || String(importedSidecar.attribution || selectedAudioCandidate.attribution || ""),
          sourceLabel: title,
          title,
          artist: result.asset.artist || String(importedSidecar.artist || selectedAudioCandidate.artist || ""),
          mood: result.asset.mood || String(importedSidecar.mood || selectedAudioCandidate.mood || recommendedAudioMood || ""),
          kind: result.asset.kind || String(importedSidecar.kind || selectedAudioCandidate.kind || "bgm"),
          candidateId: selectedAudioCandidate.id,
          operatorApproved: true,
          operatorSelected: true,
        };
        actions.setSelectedBgmAsset(pinnedAsset);
        setAudioImportResult(`Project BGM pinned for next render: ${result.asset.path} / ${result.asset.sidecarPath}`);
      }
      setAudioImportFile(null);
      setAudioImportPath("");
      if (audioImportFileRef.current) {
        audioImportFileRef.current.value = "";
      }
    } catch (error) {
      setAudioCandidateError(error instanceof Error ? error.message : String(error));
    } finally {
      setImportingAudioAsset(false);
    }
  };

  const handleImportOwnedVoiceover = async () => {
    if (selectedSceneIndex === null) {
      setVoiceoverImportError("Select a scene first.");
      return;
    }
    const sourcePath = voiceoverImportPath.trim();
    if (!sourcePath && !voiceoverImportFile) {
      setVoiceoverImportError("Owned voiceover file or local path is required.");
      return;
    }
    setImportingVoiceoverAsset(true);
    setVoiceoverImportError(null);
    setVoiceoverImportResult(null);
    try {
      const fileBase64 = voiceoverImportFile ? await readAudioFileBase64(voiceoverImportFile) : undefined;
      const sceneLabel = `scene-${String(scene.scene_num || selectedSceneIndex + 1).padStart(2, "0")}`;
      const result = await importFreeAudioAsset({
        operatorApproved: true,
        sourcePath: voiceoverImportFile ? undefined : sourcePath,
        fileBase64,
        fileName: voiceoverImportFile?.name,
        targetRole: "voiceover",
        operatorOwned: true,
        provider: "upload",
        kind: "voiceover",
        title: `${sceneLabel} owned voiceover`,
        sourceLicense: "operator-owned",
        sourceOrigin: "operator-owned-voiceover",
        speaker: "operator",
      });
      if (!result.ok || !result.asset) {
        setVoiceoverImportError(result.error || "Owned voiceover import failed.");
        return;
      }
      const importedSidecar = result.sidecar || {};
      const importedName = baseNameFromPath(result.asset.path) || result.asset.title || `${sceneLabel}-voiceover.wav`;
      actions.editScene(selectedSceneIndex, "_voiceover_asset_path", result.asset.path);
      actions.editScene(selectedSceneIndex, "_voiceover_asset_name", importedName);
      actions.editScene(selectedSceneIndex, "_voiceover_asset_mime", audioMimeFromPath(result.asset.path));
      actions.editScene(selectedSceneIndex, "_voiceover_asset_title", result.asset.title || String(importedSidecar.title || importedName));
      actions.editScene(selectedSceneIndex, "_voiceover_asset_provider", result.asset.provider || "upload");
      actions.editScene(selectedSceneIndex, "_voiceover_asset_source_origin", String(importedSidecar.sourceOrigin || "operator-owned-voiceover"));
      actions.editScene(selectedSceneIndex, "_voiceover_asset_source_license", result.asset.sourceLicense || String(importedSidecar.sourceLicense || "operator-owned"));
      actions.editScene(selectedSceneIndex, "_voiceover_asset_kind", result.asset.kind || "voiceover");
      setVoiceoverImportResult(`Owned voiceover attached to this scene: ${result.asset.path}`);
      setVoiceoverImportFile(null);
      setVoiceoverImportPath("");
      if (voiceoverImportFileRef.current) {
        voiceoverImportFileRef.current.value = "";
      }
    } catch (error) {
      setVoiceoverImportError(error instanceof Error ? error.message : String(error));
    } finally {
      setImportingVoiceoverAsset(false);
    }
  };

  const handleCopyGrokPrompt = async () => {
    const prompt = scene.grok_prompt || (
      isLocalModelSource(currentSource) ? defaultLocalModelPrompt(scene, currentSource) : defaultGrokPrompt(scene)
    );
    actions.editScene(selectedSceneIndex, "grok_prompt", prompt);
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  const handleCreateGrokHandoff = async () => {
    setCreatingGrokHandoff(true);
    try {
      await actions.createGrokHandoff();
    } finally {
      setCreatingGrokHandoff(false);
    }
  };

  const handleOpenGrok = async (
    target: "worksheet" | "grok" | "both" = "worksheet",
    browserPreference: "default" | "chrome" | "edge" = "default",
  ) => {
    setOpeningGrok(true);
    try {
      await actions.openGrokHandoff(target, browserPreference);
    } finally {
      setOpeningGrok(false);
    }
  };

  const handleOpenExistingChromeGrok = async () => {
    setOpeningGrok(true);
    try {
      await handleCopyGrokPrompt();
      await actions.openGrokHandoff("grok", "chrome");
    } finally {
      setOpeningGrok(false);
    }
  };

  const handleOpenObservedGrokPostAndWatch = async () => {
    setOpeningGrok(true);
    setStartingGrokManualWatch(true);
    try {
      await actions.openGrokHandoff("observed-post", "chrome", grokObservedPostSceneId);
      await actions.startGrokManualDownloadWatch(grokEffectiveDownloadDir, grokObservedPostSceneId);
    } finally {
      setStartingGrokManualWatch(false);
      setOpeningGrok(false);
    }
  };

  const handleOpenObservedGrokAssetManualRunway = async () => {
    setOpeningGrok(true);
    setStartingGrokManualWatch(true);
    try {
      await actions.openGrokHandoff("observed-asset-manual-runway", "chrome", grokObservedPostSceneId);
      if (!isGrokManualWatchPolling) {
        await actions.startGrokManualDownloadWatch(grokEffectiveDownloadDir, grokObservedPostSceneId);
      }
    } finally {
      setStartingGrokManualWatch(false);
      setOpeningGrok(false);
    }
  };

  const loadCurrentGrokCommand = async (): Promise<GrokCompanionCommand | null> => {
    const projectId = grokHandoff?.projectId;
    if (!projectId) {
      setGrokFallbackActionResult("Grok handoff packet is required first.");
      return null;
    }
    const command = await getGrokCompanionCommand(projectId, handoffSceneId);
    if (!command.ok) {
      setGrokFallbackActionResult(command.error || "Grok command is not ready.");
      return null;
    }
    return command;
  };

  const writeGrokFallbackClipboard = async (value: string): Promise<void> => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        return;
      }
    } catch {
      // Use the textarea path below when Clipboard API is blocked by browser policy.
    }
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    textarea.style.top = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(textarea);
    if (!copied) {
      throw new Error("clipboard copy failed");
    }
  };

  const copyGrokFallbackText = async (label: string, value?: string) => {
    if (!value) {
      setGrokFallbackActionResult(`${label}: missing URL`);
      return;
    }
    try {
      await writeGrokFallbackClipboard(value);
      setGrokFallbackActionResult(`${label} copied`);
    } catch {
      setGrokFallbackActionResult(`${label}: ${value}`);
    }
  };

  const handleCopyObservedPostRecoveryConsole = async () => {
    setLoadingGrokFallbackAction("post-recovery-console");
    try {
      await copyGrokFallbackText(
        "Observed Grok post MP4 recovery console",
        grokObservedPostImportPlan?.observedPostDownloadConsoleSnippet,
      );
    } finally {
      setLoadingGrokFallbackAction(null);
    }
  };

  const handleCopyObservedPostRecoveryConsoleAndOpen = async () => {
    setLoadingGrokFallbackAction("post-recovery-copy-open");
    try {
      if (grokObservedPostImportPlan?.postUrl) {
        window.open(grokObservedPostImportPlan.postUrl, "_blank", "noreferrer");
      }
      await copyGrokFallbackText(
        "Observed Grok post MP4 recovery console + post",
        grokObservedPostImportPlan?.observedPostDownloadConsoleSnippet,
      );
    } finally {
      setLoadingGrokFallbackAction(null);
    }
  };

  const handleCopyGrokOriginalRunwayChecklist = async () => {
    setLoadingGrokFallbackAction("original-runway-checklist");
    try {
      await copyGrokFallbackText("Grok original MP4 runway checklist", grokOriginalRunwayChecklist);
    } finally {
      setLoadingGrokFallbackAction(null);
    }
  };

  const handleCopyGrokOriginalExpectedFile = async () => {
    setLoadingGrokFallbackAction("original-runway-filename");
    try {
      await copyGrokFallbackText("Expected Grok MP4 filename", grokOriginalExpectedFile);
    } finally {
      setLoadingGrokFallbackAction(null);
    }
  };

  const handleCopyGrokPrimaryPromptPacket = async () => {
    setLoadingGrokFallbackAction("primary-grok-prompt-packet");
    try {
      await copyGrokFallbackText("Grok-main prompt packet", grokPrimaryPromptPacket);
    } finally {
      setLoadingGrokFallbackAction(null);
    }
  };

  const handleCopyGrokBookmarklet = async (autoGenerate: boolean) => {
    const actionKey = autoGenerate ? "bookmarklet-generate" : "bookmarklet-fill";
    setLoadingGrokFallbackAction(actionKey);
    try {
      const command = await loadCurrentGrokCommand();
      await copyGrokFallbackText(
        autoGenerate ? "Fill+Generate self-contained bookmarklet" : "Fill self-contained bookmarklet",
        autoGenerate
          ? command?.bookmarkletGenerateInlineUrl || command?.bookmarkletGenerateUrl
          : command?.bookmarkletInlineUrl || command?.bookmarkletUrl,
      );
    } finally {
      setLoadingGrokFallbackAction(null);
    }
  };

  const handleCopyGrokConsoleFallback = async (autoGenerate: boolean) => {
    const actionKey = autoGenerate ? "console-generate" : "console-fill";
    setLoadingGrokFallbackAction(actionKey);
    try {
      const command = await loadCurrentGrokCommand();
      const inlineSnippet = autoGenerate
        ? command?.bookmarkletGenerateInlineConsoleSnippet
        : command?.bookmarkletInlineConsoleSnippet;
      const scriptUrl = autoGenerate ? command?.bookmarkletGenerateScriptUrl : command?.bookmarkletScriptUrl;
      const snippet = inlineSnippet || (scriptUrl
        ? `(() => { const s = document.createElement("script"); s.src = ${JSON.stringify(scriptUrl)}; document.documentElement.appendChild(s); })();`
        : "");
      await copyGrokFallbackText(
        autoGenerate ? "Fill+Generate inline console fallback" : "Fill inline console fallback",
        snippet,
      );
    } finally {
      setLoadingGrokFallbackAction(null);
    }
  };

  const handleCopyGrokQueueBookmarklet = async () => {
    setLoadingGrokFallbackAction("queue-bookmarklet");
    try {
      const command = await loadCurrentGrokCommand();
      await copyGrokFallbackText(
        "Queue self-contained bookmarklet",
        command?.bookmarkletQueueInlineUrl || command?.bookmarkletQueueUrl,
      );
    } finally {
      setLoadingGrokFallbackAction(null);
    }
  };

  const handleCopyGrokQueueConsoleFallback = async () => {
    setLoadingGrokFallbackAction("queue-console");
    try {
      const command = await loadCurrentGrokCommand();
      const scriptUrl = command?.bookmarkletQueueScriptUrl;
      const snippet = command?.bookmarkletQueueInlineConsoleSnippet || (scriptUrl
        ? `(() => { const s = document.createElement("script"); s.src = ${JSON.stringify(scriptUrl)}; document.documentElement.appendChild(s); })();`
        : "");
      await copyGrokFallbackText("Queue inline console fallback", snippet);
    } finally {
      setLoadingGrokFallbackAction(null);
    }
  };

  const handleCopyGrokTakeGenerate = async (takeNumber: number, mode: "bookmarklet" | "console") => {
    const actionKey = `take-${takeNumber}-${mode}`;
    setLoadingGrokFallbackAction(actionKey);
    try {
      const command = await loadCurrentGrokCommand();
      const takeCommand = command?.takeCommands?.find((item) => Number(item.takeNumber || 1) === takeNumber);
      const selectedCommand = takeCommand || command;
      const scriptUrl = selectedCommand?.bookmarkletGenerateScriptUrl || selectedCommand?.bookmarkletScriptUrl;
      const fallbackSnippet = scriptUrl
        ? `(() => { const s = document.createElement("script"); s.src = ${JSON.stringify(scriptUrl)}; document.documentElement.appendChild(s); })();`
        : "";
      const value = mode === "console"
        ? selectedCommand?.bookmarkletGenerateInlineConsoleSnippet || fallbackSnippet
        : selectedCommand?.bookmarkletGenerateInlineUrl
          || selectedCommand?.bookmarkletGenerateUrl
          || selectedCommand?.bookmarkletInlineUrl
          || selectedCommand?.bookmarkletUrl;
      await copyGrokFallbackText(
        `Take ${takeNumber} ${mode === "console" ? "inline console" : "self-contained bookmarklet"}`,
        value,
      );
    } finally {
      setLoadingGrokFallbackAction(null);
    }
  };

  const handleOpenGrokPrepGenerateUrl = async () => {
    setLoadingGrokFallbackAction("prep-generate-url");
    try {
      const command = await loadCurrentGrokCommand();
      if (command?.prepGenerateAutostartUrl) {
        try {
          await actions.openGrokHandoff("grok-prep-generate", "chrome", handoffSceneId);
          setGrokFallbackActionResult("Grok prep+generate URL opened in Chrome");
        } catch {
          window.open(command.prepGenerateAutostartUrl, "_blank", "noreferrer");
          setGrokFallbackActionResult("Grok prep+generate URL opened with browser fallback");
        }
      } else {
        setGrokFallbackActionResult("prep+generate URL missing");
      }
    } finally {
      setLoadingGrokFallbackAction(null);
    }
  };

  const handleSyncGrok = async () => {
    setSyncingGrok(true);
    try {
      await actions.syncGrokHandoff();
    } finally {
      setSyncingGrok(false);
    }
  };

  const handleOpenGrokAutomationPlan = async () => {
    setLoadingGrokPlan(true);
    try {
      const plan = await actions.loadGrokAutomationPlan();
      if (plan?.ok && grokHandoff?.automationPlanUrl) {
        window.open(grokHandoff.automationPlanUrl, "_blank", "noreferrer");
      }
    } finally {
      setLoadingGrokPlan(false);
    }
  };

  const handleOpenGrokReviewPacket = () => {
    if (grokReviewPacketUrl) {
      window.open(grokReviewPacketUrl, "_blank", "noreferrer");
    }
  };

  const handleFocusGrokOperator = async () => {
    setFocusingGrokOperator(true);
    try {
      await actions.focusGrokOperatorBrowser();
    } finally {
      setFocusingGrokOperator(false);
    }
  };

  const handleCleanupGrokTabs = async () => {
    setCleaningGrokTabs(true);
    try {
      await actions.cleanupGrokOperatorTabs();
    } finally {
      setCleaningGrokTabs(false);
    }
  };

  const handleImportGrokDownloads = async () => {
    setImportingGrokDownloads(true);
    try {
      await actions.importGrokDownloads(grokEffectiveDownloadDir);
    } finally {
      setImportingGrokDownloads(false);
    }
  };

  const handleWatchGrokDownloads = async () => {
    setWatchingGrokDownloads(true);
    try {
      await actions.watchGrokDownloads(grokEffectiveDownloadDir);
    } finally {
      setWatchingGrokDownloads(false);
    }
  };

  const handleStartGrokManualWatch = async () => {
    setStartingGrokManualWatch(true);
    try {
      await actions.startGrokManualDownloadWatch(grokEffectiveDownloadDir, handoffSceneId);
    } finally {
      setStartingGrokManualWatch(false);
    }
  };

  const handleStartGrokManualWatchAll = async () => {
    setStartingGrokManualWatchAll(true);
    try {
      await actions.startGrokManualDownloadWatchAll(grokEffectiveDownloadDir);
    } finally {
      setStartingGrokManualWatchAll(false);
    }
  };

  const handleRunGrokOperator = async () => {
    setRunningGrokOperator(true);
    try {
      await actions.runGrokOperatorLoop(grokDownloadDir);
    } finally {
      setRunningGrokOperator(false);
    }
  };

  const handleRunGrokBrowserAutomation = async () => {
    setRunningGrokBrowserAutomation(true);
    try {
      const waitSeconds = Math.max(30, Math.min(GROK_OPERATOR_WAIT_MAX_SECONDS, Number(grokAuthWaitSeconds) || GROK_OPERATOR_WAIT_DEFAULT_SECONDS));
      await actions.runGrokBrowserAutomation(selectedSceneIndex, grokDownloadDir, {
        operatorReadyTimeoutSeconds: waitSeconds,
        operatorReadyPollIntervalSeconds: 2,
        authProviderPreference: grokAuthProvider,
      });
    } finally {
      setRunningGrokBrowserAutomation(false);
    }
  };

  const handleStartGrokBackgroundAutomation = async () => {
    setStartingGrokBackgroundAutomation(true);
    try {
      const waitSeconds = Math.max(30, Math.min(GROK_OPERATOR_WAIT_MAX_SECONDS, Number(grokAuthWaitSeconds) || GROK_OPERATOR_WAIT_DEFAULT_SECONDS));
      await actions.startGrokBackgroundAutomation(selectedSceneIndex, grokDownloadDir, {
        operatorReadyTimeoutSeconds: waitSeconds,
        operatorReadyPollIntervalSeconds: 2,
        authProviderPreference: grokAuthProvider,
      });
    } finally {
      setStartingGrokBackgroundAutomation(false);
    }
  };

  const handleStartNextGrokBackgroundAutomation = async () => {
    setStartingNextGrokBackgroundAutomation(true);
    try {
      const waitSeconds = Math.max(30, Math.min(GROK_OPERATOR_WAIT_MAX_SECONDS, Number(grokAuthWaitSeconds) || GROK_OPERATOR_WAIT_DEFAULT_SECONDS));
      await actions.startNextGrokBackgroundAutomation(grokDownloadDir, {
        operatorReadyTimeoutSeconds: waitSeconds,
        operatorReadyPollIntervalSeconds: 2,
        authProviderPreference: grokAuthProvider,
      });
    } finally {
      setStartingNextGrokBackgroundAutomation(false);
    }
  };

  const handleRestartGrokBackgroundAutomationWithIsolatedProfile = async () => {
    setRestartingGrokBackgroundAutomation(true);
    try {
      const waitSeconds = Math.max(30, Math.min(GROK_OPERATOR_WAIT_MAX_SECONDS, Number(grokAuthWaitSeconds) || GROK_OPERATOR_WAIT_DEFAULT_SECONDS));
      await actions.startNextGrokBackgroundAutomation(grokDownloadDir, {
        operatorReadyTimeoutSeconds: waitSeconds,
        operatorReadyPollIntervalSeconds: 2,
        supersedeActiveJobApproved: true,
        remoteDebuggingPort: 9333,
        authProviderPreference: grokAuthProvider,
      });
    } finally {
      setRestartingGrokBackgroundAutomation(false);
    }
  };

  const handleStartGrokBackgroundAutomationWithDefaultChromeAttach = async () => {
    setAttachingDefaultChromeGrok(true);
    try {
      const waitSeconds = Math.max(30, Math.min(GROK_OPERATOR_WAIT_MAX_SECONDS, Number(grokAuthWaitSeconds) || GROK_OPERATOR_WAIT_DEFAULT_SECONDS));
      await actions.startGrokBackgroundAutomation(selectedSceneIndex, grokDownloadDir, {
        operatorReadyTimeoutSeconds: waitSeconds,
        operatorReadyPollIntervalSeconds: 2,
        supersedeActiveJobApproved: true,
        remoteDebuggingPort: 9222,
        authProviderPreference: grokAuthProvider,
        useDefaultChromeProfile: true,
        attachDefaultChromeApproved: true,
        browserProfileDirectory: "Default",
      });
    } finally {
      setAttachingDefaultChromeGrok(false);
    }
  };

  const handleResumeGrokBrowserAutomation = async () => {
    setResumingGrokAutomation(true);
    try {
      const waitSeconds = Math.max(30, Math.min(GROK_OPERATOR_WAIT_MAX_SECONDS, Number(grokAuthWaitSeconds) || GROK_OPERATOR_WAIT_DEFAULT_SECONDS));
      await actions.resumeGrokBrowserAutomation(selectedSceneIndex, {
        operatorReadyTimeoutSeconds: waitSeconds,
        operatorReadyPollIntervalSeconds: 2,
        authProviderPreference: grokAuthProvider,
      });
    } finally {
      setResumingGrokAutomation(false);
    }
  };

  const handleGenerateLocalVideo = async () => {
    setGeneratingLocalVideo(true);
    try {
      await actions.generateLocalSceneVideo(selectedSceneIndex);
    } finally {
      setGeneratingLocalVideo(false);
    }
  };

  const handleImportLocalFolder = async () => {
    setImportingLocalFolder(true);
    try {
      const providerHint = LOCAL_PROVIDER_BY_SOURCE[currentSource];
      await actions.importLocalVideoFolder(localFolderDir, providerHint);
    } finally {
      setImportingLocalFolder(false);
    }
  };

  const handleSaveGrokReview = async (accepted: boolean) => {
    setSavingGrokReview(true);
    try {
      await actions.saveGrokReviewDecision(
        selectedSceneIndex,
        accepted,
        grokReviewOperatorNote.trim(),
        grokReviewChecks,
        currentSource === "grok" ? selectedGrokCandidateFileName : "",
        currentSource === "grok" ? grokCandidateSummary.trim() : "",
        currentSource === "grok" ? grokReviewQualityFields : undefined,
      );
    } finally {
      setSavingGrokReview(false);
    }
  };

  const handleRenderGrok = async () => {
    setRenderingGrok(true);
    try {
      await actions.renderGrokHandoff();
    } finally {
      setRenderingGrok(false);
    }
  };

  const handleRenderGrokPreview = async () => {
    setRenderingGrok(true);
    try {
      await actions.renderGrokHandoffPreview();
    } finally {
      setRenderingGrok(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    const file = files[0];
    if (file) {
      const grokVideoFiles = currentSource === "grok"
        ? files.filter((item) => item.type.startsWith("video/") || item.name.toLowerCase().endsWith(".mp4"))
        : [];
      if (currentSource === "grok" && grokVideoFiles.length > 1) {
        setUploadingGrokMp4(true);
        try {
          await actions.uploadGrokSceneMp4Batch(selectedSceneIndex, grokVideoFiles, grokUploadBatchModeRef.current);
        } finally {
          setUploadingGrokMp4(false);
        }
      } else {
        const source = currentSource === "grok" || isLocalModel ? currentSource : "upload";
        actions.uploadSceneVisual(selectedSceneIndex, file, source);
        if (currentSource === "grok" && (file.type.startsWith("video/") || file.name.toLowerCase().endsWith(".mp4"))) {
          setUploadingGrokMp4(true);
          try {
            await actions.uploadGrokSceneMp4(selectedSceneIndex, file);
          } finally {
            setUploadingGrokMp4(false);
          }
        }
      }
    }
    grokUploadBatchModeRef.current = "auto";
    e.target.value = "";
  };

  return (
    <div className="scene-detail">
      {/* Header */}
      <div className="scene-detail-header">
        <div className="scene-detail-title-group">
          <h3>씬 {scene.scene_num}</h3>
          <span className="route-badge route-local">LOCAL</span>
          <span className="scene-detail-duration">{scene.duration}s</span>
        </div>
        <button className="scene-detail-close" onClick={() => actions.selectScene(null)}>
          <X size={14} />
        </button>
      </div>

      <div className="scene-detail-section">
        <div className="scene-detail-section-title">씬 소스</div>
        <div className="source-grid">
          {SOURCE_OPTIONS.map((src) => {
            const Icon = src.icon;
            return (
            <button
              key={src.key}
              className={`source-card ${currentSource === src.key ? "active" : ""}`}
              onClick={() => handleSourceChange(src.key)}
            >
              <Icon size={14} />
              <span>{src.label}</span>
            </button>
            );
          })}
        </div>
        {sourceGuidance && (
          <div className="source-guidance-card">
            <div className="source-guidance-head">
              <strong>template source plan</strong>
              <span>{sourceGuidance.sourceMix}</span>
            </div>
            <div className="source-guidance-list">
              <span>free: {sourceGuidance.freeAssets}</span>
              <span>proof: {sourceGuidance.proof}</span>
              <span>layout: {sourceGuidance.layout}</span>
              <span>avoid: {sourceGuidance.avoid}</span>
            </div>
          </div>
        )}
        <div className="button-row" style={{ marginTop: 8 }}>
          <button className="chip" onClick={handleCreateAssetPacket} disabled={creatingAssetPacket}>
            {creatingAssetPacket ? <RefreshCw size={12} className="spin" /> : <Search size={12} />}
            {creatingAssetPacket ? "에셋 패킷 생성 중" : "무료 에셋 패킷"}
          </button>
        </div>
        {freeAssetPacket?.ok && (
          <div className="asset-packet-card">
            <div className="asset-packet-head">
              <strong>{freeAssetPacket.templateFamily || templateType}</strong>
              <span>{freeAssetPacket.sourceMix}</span>
            </div>
            {freeAssetPacket.selectedTemplatePlaybook && (
              <div className="asset-packet-block">
                <span className="asset-packet-label">template playbook</span>
                <div className="asset-variant-row">
                  <strong>{freeAssetPacket.selectedTemplatePlaybook.family}</strong>
                  <span>{freeAssetPacket.selectedTemplatePlaybook.pattern}</span>
                  <small>{freeAssetPacket.selectedTemplatePlaybook.layout}</small>
                </div>
                {!!freeAssetPacket.selectedTemplatePlaybook.freeAssetSubstitutes?.length && (
                  <div className="asset-packet-tags">
                    {freeAssetPacket.selectedTemplatePlaybook.freeAssetSubstitutes.slice(0, 4).map((item) => (
                      <span key={item}>{item}</span>
                    ))}
                  </div>
                )}
                {freeAssetPacket.selectedTemplatePlaybook.qualityGate && (
                  <small>{freeAssetPacket.selectedTemplatePlaybook.qualityGate}</small>
                )}
              </div>
            )}
            {(freeAssetPacket.packetPath || freeAssetPacket.worksheetPath) && (
              <div className="asset-packet-block">
                <span className="asset-packet-label">saved packet</span>
                <div className="asset-bgm-status">
                  {freeAssetPacket.packetPath && <span>{freeAssetPacket.packetPath}</span>}
                  {freeAssetPacket.worksheetPath && <span>{freeAssetPacket.worksheetPath}</span>}
                </div>
              </div>
            )}
            <div className="asset-packet-tags">
              {(freeAssetPacket.preferredSourceOrder || []).slice(0, 6).map((source) => (
                <span key={source}>{source}</span>
              ))}
            </div>
            {!!freeAssetPacket.layoutVariants?.length && (
              <div className="asset-packet-block">
                <span className="asset-packet-label">layout variants</span>
                <div className="asset-variant-list">
                  {freeAssetPacket.layoutVariants.slice(0, 2).map((variant) => (
                    <div className="asset-variant-row" key={variant.key}>
                      <strong>{variant.label}</strong>
                      <span>{variant.scenePattern}</span>
                      <small>{variant.captionPlan}</small>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {!!freeAssetPacket.assetProductionRecipes?.length && (
              <div className="asset-packet-block">
                <span className="asset-packet-label">production recipes</span>
                <div className="asset-variant-list">
                  {freeAssetPacket.assetProductionRecipes.slice(0, 3).map((recipe) => (
                    <div className="asset-variant-row" key={recipe.key}>
                      <strong>{recipe.label || recipe.key}</strong>
                      <span>{recipe.goal}</span>
                      <small>{recipe.qualityGate}</small>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {freeAssetPacket.bgmPlan?.localLibrary && (
              <div className="asset-packet-block">
                <span className="asset-packet-label">BGM plan</span>
                <div className="asset-bgm-status">
                  <span>mood: {freeAssetPacket.bgmPlan.recommendedMood || freeAssetPacket.recommendedBgmMood || "auto"}</span>
                  <span>local: {freeAssetPacket.bgmPlan.localLibrary.tracksWithProvenance || 0}/{freeAssetPacket.bgmPlan.localLibrary.totalTracks || 0} provenanced</span>
                  <span>{freeAssetPacket.bgmPlan.localLibrary.status || "unknown"}</span>
                </div>
                {freeAssetPacket.bgmPlan.localLibrary.operatorAction && (
                  <small>{freeAssetPacket.bgmPlan.localLibrary.operatorAction}</small>
                )}
              </div>
            )}
            <div className="asset-packet-block">
              <span className="asset-packet-label">free BGM/SFX candidates</span>
              <div className="button-row">
                <button className="chip" onClick={handleFetchFreeAudioCandidates} disabled={searchingAudioCandidates}>
                  {searchingAudioCandidates ? <RefreshCw size={12} className="spin" /> : <Search size={12} />}
                  {searchingAudioCandidates ? "후보 조회 중" : "후보 조회"}
                </button>
                <span className="chip">mood: {recommendedAudioMood || "auto"}</span>
              </div>
              {audioPlan && (
                <div className="asset-bgm-status">
                  <span>variant: {audioPlan.selectedVariant?.label || scene.layout_variant_label || "template default"}</span>
                  <span>sources: {(audioPlan.sourceRoutes || []).slice(0, 4).join(" / ")}</span>
                  <span>sfx: {audioPlan.sfxPolicy || "minimal"}</span>
                </div>
              )}
              {audioPlan?.bgmRule && <small>{audioPlan.bgmRule}</small>}
              {audioPlan?.operatorAction && <small>{audioPlan.operatorAction}</small>}
              {selectedBgmAsset && (
                <>
                  <div className="asset-bgm-status">
                    <span>project BGM: {selectedBgmAsset.sourceLabel || selectedBgmAsset.title || baseNameFromPath(selectedBgmAsset.path)}</span>
                    <span>{selectedBgmAsset.sourceProvider || "local-bgm"}</span>
                    <span>{selectedBgmAsset.sourceLicense || selectedBgmAsset.licenseUrl || "license metadata pending"}</span>
                  </div>
                  <div className="button-row">
                    <span className="chip">{selectedBgmAsset.mood || recommendedAudioMood || "mood auto"}</span>
                    <button className="chip" onClick={() => actions.setSelectedBgmAsset(null)}>
                      BGM 선택 해제
                    </button>
                  </div>
                  <small>This BGM will be pinned into the render manifest instead of using automatic library rotation.</small>
                </>
              )}
              {scene._sfx_asset_path && (
                <>
                  <div className="asset-bgm-status">
                    <span>scene SFX: {scene._sfx_asset_title || scene._sfx_asset_name || baseNameFromPath(scene._sfx_asset_path)}</span>
                    <span>{scene._sfx_asset_provider || "local-sfx"}</span>
                    <span>{scene._sfx_asset_source_license || "license metadata pending"}</span>
                  </div>
                  <small>SFX will be sent as a scene asset on render and mixed into this scene only.</small>
                </>
              )}
              <>
                <span className="asset-packet-label">owned voiceover</span>
                {scene._voiceover_asset_path && (
                  <div className="asset-bgm-status">
                    <span>{scene._voiceover_asset_title || scene._voiceover_asset_name || baseNameFromPath(scene._voiceover_asset_path)}</span>
                    <span>{scene._voiceover_asset_provider || "upload"}</span>
                    <span>{scene._voiceover_asset_source_license || "operator-owned"}</span>
                  </div>
                )}
                <input
                  ref={voiceoverImportFileRef}
                  type="file"
                  accept="audio/*,.mp3,.wav,.m4a,.ogg,.flac"
                  style={{ display: "none" }}
                  onChange={(event) => {
                    setVoiceoverImportFile(event.target.files?.[0] || null);
                    if (event.target.files?.[0]) {
                      setVoiceoverImportPath("");
                    }
                  }}
                />
                <div className="button-row">
                  <button className="chip" onClick={() => voiceoverImportFileRef.current?.click()}>
                    <Upload size={12} />
                    보이스 파일 선택
                  </button>
                  {voiceoverImportFile && <span className="chip">{voiceoverImportFile.name}</span>}
                </div>
                <input
                  className="editable-input"
                  value={voiceoverImportPath}
                  onChange={(event) => {
                    setVoiceoverImportPath(event.target.value);
                    if (event.target.value.trim()) {
                      setVoiceoverImportFile(null);
                      if (voiceoverImportFileRef.current) {
                        voiceoverImportFileRef.current.value = "";
                      }
                    }
                  }}
                  placeholder="또는 직접 녹음한 오디오 경로"
                />
                <div className="button-row">
                  <button className="chip" onClick={handleImportOwnedVoiceover} disabled={importingVoiceoverAsset}>
                    {importingVoiceoverAsset ? <RefreshCw size={12} className="spin" /> : <Upload size={12} />}
                    {importingVoiceoverAsset ? "import 중" : "owned voiceover 붙이기"}
                  </button>
                  <span className="chip">voiceover</span>
                </div>
                {voiceoverImportError && <small style={{ color: "var(--error)" }}>{voiceoverImportError}</small>}
                {voiceoverImportResult && <small>{voiceoverImportResult}</small>}
              </>
              {!!audioCandidates.length && (
                <div className="asset-variant-list">
                  {audioCandidates.slice(0, 6).map((candidate) => (
                    <div className="asset-variant-row" key={candidate.id}>
                      <strong>{candidate.title}</strong>
                      <span>{candidate.provider} · {candidate.kind} · {candidate.matchedMood || candidate.mood || "mood n/a"} · {candidate.matchReason || "exact"} · risk {candidate.riskLevel || "n/a"}</span>
                      <small>{candidate.sourceLicense || candidate.licenseUrl || candidate.riskNote || "verify source license before import"}</small>
                      <button className="chip" onClick={() => setSelectedAudioCandidateId(candidate.id)}>
                        {selectedAudioCandidate?.id === candidate.id ? "선택됨" : "선택"}
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {selectedAudioCandidate && (
                <>
                  <div className="asset-packet-links">
                    <a href={selectedAudioCandidate.sourceUrl} target="_blank" rel="noreferrer">
                      {selectedAudioCandidate.provider} source
                    </a>
                    <button className="chip" onClick={handleCopyAudioSource}>
                      <Copy size={12} />
                      source 복사
                    </button>
                  </div>
                  <input
                    ref={audioImportFileRef}
                    type="file"
                    accept="audio/*,.mp3,.wav,.m4a,.ogg,.flac"
                    style={{ display: "none" }}
                    onChange={(event) => {
                      setAudioImportFile(event.target.files?.[0] || null);
                      if (event.target.files?.[0]) {
                        setAudioImportPath("");
                      }
                    }}
                  />
                  <div className="button-row">
                    <button className="chip" onClick={() => audioImportFileRef.current?.click()}>
                      <Upload size={12} />
                      오디오 파일 선택
                    </button>
                    {audioImportFile && <span className="chip">{audioImportFile.name}</span>}
                  </div>
                  <input
                    className="editable-input"
                    value={audioImportPath}
                    onChange={(event) => {
                      setAudioImportPath(event.target.value);
                      if (event.target.value.trim()) {
                        setAudioImportFile(null);
                        if (audioImportFileRef.current) {
                          audioImportFileRef.current.value = "";
                        }
                      }
                    }}
                    placeholder="또는 다운로드한 로컬 오디오 경로"
                  />
                  <div className="button-row">
                    <button className="chip" onClick={handleImportFreeAudioCandidate} disabled={importingAudioAsset}>
                      {importingAudioAsset ? <RefreshCw size={12} className="spin" /> : <Upload size={12} />}
                      {importingAudioAsset ? "import 중" : "선택 후보 import"}
                    </button>
                    <span className="chip">{selectedAudioCandidate.importPayloadTemplate?.targetRole || "bgm"}</span>
                  </div>
                </>
              )}
              {audioCandidateError && <small style={{ color: "var(--error)" }}>{audioCandidateError}</small>}
              {audioImportResult && <small>{audioImportResult}</small>}
            </div>
            {assetScenePlan && (
              <>
                <div className="asset-packet-block">
                  <span className="asset-packet-label">scene queries</span>
                  <div className="asset-packet-list">
                    {assetScenePlan.queries.slice(0, 3).map((query) => <span key={query}>{query}</span>)}
                  </div>
                </div>
                <div className="asset-packet-links">
                  {assetScenePlan.candidateSearches.slice(0, 6).map((item, index) => (
                    item.searchUrl ? (
                      <a key={`${item.provider}-${index}`} href={item.searchUrl} target="_blank" rel="noreferrer">
                        {item.label || item.provider}
                      </a>
                    ) : (
                      <span key={`${item.provider}-${index}`}>{item.label || item.provider}</span>
                    )
                  ))}
                </div>
                {assetScenePlan.repeatGuard?.rule && (
                  <small>{assetScenePlan.repeatGuard.rule}</small>
                )}
                {!!assetScenePlan.layoutVariants?.length && (
                  <div className="asset-packet-block">
                    <span className="asset-packet-label">scene layout variants</span>
                    <div className="asset-variant-list">
                      {assetScenePlan.layoutVariants.slice(0, 3).map((variant) => (
                        <div className="asset-variant-row" key={variant.key}>
                          <strong>{variant.label || variant.key}</strong>
                          <span>{variant.scenePattern}</span>
                          <small>{variant.captionPlan}</small>
                          <button className="chip" onClick={() => handleApplyLayoutVariant(variant)}>
                            {scene.layout_variant_key === variant.key ? "적용됨" : "적용"}
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
            {!!freeAssetPacket.assetAcquisitionMethods?.length && (
              <div className="asset-packet-block">
                <span className="asset-packet-label">asset acquisition</span>
                <div className="asset-method-grid">
                  {freeAssetPacket.assetAcquisitionMethods.slice(0, 4).map((method) => (
                    <span key={method.method} title={method.freePath || method.role}>{method.method}</span>
                  ))}
                </div>
              </div>
            )}
            {!!freeAssetPacket.audioSources?.length && (
              <div className="asset-packet-links">
                {freeAssetPacket.audioSources.slice(0, 3).map((item) => (
                  <a key={item.provider} href={item.searchUrl || item.manualUrl || item.officialUrl} target="_blank" rel="noreferrer">
                    {item.label || item.provider}
                  </a>
                ))}
              </div>
            )}
            {!!freeAssetPacket.evidenceSources?.length && (
              <div className="asset-packet-block">
                <span className="asset-packet-label">official references</span>
                <div className="asset-packet-links">
                  {freeAssetPacket.evidenceSources.slice(0, 6).map((item) => (
                    <a key={item.key} href={item.url} target="_blank" rel="noreferrer" title={item.operatorUse || item.sourceType}>
                      {item.label}
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {(videoPreview || imagePreview) && (
        <div className="scene-visual-preview">
          {videoPreview ? (
            <video
              src={videoPreview}
              controls
              muted
              playsInline
            />
          ) : (
          <img
            src={imagePreview!}
            alt={scene._upload_preview ? "업로드 이미지" : "생성된 이미지"}
          />
          )}
          <span className="scene-preview-badge">{currentSource}</span>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,video/*"
        multiple={currentSource === "grok"}
        style={{ display: "none" }}
        onChange={handleFileUpload}
      />

      {(currentSource === "upload" || currentSource === "grok" || isLocalModel) && (
        <div className="button-row scene-detail-section">
          <button
            className="chip"
            onClick={() => {
              grokUploadBatchModeRef.current = currentSource === "grok" ? "current-scene-candidates" : "auto";
              fileInputRef.current?.click();
            }}
            disabled={uploadingGrokMp4}
          >
            {uploadingGrokMp4 ? <RefreshCw size={12} className="spin" /> : <Upload size={12} />}
            {currentSource === "grok" ? "Grok MP4 반입" : "MP4/이미지 선택"}
          </button>
          {scene._upload_name && <span className="inline-file-name">{scene._upload_name}</span>}
          {currentSource === "grok" && (
            <span className="inline-file-name">현재 씬 후보 MP4 여러 개를 한 번에 반입합니다. 전체 씬 묶음은 Grok-main production rail의 일괄 반입을 사용하세요.</span>
          )}
        </div>
      )}

      {(currentSource === "grok" || isLocalModel) && (
        <div className="scene-detail-section">
          <div className="scene-detail-section-title">
            {currentSource === "grok" ? "Grok prompt" : `${localModelLabel(currentSource)} handoff prompt`}
          </div>
          <textarea
            className="editable-input"
            value={scene.grok_prompt || (
              isLocalModelSource(currentSource) ? defaultLocalModelPrompt(scene, currentSource) : defaultGrokPrompt(scene)
            )}
            onChange={(e) => actions.editScene(selectedSceneIndex, "grok_prompt", e.target.value)}
            rows={3}
          />
          <div className="button-row" style={{ marginTop: 8 }}>
            <button className="chip" onClick={handleCopyGrokPrompt}>
              <Copy size={12} /> {copied ? "복사됨" : "복사"}
            </button>
            <button className="chip" onClick={() => fileInputRef.current?.click()}>
              <Upload size={12} /> {currentSource === "grok" ? "Grok" : localModelLabel(currentSource)} MP4 업로드
            </button>
          </div>
          {isLocalModel && (
            <div className="local-video-handoff-box">
              <div className={`adapter-readiness ${adapterReadinessClass(localAdapterStatus)}`}>
                <div className="adapter-readiness-head">
                  <span>{localAdapterStatus?.label || localModelLabel(currentSource)}</span>
                  <strong>{adapterReadinessLabel(localAdapterStatus)}</strong>
                </div>
                <small>{localAdapterStatus?.detail || `${localAdapterEnvPrefix}_MODE not reported by bridge health`}</small>
                {localAdapterStatus?.commandPreview && <code>{localAdapterStatus.commandPreview}</code>}
                {localAdapterEnvPrefix && !localAdapterStatus?.ready && (
                  <small>{`${localAdapterEnvPrefix}_MODE=command + ${localAdapterEnvPrefix}_COMMAND required`}</small>
                )}
              </div>
              <textarea
                className="editable-input"
                value={scene.local_command_template_json || ""}
                onChange={(e) => actions.editScene(selectedSceneIndex, "local_command_template_json", e.target.value)}
                rows={3}
                placeholder='Optional one-time command JSON, e.g. ["python","scripts/run_wan.py","--prompt-path","{prompt_path}","--output-path","{output_path}"]'
              />
              <small>이 씬에서만 쓰는 승인형 command override입니다. .env를 수정하지 않고 JSON string array만 실행합니다.</small>
              <div className="button-row">
                <button className="chip" onClick={handleGenerateLocalVideo} disabled={generatingLocalVideo}>
                  {generatingLocalVideo ? <RefreshCw size={12} className="spin" /> : <WandSparkles size={12} />}
                  {generatingLocalVideo ? "생성 중" : "승인 로컬 생성"}
                </button>
              </div>
              <div className="button-row">
                <input
                  className="editable-input"
                  value={localFolderDir}
                  onChange={(e) => setLocalFolderDir(e.target.value)}
                  placeholder="C:\\path\\to\\wan-outputs"
                />
                <button className="chip" onClick={handleImportLocalFolder} disabled={importingLocalFolder || !localFolderDir.trim()}>
                  {importingLocalFolder ? <RefreshCw size={12} className="spin" /> : <Upload size={12} />}
                  {importingLocalFolder ? "가져오는 중" : "폴더 MP4 가져오기"}
                </button>
              </div>
              {(scene.local_generation_status || scene.local_generation_detail || scene.local_generation_request_path) && (
                <div className="grok-handoff-meta">
                  {scene.local_generation_status && <span>status: {scene.local_generation_status}</span>}
                  {scene.local_generation_detail && <span>detail: {scene.local_generation_detail}</span>}
                  {scene.local_generation_request_path && <span>request: {scene.local_generation_request_path}</span>}
                  {scene.local_generation_prompt_path && <span>prompt: {scene.local_generation_prompt_path}</span>}
                  {scene.local_generation_log_path && <span>log: {scene.local_generation_log_path}</span>}
                  {scene.local_generation_command_preview && <span>command: {scene.local_generation_command_preview}</span>}
                </div>
              )}
            </div>
          )}
          {currentSource === "grok" && (
            <div className="grok-handoff-box">
              <div className={`automation-status ${automationStatusClass(grokAutomationStatus?.status)}`}>
                <div className="automation-status-head">
                  <span>Grok app/web MP4 handoff</span>
                  <strong>{grokManualPrimaryPath?.mode === "manual-grok-app-web-primary" ? "primary" : automationStatusLabel(grokAutomationStatus?.status)}</strong>
                </div>
                <small>{grokAutomationStatus?.detail || "prompt -> Grok app/web MP4 -> import -> review -> render"}</small>
                <div className="grok-handoff-meta" style={{ marginTop: 8 }}>
                  <span>mode: {grokManualPrimaryPath?.mode || "operator-approved app/web handoff"}</span>
                  <span>browser rail: {grokBrowserControlRail?.mode || grokManualPrimaryPath?.browserControlRail || "existing signed-in Chrome control"}</span>
                  <span>primary source: {grokManualPrimaryPath?.primarySource || "Grok MP4"}</span>
                  <span>paid API: disabled</span>
                  <span>browser automation: {grokManualPrimaryPath?.browserAutomationRole || "secondary"}</span>
                  <span>download: {grokBrowserControlRail?.downloadAuthority || grokManualPrimaryPath?.downloadAuthority || "operator-owned local MP4"}</span>
                  <span>operator owns login/captcha/payment/manual upload choice</span>
                </div>
                {grokManualPrimaryPath?.paidApiPolicy && <small>{grokManualPrimaryPath.paidApiPolicy}</small>}
                {grokAutomationStatus?.targetUrl && <small>target: {grokAutomationStatus.targetTitle || grokAutomationStatus.targetUrl}</small>}
                {grokAutomationStatus?.operatorAuthStageLabel && (
                  <small>auth stage: {grokAutomationStatus.operatorAuthStageLabel}</small>
                )}
                {grokPrimaryNextAction && <small>next: {grokPrimaryNextAction}</small>}
                {!grokPrimaryNextAction && grokAutomationStatus?.operatorNextAction && (
                  <small>automation: {grokAutomationStatus.operatorNextAction}</small>
                )}
                {!grokPrimaryNextAction && !grokAutomationStatus?.operatorNextAction && grokAutomationStatus?.manualDownloadInstruction && (
                  <small>fallback: {grokAutomationStatus.manualDownloadInstruction}</small>
                )}
                {typeof grokAutomationStatus?.readyScenes === "number" && typeof grokAutomationStatus.totalScenes === "number" && (
                  <small>ready: {grokAutomationStatus.readyScenes}/{grokAutomationStatus.totalScenes}</small>
                )}
                {grokHandoff?.automationReplay?.updatedAt && (
                  <small>
                    replay: {grokHandoff.automationReplay.sceneId || handoffSceneId}
                    {grokHandoff.automationReplay.watchDownloadsApproved ? " / generate+operator-watch" : " / browser action"}
                    {" / "}{grokHandoff.automationReplay.updatedAt}
                  </small>
                )}
                {grokAutomationJob?.jobId && (
                  <small>
                    background: {grokAutomationJob.status || "queued"} / {grokAutomationJob.sceneId || handoffSceneId}
                    {grokAutomationJob.updatedAt ? ` / ${grokAutomationJob.updatedAt}` : ""}
                  </small>
                )}
                {grokAutomationJob?.jobId && (
                  <small>
                    worker: {grokAutomationJob.activeThread ? "active" : "not active"}
                    {grokAutomationJob.restartAvailable ? " / restart available" : ""}
                    {grokJobElapsedSeconds !== null ? ` / elapsed ${grokJobElapsedSeconds}s` : ""}
                    {grokJobRemainingSeconds !== null ? ` / auth wait ${grokJobRemainingSeconds}s left` : ""}
                  </small>
                )}
                {isGrokBackgroundPolling && <small>dashboard polling: on / MP4 import will sync automatically</small>}
                {grokAutomationJob?.detail && <small>job: {grokAutomationJob.detail}</small>}
                {grokManualDownloadWatchJob?.jobId && (
                  <small>
                    manual watch: {grokManualDownloadWatchJob.status || "queued"} / {grokManualDownloadWatchJob.sceneId || handoffSceneId}
                    {grokManualDownloadWatchJob.importedCount ? ` / imported ${grokManualDownloadWatchJob.importedCount}` : ""}
                    {grokManualDownloadWatchJob.updatedAt ? ` / ${grokManualDownloadWatchJob.updatedAt}` : ""}
                  </small>
                )}
                {grokManualDownloadWatchJob?.jobId && (
                  <small>
                    watch worker: {grokManualDownloadWatchJob.activeThread ? "active" : "not active"}
                    {grokManualWatchRemainingSeconds !== null ? ` / ${grokManualWatchRemainingSeconds}s left` : ""}
                  </small>
                )}
                {isGrokManualWatchPolling && <small>manual Grok watch polling: on / operator-saved MP4 will import automatically</small>}
                {grokManualDownloadWatchJob?.detail && <small>manual watch detail: {grokManualDownloadWatchJob.detail}</small>}
                {grokOperatorReadyWait && (
                  <small>
                    auth wait: {grokOperatorReadyWait.timedOut ? "timeout" : grokOperatorReadyWait.ready ? "ready" : "waiting"}
                    {typeof grokOperatorReadyWait.elapsedSeconds === "number" ? ` / ${grokOperatorReadyWait.elapsedSeconds}s` : ""}
                    {typeof grokOperatorReadyWait.attempts === "number" ? ` / ${grokOperatorReadyWait.attempts} checks` : ""}
                  </small>
                )}
              </div>
              <div className="grok-production-rail">
                <div className="grok-production-rail-head">
                  <div>
                    <span>Grok-main production rail</span>
                    <strong>{grokMainReady ? "ready to render" : "needs Grok MP4 takes"}</strong>
                  </div>
                  <span className={`grok-production-mode ${grokRailNeedsManualHandoff ? "manual" : "fallback"}`}>
                    {grokBrowserControlRail?.mode ? "browser-control primary" : "manual app/web handoff"}
                  </span>
                </div>
                <div className={`grok-primary-action-card ${grokPrimaryActionClass}`}>
                  <div className="grok-primary-action-head">
                    <div>
                      <span>Next Grok-main action</span>
                      <strong>{grokPrimaryActionTitle}</strong>
                    </div>
                    <span>
                      {nativeGrokDownloadFallbackBlocked
                        ? "operator download only"
                        : isGrokManualWatchPolling
                        ? "watcher armed"
                        : grokHasCurrentMp4 ? "imported, review" : "generate native MP4"}
                    </span>
                  </div>
                  <div className="grok-primary-action-grid">
                    <span>scene: {grokOriginalExpectedScene}</span>
                    <span>target: {grokOriginalExpectedFile}</span>
                    <span>take: {grokPrimaryTakeNumber} / {grokPrimaryTakeLabel}</span>
                    <span>watch fallback: disabled for native prompt safety</span>
                    <span>blocker: {grokPrimaryBlocker}</span>
                    <span>source: browser-control generation plus operator-owned manual download/upload</span>
                  </div>
                  <small>
                    Grok 생성은 기존 로그인 Chrome 직접 제어를 기본으로 봅니다. 최종 소스는 cache/currentSrc proof가 아니라 사용자가 저장/다운로드 후 반입했거나 명시적으로 업로드한 Grok MP4여야 합니다.
                  </small>
                  <div className="grok-primary-action-buttons">
                    <button
                      className="chip primary"
                      onClick={handleCopyGrokPrimaryPromptPacket}
                      disabled={!grokHasPacket || loadingGrokFallbackAction === "primary-grok-prompt-packet"}
                      title="현재 scene의 Grok prompt, reject rule, 저장 대상 파일명을 한 번에 복사합니다."
                    >
                      {loadingGrokFallbackAction === "primary-grok-prompt-packet"
                        ? <RefreshCw size={12} className="spin" />
                        : <Copy size={12} />}
                      Prompt packet
                    </button>
                    <button
                      className="chip"
                      onClick={() => window.open(grokProductionQueueUrl, "_blank", "noreferrer")}
                      disabled={!grokProductionQueueUrl}
                      title="전체 scene별 2-take Grok 생성 큐를 엽니다."
                    >
                      <Clapperboard size={12} />
                      Production queue
                    </button>
                    <button
                      className="chip"
                      onClick={() => handleOpenGrok("grok", "chrome")}
                      disabled={!grokHasPacket || openingGrok}
                      title="기존 로그인 Chrome에서 Grok을 열어 app/web 생성 흐름을 이어갑니다."
                    >
                      {openingGrok ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                      Open Grok
                    </button>
                    <button
                      className="chip"
                      onClick={handleStartGrokManualWatchAll}
                      disabled={nativeGrokDownloadFallbackBlocked || !grokHasPacket || startingGrokManualWatchAll || isGrokManualWatchPolling || renderingGrok || !grokEffectiveDownloadDir}
                      title={nativeGrokDownloadFallbackTitle}
                    >
                      {startingGrokManualWatchAll || isGrokManualWatchPolling
                        ? <RefreshCw size={12} className="spin" />
                        : <Play size={12} />}
                      Watch blocked
                    </button>
                    <button
                      className="chip"
                      onClick={handleImportGrokDownloads}
                      disabled={!grokHasPacket || importingGrokDownloads || !grokEffectiveDownloadDir}
                      title="Operator-owned local MP4 files only. This does not press Grok Download/Save/Export."
                    >
                      {importingGrokDownloads ? <RefreshCw size={12} className="spin" /> : <Upload size={12} />}
                      Import local MP4s
                    </button>
                    <button
                      className="chip"
                      onClick={handleOpenGrokReviewPacket}
                      disabled={!grokReviewPacketUrl || !grokHasCurrentMp4}
                      title="반입된 Grok MP4 후보를 provenance, motion, hook, layout 기준으로 검수합니다."
                    >
                      <Captions size={12} />
                      Review take
                    </button>
                  </div>
                </div>
                {grokMainPathStatus && (
                  <div className={`grok-quality-gate ${grokMainPathStatusClass}`}>
                    <div className="grok-quality-gate-head">
                      <span>Grok-main source diagnosis</span>
                      <strong>{grokMainPathStatus.status === "ready" ? "Grok MP4 ready" : "첫 Grok MP4 확보 필요"}</strong>
                    </div>
                    <div className="grok-quality-gate-grid">
                      <span>primary: {grokMainPathStatus.primaryPath || "signed-in Grok app/web MP4"}</span>
                      <span>paid API: {grokMainPathStatus.usesPaidApi ? "used" : "not used"}</span>
                      <span>scene: {grokMainPathStatus.nextSceneId || grokManualCurrentScene?.sceneId || "review"}</span>
                      <span>file: {grokMainPathStatus.nextExpectedFileName || grokManualCurrentScene?.expectedFileName || "candidate MP4"}</span>
                      <span>ready: {grokMainPathStatus.readyScenes ?? grokHandoff?.readyScenes ?? 0}/{grokMainPathStatus.totalScenes ?? grokHandoff?.totalScenes ?? "?"}</span>
                      <span>accepted: {(grokMainPathStatus.acceptedSceneIds || []).length}/{grokMainPathStatus.requiredAcceptedScenes || "?"}</span>
                      <span>CDP: {grokMainPathStatus.cdpPrimaryRecommended ? "primary" : "secondary only"}</span>
                      {grokMainSourceDiagnosis && (
                        <span>Grok model: {grokMainSourceDiagnosis.modelBlocked ? "blocked" : "available"}</span>
                      )}
                      {grokMainSourceDiagnosis && (
                        <span>generation: {grokMainSourceDiagnosis.generationObserved ? "observed" : "not observed"}</span>
                      )}
                      {grokMainSourceDiagnosis?.currentBlocker && (
                        <span>current blocker: {grokMainSourceDiagnosis.currentBlocker}</span>
                      )}
                      {grokMainSourceDiagnosis?.recommendedPrimaryPath && (
                        <span>primary path: {grokMainSourceDiagnosis.recommendedPrimaryPath}</span>
                      )}
                      {grokAssetAcquisition?.state && <span>acquisition: {grokAssetAcquisition.state}</span>}
                      {grokAssetAcquisition?.blockerScope && <span>blocker scope: {grokAssetAcquisition.blockerScope}</span>}
                      {grokAssetAcquisition?.primaryBlocker && <span>asset blocker: {grokAssetAcquisition.primaryBlocker}</span>}
                      {grokOriginalExportPlan?.currentBlocker && <span>original export blocker: {grokOriginalExportPlan.currentBlocker}</span>}
                      {grokAssetAcquisition?.downloadAuthority && <span>download authority: {grokAssetAcquisition.downloadAuthority}</span>}
                      {grokAssetAcquisition && (
                        <span>
                          generated/imported: {grokAssetAcquisition.clipGenerated ? "yes" : "no"}
                          {" / "}{grokAssetAcquisition.localMp4Imported ? "local MP4 ready" : "local MP4 missing"}
                        </span>
                      )}
                      {grokAssetAcquisition && (
                        <span>
                          source quality: {grokAssetAcquisition.publishReadyLocalMp4
                            ? "publish-ready source"
                            : grokAssetAcquisition.qualityBlocked
                              ? "replacement required"
                              : "not proven"}
                        </span>
                      )}
                      {grokAssetAcquisition?.bestLocalCandidate?.fileName && (
                        <span>
                          best local: {grokAssetAcquisition.bestLocalCandidate.fileName}
                          {grokAssetAcquisition.bestLocalCandidate.width && grokAssetAcquisition.bestLocalCandidate.height
                            ? ` / ${grokAssetAcquisition.bestLocalCandidate.width}x${grokAssetAcquisition.bestLocalCandidate.height}`
                            : ""}
                        </span>
                      )}
                      {grokAssetAcquisition && <span>watch fallback: disabled for native prompt safety</span>}
                    </div>
                    {grokMainPathStatus.summary && <small>{grokMainPathStatus.summary}</small>}
                    {grokOriginalExportPlan?.summary && <small>Grok-main export: {grokOriginalExportPlan.summary}</small>}
                    {grokCandidateCurationPlan?.recommendation && <small>candidate curation: {grokCandidateCurationPlan.recommendation}</small>}
                    {grokMainPathStatus.primaryNextAction && <small>next: {grokMainPathStatus.primaryNextAction}</small>}
                    {grokAssetAcquisition && (
                      <div className="source-guidance-card compact">
                        <div className="source-guidance-head">
                          <strong>Grok MP4 acquisition</strong>
                          <span>
                            {grokAssetAcquisition.clipGenerated
                              ? grokAssetAcquisition.qualityBlocked
                                ? "Grok cache/import exists; original-quality replacement is the gate"
                                : "Grok clip exists; local MP4 import is the gate"
                              : "Generate a Grok clip before render"}
                          </span>
                        </div>
                        <div className="source-guidance-list">
                          {grokAssetAcquisition.sourceQualityFloor && (
                            <span>quality floor: {grokAssetAcquisition.sourceQualityFloor}</span>
                          )}
                          {(grokAssetAcquisition.qualityBlockers || []).slice(0, 4).map((item) => (
                            <span key={item}>quality blocker: {item}</span>
                          ))}
                          {grokObservedPostImportPlan?.directAssetFetch?.serverFetchSupported === false && (
                            <span>
                              fetch: server/direct URL download is not supported
                              {grokObservedPostImportPlan.directAssetFetch.expectedFailure
                                ? ` (${grokObservedPostImportPlan.directAssetFetch.expectedFailure})`
                                : ""}
                            </span>
                          )}
                          {(grokAssetAcquisition.approvedImportPaths || []).slice(0, 3).map((item) => (
                            <span key={item}>import: {item}</span>
                          ))}
                          {(grokAssetAcquisition.operatorActionPriority || []).slice(0, 4).map((item) => (
                            <span key={item}>do: {item}</span>
                          ))}
                          {(grokAssetAcquisition.doNotDo || []).slice(0, 3).map((item) => (
                            <span key={item}>avoid: {item}</span>
                          ))}
                          {(grokAssetAcquisition.qualityContract || []).slice(0, 2).map((item) => (
                            <span key={item}>contract: {item}</span>
                          ))}
                        </div>
                      </div>
                    )}
                    {grokCandidateCurationPlan && (
                      <div className="source-guidance-card compact">
                        <div className="source-guidance-head">
                          <strong>Grok take curation</strong>
                          <span>
                            {grokCandidateCurationPlan.publishableCandidateCount || 0}/
                            {grokCandidateCurationPlan.candidateCount || 0} publishable candidates
                          </span>
                        </div>
                        <div className="source-guidance-list">
                          <span>scene: {grokCandidateCurationPlan.targetSceneId || handoffSceneId}</span>
                          <span>minimum: {grokCandidateCurationPlan.minimumCandidates || 2} native Grok MP4 takes</span>
                          {grokCandidateCurationPlan.reviewReadiness && <span>review: {grokCandidateCurationPlan.reviewReadiness}</span>}
                          {grokCandidateCurationPlan.selectionRule && <span>rule: {grokCandidateCurationPlan.selectionRule}</span>}
                          {(grokCandidateCurationPlan.candidates || []).slice(0, 4).map((candidate, index) => (
                            <span key={`${candidate.fileName || "candidate"}-${index}`}>
                              {index + 1}. {candidate.fileName || "candidate"}
                              {candidate.width && candidate.height ? ` / ${candidate.width}x${candidate.height}` : ""}
                              {typeof candidate.score === "number" ? ` / score ${candidate.score}` : ""}
                              {" / "}{candidate.sourceAcceptable ? "native source" : "source not accepted"}
                              {" / "}{candidate.technicalOk ? "technical ok" : "technical blocked"}
                              {" / "}{candidate.motionOk ? "motion ok" : "motion weak"}
                              {candidate.rejectReasons?.length ? ` / ${candidate.rejectReasons[0]}` : ""}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {grokCodexChromeObservation?.status && (
                      <div className="source-guidance-card compact">
                        <div className="source-guidance-list">
                          <span>
                            Codex Chrome observed: {grokCodexChromeObservation.status}
                            {grokCodexChromeObservation.exportStatus ? ` / ${grokCodexChromeObservation.exportStatus}` : ""}
                          </span>
                          <span>
                            observed scene: {grokCodexChromeObservation.sceneId || grokMainPathStatus.nextSceneId || "current"}
                            {" -> "}{grokCodexChromeObservation.expectedFileName || grokMainPathStatus.nextExpectedFileName || "Grok MP4"}
                          </span>
                          {typeof grokCodexChromeObservation.durationSeconds === "number" && grokCodexChromeObservation.durationSeconds > 0 && (
                            <span>
                              media: {grokCodexChromeObservation.durationSeconds.toFixed(1)}s
                              {grokCodexChromeObservation.renderedWidth && grokCodexChromeObservation.renderedHeight
                                ? ` / ${grokCodexChromeObservation.renderedWidth}x${grokCodexChromeObservation.renderedHeight}`
                                : ""}
                            </span>
                          )}
                          {grokCodexChromeObservation.postUrl && (
                            <span>
                              post: <a href={grokCodexChromeObservation.postUrl} target="_blank" rel="noreferrer">{grokCodexChromeObservation.postUrl}</a>
                            </span>
                          )}
                          {grokObservedPostImportPlan?.mode && (
                            <span>
                              import runway: {grokObservedPostImportPlan.mode} / {grokObservedPostExpectedFile}
                            </span>
                          )}
                          {grokObservedPostImportPlan?.observedAssetManualRunwayUrl && (
                            <span>
                              manual runway: operator-owned local upload {"->"} {grokObservedPostExpectedFile}
                            </span>
                          )}
                          {grokObservedAssetUrl && (
                            <span>
                              asset tab: blocked for Codex automation; use post direct-import or local upload
                            </span>
                          )}
                          {grokObservedPostImportPlan?.qualityNote && <span>quality: {grokObservedPostImportPlan.qualityNote}</span>}
                          {grokCodexChromeObservation.exportBlocker && <span>export blocker: {grokCodexChromeObservation.exportBlocker}</span>}
                          {grokCodexChromeObservation.operatorNextAction && <span>next: {grokCodexChromeObservation.operatorNextAction}</span>}
                        </div>
                        {grokObservedPostImportPlan?.available && (
                          <div className="grok-production-actions">
                            <button
                              className="chip"
                              onClick={handleOpenObservedGrokPostAndWatch}
                              disabled={nativeGrokDownloadFallbackBlocked || !grokObservedPostReady}
                              title={nativeGrokDownloadFallbackTitle}
                            >
                              {startingGrokManualWatch || isGrokManualWatchPolling || openingGrok
                                ? <RefreshCw size={12} className="spin" />
                                : <Play size={12} />}
                              관측 post 감시 차단
                            </button>
                            {grokObservedPostImportPlan?.observedPostDownloadConsoleSnippet && (
                              <>
                                <button
                                  className="chip"
                                  onClick={handleCopyObservedPostRecoveryConsole}
                                  disabled={!grokObservedPostRecoveryReady}
                                title="Debug fallback only: 로그인된 Grok post 탭 DevTools console에서 visible video 후보를 회수합니다. Production success에는 operator-owned local MP4 import가 필요합니다."
                                >
                                  {loadingGrokFallbackAction === "post-recovery-console"
                                    ? <RefreshCw size={12} className="spin" />
                                    : <Copy size={12} />}
                                  Post 회수 console
                                </button>
                                <button
                                  className="chip"
                                  onClick={handleCopyObservedPostRecoveryConsoleAndOpen}
                                  disabled={!grokObservedPostRecoveryReady || !grokObservedPostImportPlan?.postUrl}
                                  title="Observed Grok post를 열고 같은 클릭에서 direct-import console snippet을 복사합니다. Chrome Download 승인창을 누르지 않고 Grok post console에 붙여넣는 경로입니다."
                                >
                                  {loadingGrokFallbackAction === "post-recovery-copy-open"
                                    ? <RefreshCw size={12} className="spin" />
                                    : <Copy size={12} />}
                                  Console+post 열기
                                </button>
                              </>
                            )}
                            {grokObservedPostImportPlan?.observedAssetManualRunwayUrl && (
                              <button
                                className="chip"
                                onClick={handleOpenObservedGrokAssetManualRunway}
                                disabled={!grokObservedManualRunwayReady}
                                title="로컬 수동 runway를 열되, 저장/업로드 선택은 사용자가 직접 수행합니다. Codex는 다운로드 승인창을 누르지 않습니다."
                              >
                                {startingGrokManualWatch || openingGrok
                                  ? <RefreshCw size={12} className="spin" />
                                  : <Upload size={12} />}
                                수동 MP4 runway
                              </button>
                            )}
                            {grokObservedAssetUrl && (
                              <button
                                className="chip"
                                onClick={handleOpenObservedGrokAssetManualRunway}
                                disabled={!grokObservedManualRunwayReady}
                                title="직접 MP4 asset 탭은 Chrome 다운로드 승인창을 열 수 있어 Codex 자동화에서 차단됩니다. 로컬 수동 runway만 엽니다."
                              >
                                {startingGrokManualWatch || openingGrok
                                  ? <RefreshCw size={12} className="spin" />
                                  : <Upload size={12} />}
                                Asset 차단됨
                              </button>
                            )}
                            <span>
                              {grokObservedPostImportPlan.ready
                                ? `${grokObservedPostSceneId} direct-import/local upload ready`
                                : grokObservedPostImportPlan.disabledReason || "observed post import plan needs download folder"}
                            </span>
                          </div>
                        )}
                      </div>
                    )}
                    {grokMainPathStatus.secondaryAutomationBlocker && (
                      <small>
                        CDP blocker: {grokMainPathStatus.secondaryAutomationBlocker}
                        {grokMainPathStatus.secondaryAutomationDetail ? ` / ${grokMainPathStatus.secondaryAutomationDetail}` : ""}
                      </small>
                    )}
                    {!!grokMainPathStatus.notBlockedBy?.length && (
                      <div className="grok-quality-chip-row">
                        {grokMainSourceDiagnosis?.doNotDowngradeToStockOnly && (
                          <span className="grok-quality-chip warn">do not downgrade to stock-only</span>
                        )}
                        {grokMainPathStatus.notBlockedBy.slice(0, 3).map((item) => (
                          <span className="grok-quality-chip pass" key={item}>{item}</span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {grokHasPacket && (
                  <div className={`grok-original-runway ${grokOriginalRunwayNeedsReplacement ? "blocked" : grokAssetAcquisition?.publishReadyLocalMp4 ? "ready" : "active"}`}>
                    <div className="grok-original-runway-head">
                      <div>
                        <span>Grok original MP4 runway</span>
                        <strong>
                          {grokAssetAcquisition?.publishReadyLocalMp4
                            ? "원본 소스 통과"
                            : grokOriginalRunwayNeedsReplacement
                              ? "원본 MP4 재확보 필요"
                            : "direct-import 대기"}
                        </strong>
                      </div>
                      <span className="grok-original-runway-badge">
                        {grokOriginalExpectedScene} / {grokOriginalExpectedFile}
                      </span>
                    </div>
                    <div className="grok-original-runway-grid">
                      <span>required source: operator-owned local MP4 import or manual upload after browser-control generation</span>
                      <span>import/manual upload: {grokEffectiveDownloadDir || grokHandoff?.incomingDir || "set import folder"}</span>
                      <span>current candidate: {grokBestLocalCandidate?.fileName || grokSceneAsset?.fileName || "none"}</span>
                      <span>candidate source: {grokBestLocalSourceLabel}</span>
                      <span>candidate probe: {grokBestLocalDimensions}</span>
                      <span>
                        gate: {grokAssetAcquisition?.publishReadyLocalMp4
                          ? "publish-ready"
                          : grokOriginalRunwayNeedsReplacement
                            ? "replace before review"
                            : "waiting for Grok MP4"}
                      </span>
                    </div>
                    <div className="source-guidance-list">
                      <span>1. Generate two takes in signed-in Grok for this exact scene; do not bake captions or explanatory intent into the clip.</span>
                      <span>2. Operator downloads/saves the MP4, then uses local import or manual batch upload; Codex automation must not click Download/Save/Export.</span>
                      <span>3. Keep the filename as {grokOriginalExpectedFile}, or use grouped batch order: scene-01 take A/B, scene-02 take A/B, and so on.</span>
                      <span>4. After import, compare takes in Video Studio and approve only after first-hook, layout, continuity, artifact, and audio-mix review.</span>
                    </div>
                    {grokOriginalExportPlan && (
                      <div className="source-guidance-card compact">
                        <div className="source-guidance-head">
                          <strong>Grok-main original export plan</strong>
                          <span>
                            {grokOriginalExportPlan.modelBlocked || grokOriginalExportPlan.accountBlocked
                              ? "Grok access blocked"
                              : "Grok available; source import is the gate"}
                          </span>
                        </div>
                        <div className="source-guidance-list">
                          {grokOriginalExportPlan.priority && <span>priority: {grokOriginalExportPlan.priority}</span>}
                          {grokOriginalExportPlan.reason && <span>reason: {grokOriginalExportPlan.reason}</span>}
                          <span>paid API: {grokOriginalExportPlan.paidApiRequired ? "required" : "not required"}</span>
                          <span>browser CDP: {grokOriginalExportPlan.cdpPrimary ? "primary" : "secondary only"}</span>
                          {(grokOriginalExportPlan.requiredActions || []).slice(0, 5).map((item, index) => (
                            <span key={`grok-original-action-${index}`}>do: {item}</span>
                          ))}
                          {(grokOriginalExportPlan.rejectAsMainSource || []).slice(0, 4).map((item, index) => (
                            <span key={`grok-original-reject-${index}`}>reject as main: {item}</span>
                          ))}
                          {(grokOriginalExportPlan.operatorProofNeeded || []).slice(0, 3).map((item, index) => (
                            <span key={`grok-original-proof-${index}`}>proof: {item}</span>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="grok-production-actions">
                      <button
                        className="chip"
                        onClick={handleCopyGrokOriginalRunwayChecklist}
                        disabled={loadingGrokFallbackAction === "original-runway-checklist"}
                        title="Copy the scene-specific Grok original MP4 production checklist."
                      >
                        {loadingGrokFallbackAction === "original-runway-checklist"
                          ? <RefreshCw size={12} className="spin" />
                          : <Copy size={12} />}
                        원본 확보 체크리스트
                      </button>
                      <button
                        className="chip"
                        onClick={handleCopyGrokOriginalExpectedFile}
                        disabled={loadingGrokFallbackAction === "original-runway-filename"}
                        title="Copy the exact filename Video Studio expects for this Grok scene."
                      >
                        {loadingGrokFallbackAction === "original-runway-filename"
                          ? <RefreshCw size={12} className="spin" />
                          : <Copy size={12} />}
                        파일명 복사
                      </button>
                    </div>
                    {grokFallbackActionResult && <small>{grokFallbackActionResult}</small>}
                  </div>
                )}
                <div className="grok-production-steps">
                  {grokProductionRailSteps.map((step) => (
                    <div className={`grok-production-step ${step.state}`} key={step.key}>
                      <strong>{step.label}</strong>
                      <span>{step.detail}</span>
                    </div>
                  ))}
                </div>
                {grokManualPrimaryPath && (
                  <div className="source-guidance-card compact">
                    <div className="source-guidance-list">
                      <span>
                        next scene: {grokManualCurrentScene?.sceneId || grokHandoff?.nextMissingSceneId || handoffSceneId}
                        {" -> "}{grokManualCurrentScene?.expectedFileName || grokHandoff?.nextMissingExpectedFileName || "scene.grok.mp4"}
                      </span>
                      {grokManualCurrentScene?.promptExcerpt && <span>prompt: {grokManualCurrentScene.promptExcerpt}</span>}
                      {grokManualCurrentScene?.promptPath && <span>prompt file: {grokManualCurrentScene.promptPath}</span>}
                      {grokManualPrimaryPath.orderedBatchUpload?.selectionRule && (
                        <span>batch rule: {grokManualPrimaryPath.orderedBatchUpload.selectionRule}</span>
                      )}
                      <span>watch fallback: disabled; use direct import or local MP4 upload/import</span>
                      <span>
                        accepted Grok clips: {(grokManualPrimaryPath.acceptedSceneIds || []).length}/{grokManualPrimaryPath.requiredAcceptedScenes || "?"}
                        {typeof grokManualPrimaryPath.additionalAcceptedScenesNeeded === "number"
                          ? ` / need ${grokManualPrimaryPath.additionalAcceptedScenesNeeded} more`
                          : ""}
                      </span>
                      {grokManualQualityRules.slice(0, 3).map((rule) => <span key={rule}>rule: {rule}</span>)}
                    </div>
                  </div>
                )}
                <div className="grok-production-actions">
                  <button className="chip" onClick={handleCreateGrokHandoff} disabled={creatingGrokHandoff}>
                    {creatingGrokHandoff ? <RefreshCw size={12} className="spin" /> : <Clapperboard size={12} />}
                    패킷 준비
                  </button>
                  <button
                    className="chip"
                    onClick={() => window.open(grokProductionQueueUrl, "_blank", "noreferrer")}
                    disabled={!grokProductionQueueUrl}
                    title="전체 씬을 Grok에서 생성하고 MP4를 씬별 take 묶음 순서로 일괄 반입하기 위한 생산 큐를 엽니다."
                  >
                    <Clapperboard size={12} />
                    생산 큐
                  </button>
                  <button
                    className="chip"
                    onClick={handleOpenExistingChromeGrok}
                    disabled={openingGrok}
                    title="기존 로그인 Chrome에서 Grok을 열고 현재 씬 프롬프트를 복사합니다."
                  >
                    {openingGrok ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                    기존 Chrome + prompt
                  </button>
                  <button
                    className="chip"
                    onClick={() => {
                      grokUploadBatchModeRef.current = "scene-grouped-takes";
                      fileInputRef.current?.click();
                    }}
                    disabled={!grokHasPacket || uploadingGrokMp4}
                    title="scene명이 없는 Grok downloads도 선택 순서대로 scene-01 takes, scene-02 takes... 묶음 후보로 보존합니다."
                  >
                    {uploadingGrokMp4 ? <RefreshCw size={12} className="spin" /> : <Upload size={12} />}
                    Grok MP4 일괄 반입
                  </button>
                  <button
                    className="chip"
                    onClick={handleImportGrokDownloads}
                    disabled={!grokHasPacket || importingGrokDownloads || !grokEffectiveDownloadDir}
                    title="이미 operator가 소유한 로컬 Grok MP4만 scene 순서로 반입합니다. Grok Download/Save/Export는 누르지 않습니다."
                  >
                    {importingGrokDownloads ? <RefreshCw size={12} className="spin" /> : <Upload size={12} />}
                    로컬 MP4 반입
                  </button>
                  <button
                    className="chip"
                    onClick={handleWatchGrokDownloads}
                    disabled={nativeGrokDownloadFallbackBlocked || !grokHasPacket || watchingGrokDownloads || renderingGrok || !grokEffectiveDownloadDir}
                    title={nativeGrokDownloadFallbackTitle}
                  >
                    {watchingGrokDownloads ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                    감시 차단
                  </button>
                  <button
                    className="chip"
                    onClick={handleStartGrokManualWatch}
                    disabled={nativeGrokDownloadFallbackBlocked || !grokHasPacket || startingGrokManualWatch || isGrokManualWatchPolling || renderingGrok || !grokEffectiveDownloadDir}
                    title={nativeGrokDownloadFallbackTitle}
                  >
                    {startingGrokManualWatch || isGrokManualWatchPolling ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                    수동 감시 차단
                  </button>
                  <button
                    className="chip"
                    onClick={handleStartGrokManualWatchAll}
                    disabled={nativeGrokDownloadFallbackBlocked || !grokHasPacket || startingGrokManualWatchAll || isGrokManualWatchPolling || renderingGrok || !grokEffectiveDownloadDir}
                    title={nativeGrokDownloadFallbackTitle}
                  >
                    {startingGrokManualWatchAll || isGrokManualWatchPolling ? <RefreshCw size={12} className="spin" /> : <Clapperboard size={12} />}
                    전체 감시 차단
                  </button>
                  <button className="chip" onClick={handleOpenGrokReviewPacket} disabled={!grokReviewPacketUrl}>
                    <Captions size={12} />
                    후보 검수
                  </button>
                  <button
                    className="chip"
                    onClick={handleRenderGrokPreview}
                    disabled={!grokPreviewReady || renderingGrok}
                    title="가져온 Grok MP4만 먼저 이어 붙여 빠르게 레이아웃/자막/BGM 품질을 확인합니다. 최종 렌더 게이트는 그대로 유지됩니다."
                  >
                    {renderingGrok ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                    Grok 미리 렌더
                  </button>
                  <button className="chip" onClick={handleRenderGrok} disabled={!grokMainReady || renderingGrok}>
                    {renderingGrok ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                    Grok-main 렌더
                  </button>
                </div>
                <small>
                  이 레일이 기본 제작 경로입니다. Grok API나 Codex Chrome 직접 제어에 기대지 않고, Grok 앱/웹 MP4를 메인 소스로 가져온 뒤 scene-01 후보들, scene-02 후보들 순서로 반입해 Video Studio가 후보 선택, 자막/BGM/렌더, 품질 게이트를 맡습니다. Grok 미리 렌더는 현재 확보된 {grokPreviewReadyCount}개 클립만 빠르게 확인하고, 최종 Grok-main 렌더는 전체 gate 통과 후 실행됩니다.
                </small>
                {!!grokManualOperatorSteps.length && (
                  <div className="source-guidance-card compact">
                    <div className="source-guidance-list">
                      {grokManualOperatorSteps.slice(0, 6).map((step, index) => <span key={`${index}-${step}`}>{index + 1}. {step}</span>)}
                    </div>
                  </div>
                )}
              </div>
              {grokHandoff?.projectId && (
                <div className={`grok-quality-gate ${grokGateStatusClass(grokSceneQualityGate?.status || (grokSceneAsset?.status === "ready" ? "pending-operator-review" : "missing"))}`}>
                  <div className="grok-quality-gate-head">
                    <span>Grok primary-source gate</span>
                    <strong>{grokGateStatusLabel(grokSceneQualityGate?.status || (grokSceneAsset?.status === "ready" ? "pending-operator-review" : "missing"))}</strong>
                  </div>
                  <div className="grok-quality-gate-grid">
                    <span>scene: {handoffSceneId}</span>
                    {grokManualPrimaryPath?.currentScene?.recommendedTakeNumber && (
                      <span>
                        recommended take: {grokManualPrimaryPath.currentScene.recommendedTakeNumber}
                        {grokManualPrimaryPath.currentScene.recommendedTakeLabel ? ` / ${grokManualPrimaryPath.currentScene.recommendedTakeLabel}` : ""}
                      </span>
                    )}
                    <span>expected: {grokSceneAsset?.expectedFileName || grokHandoffScene?.expectedFileName || `${handoffSceneId}.grok.mp4`}</span>
                    <span>prompt: {grokPromptQuality?.status || "not packaged"}</span>
                    <span>prompt score: {typeof grokPromptQuality?.score === "number" ? grokPromptQuality.score : "?"}</span>
                    <span>template: {grokProductionProfile?.family || templateType}</span>
                    <span>accepted: {grokGateAcceptedCount}/{grokHandoff.totalScenes || "?"}</span>
                    <span>main source: {grokMainAcceptedCount}/{grokMainMinAccepted || "?"}</span>
                    <span>planned Grok: {grokMainPlannedCount || "?"}/{grokMainTotalCount || "?"}</span>
                    <span>source mix: {grokMainSourceGate?.status || "waiting"}</span>
                    <span>candidate gaps: {grokMainSourceGate?.candidateCurationGapSceneIds?.length ? grokMainSourceGate.candidateCurationGapSceneIds.join(", ") : "none"}</span>
                    <span>gate: {grokGateRequired ? "required" : "recommended"}</span>
                    <span>asset: {grokSceneAsset?.fileName || grokSceneAsset?.status || "missing"}</span>
                    <span>source: {grokSourceProvenanceLabel(grokSelectedSourceStatus)}</span>
                    <span>blocking: {grokGateBlockingSceneIds.length ? grokGateBlockingSceneIds.join(", ") : "none"}</span>
                  </div>
                  {grokPromptQuality?.missing?.length ? (
                    <small>prompt gaps: {grokPromptQuality.missing.join(", ")}</small>
                  ) : grokHandoff?.shotBible?.layoutPlan ? (
                    <small>production layout: {grokHandoff.shotBible.layoutPlan}</small>
                  ) : null}
                  {grokPromptQuality?.weakSourcePrompt && (
                    <small>
                      source prompt is too generic
                      {typeof grokPromptQuality.sourceWordCount === "number" ? ` / words ${grokPromptQuality.sourceWordCount}` : ""}
                      {grokPromptQuality.sourcePrompt ? ` / "${grokPromptQuality.sourcePrompt}"` : ""}
                    </small>
                  )}
                  {grokPromptQuality?.operatorAction && <small>prompt action: {grokPromptQuality.operatorAction}</small>}
                  <div className="grok-quality-chip-row">
                    <span className={`grok-quality-chip ${grokReviewDecision?.firstTwoSecondHook ? "pass" : "neutral"}`}>first 2s hook</span>
                    <span className={`grok-quality-chip ${grokReviewDecision?.artifactFree ? "pass" : "neutral"}`}>artifact-free</span>
                    <span className={`grok-quality-chip ${grokReviewDecision?.continuityOk ? "pass" : "neutral"}`}>continuity</span>
                    <span className={`grok-quality-chip ${grokSceneQualityGate?.technicalOk === false ? "fail" : grokSceneQualityGate?.technicalOk ? "pass" : "neutral"}`}>
                      probe {grokSceneAsset?.clipProbe?.width && grokSceneAsset?.clipProbe?.height
                        ? `${grokSceneAsset.clipProbe.width}x${grokSceneAsset.clipProbe.height}`
                        : "waiting"}
                    </span>
                    <span className={`grok-quality-chip ${grokSourceProvenanceClass(grokSelectedSourceStatus, grokSelectedSourceProvenance?.acceptAsGrokMainSource)}`}>
                      {grokSourceProvenanceLabel(grokSelectedSourceStatus)}
                    </span>
                  </div>
                  {grokSceneQualityGate?.technicalIssues?.length ? (
                    <small>technical issues: {grokSceneQualityGate.technicalIssues.join(", ")}</small>
                  ) : grokSceneQualityGate?.sourceIssues?.length ? (
                    <small>source issues: {grokSceneQualityGate.sourceIssues.join(", ")}</small>
                  ) : grokSelectedSourceProvenance?.operatorAction ? (
                    <small>source action: {grokSelectedSourceProvenance.operatorAction}</small>
                  ) : grokMainAdditionalPlanned > 0 ? (
                    <small>top-tier source mix needs {grokMainAdditionalPlanned} more Grok scene(s) planned before generation; switch more scenes to Grok/local/direct instead of Pexels filler.</small>
                  ) : grokMainAdditionalAccepted > 0 ? (
                    <small>top-tier source mix needs {grokMainAdditionalAccepted} more accepted Grok MP4 scene(s) before render can be considered Grok-main.</small>
                  ) : grokSceneQualityGate?.status === "accepted" ? (
                    <small>this scene is accepted as a Grok hero clip and can feed the render payload.</small>
                  ) : grokSceneAsset?.status === "ready" ? (
                    <small>imported MP4 is waiting for operator review: first hook, artifact check, continuity, caption-safe framing.</small>
                  ) : (
                    <small>Grok cannot be the main visual source yet: put the generated MP4 in incoming or Downloads, then sync/import and review it.</small>
                  )}
                  <div className="button-row" style={{ marginTop: 8 }}>
                    <button className="chip" onClick={handleOpenGrokReviewPacket} disabled={!grokHandoff.reviewPacketUrl}>
                      <Captions size={12} />
                      검수 패킷
                    </button>
                  </div>
                  <div className="button-row" style={{ marginTop: 8 }}>
                    <button
                      className="chip"
                      onClick={() => handleCopyGrokBookmarklet(false)}
                      disabled={!!loadingGrokFallbackAction}
                      title="Grok 탭에서 실행할 현재 씬 self-contained prompt-fill bookmarklet을 복사합니다."
                    >
                      {loadingGrokFallbackAction === "bookmarklet-fill" ? <RefreshCw size={12} className="spin" /> : <Copy size={12} />}
                      Fill inline
                    </button>
                    <button
                      className="chip"
                      onClick={() => handleCopyGrokBookmarklet(true)}
                      disabled={!!loadingGrokFallbackAction}
                      title="Grok 탭에서 실행할 현재 씬 self-contained prompt-fill + generate bookmarklet을 복사합니다."
                    >
                      {loadingGrokFallbackAction === "bookmarklet-generate" ? <RefreshCw size={12} className="spin" /> : <Copy size={12} />}
                      Inline+Generate
                    </button>
                    <button
                      className="chip"
                      onClick={() => handleCopyGrokConsoleFallback(true)}
                      disabled={!!loadingGrokFallbackAction}
                      title="Grok 탭 DevTools console에 붙여넣을 self-contained fill+generate snippet을 복사합니다."
                    >
                      {loadingGrokFallbackAction === "console-generate" ? <RefreshCw size={12} className="spin" /> : <Copy size={12} />}
                      Console+Generate
                    </button>
                    <button
                      className="chip"
                      onClick={handleCopyGrokQueueBookmarklet}
                      disabled={!!loadingGrokFallbackAction}
                      title="로그인된 Grok 탭에서 다음 누락 씬부터 생성/다운로드/가져오기를 이어가는 self-contained queue bookmarklet을 복사합니다."
                    >
                      {loadingGrokFallbackAction === "queue-bookmarklet" ? <RefreshCw size={12} className="spin" /> : <Copy size={12} />}
                      Queue inline
                    </button>
                    <button
                      className="chip"
                      onClick={handleCopyGrokQueueConsoleFallback}
                      disabled={!!loadingGrokFallbackAction}
                      title="Grok 탭 console에서 실행할 queue fallback snippet을 복사합니다."
                    >
                      {loadingGrokFallbackAction === "queue-console" ? <RefreshCw size={12} className="spin" /> : <Copy size={12} />}
                      Queue console
                    </button>
                    <button
                      className="chip"
                      onClick={handleOpenGrokPrepGenerateUrl}
                      disabled={!!loadingGrokFallbackAction}
                      title="Grok Imagine URL hash에 현재 씬 command를 실어 새 탭으로 엽니다."
                    >
                      {loadingGrokFallbackAction === "prep-generate-url" ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                      Hash+Generate
                    </button>
                  </div>
                  {grokTakePrompts.length > 1 && (
                    <div className="grok-quality-gate active" style={{ marginTop: 8 }}>
                      <div className="grok-quality-gate-head">
                        <span>Grok take ladder</span>
                        <strong>{grokTakePrompts.length} candidates</strong>
                      </div>
                      <small>Generate multiple distinct MP4 takes for this scene, then accept only the strongest candidate after review.</small>
                      {grokTakePrompts.map((take) => {
                        const takeNumber = Number(take.takeNumber || 1);
                        const actionBase = `take-${takeNumber}`;
                        return (
                          <div className="asset-variant-row" key={`${takeNumber}:${take.label || "take"}`}>
                            <strong>Take {takeNumber}: {take.label || `take-${takeNumber}`}</strong>
                            {take.focus && <span>{take.focus}</span>}
                            <small>
                              prompt {take.promptQuality?.status || "ready"}
                              {typeof take.promptQuality?.score === "number" ? ` / ${take.promptQuality.score}` : ""}
                            </small>
                            <div className="button-row">
                              <button
                                className="chip"
                                onClick={() => handleCopyGrokTakeGenerate(takeNumber, "bookmarklet")}
                                disabled={!!loadingGrokFallbackAction}
                                title="Copy the self-contained Grok fill+generate bookmarklet for this take."
                              >
                                {loadingGrokFallbackAction === `${actionBase}-bookmarklet` ? <RefreshCw size={12} className="spin" /> : <Copy size={12} />}
                                Take generate
                              </button>
                              <button
                                className="chip"
                                onClick={() => handleCopyGrokTakeGenerate(takeNumber, "console")}
                                disabled={!!loadingGrokFallbackAction}
                                title="Copy the self-contained Grok fill+generate console snippet for this take."
                              >
                                {loadingGrokFallbackAction === `${actionBase}-console` ? <RefreshCw size={12} className="spin" /> : <Copy size={12} />}
                                Take console
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {grokFallbackActionResult && <small>{grokFallbackActionResult}</small>}
                </div>
              )}
              <small>
                기본 경로는 기존 signed-in Chrome/Grok 탭에서 browser-control로 생성 proof를 확보한 뒤, operator-owned manual download/save와 로컬 MP4 반입으로 이어가는 방식입니다. Chrome/Grok Download/Save/Export 자동 클릭과 native prompt 자동화는 차단됩니다.
              </small>
              <div className="button-row">
                <button className="chip" onClick={handleCreateGrokHandoff} disabled={creatingGrokHandoff}>
                  {creatingGrokHandoff ? <RefreshCw size={12} className="spin" /> : <Clapperboard size={12} />}
                  {creatingGrokHandoff ? "패킷 생성 중" : "패킷 준비"}
                </button>
                <button className="chip" onClick={() => handleOpenGrok("worksheet")} disabled={openingGrok}>
                  {openingGrok ? <RefreshCw size={12} className="spin" /> : <Clapperboard size={12} />}
                  작업 시트
                </button>
                <button className="chip" onClick={() => handleOpenGrok("grok")} disabled={openingGrok}>
                  {openingGrok ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                  Grok 열기
                </button>
                <button
                  className="chip"
                  onClick={handleOpenExistingChromeGrok}
                  disabled={openingGrok}
                  title="CDP 없이 로그인된 기존 Chrome 프로필로 Grok을 열고 현재 씬 프롬프트를 클립보드에 복사합니다."
                >
                  {openingGrok ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                  기존 Chrome 열기
                </button>
                <button
                  className="chip"
                  onClick={handleFocusGrokOperator}
                  disabled={!grokHandoff?.projectId || focusingGrokOperator}
                  title="승인된 로컬 CDP 세션에서 현재 Grok/xAI 로그인 또는 Imagine 탭을 앞으로 가져옵니다."
                >
                  {focusingGrokOperator ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                  로그인 탭 포커스
                </button>
                <button
                  className="chip"
                  onClick={handleCleanupGrokTabs}
                  disabled={!grokHandoff?.projectId || cleaningGrokTabs}
                  title="승인된 로컬 CDP 세션에서 중복 Grok/xAI 탭을 닫고 로그인 대상 하나만 남깁니다."
                >
                  {cleaningGrokTabs ? <RefreshCw size={12} className="spin" /> : <X size={12} />}
                  중복 탭 정리
                </button>
                <button className="chip" onClick={handleSyncGrok} disabled={!grokHandoff?.projectId || syncingGrok}>
                  {syncingGrok ? <RefreshCw size={12} className="spin" /> : <RefreshCw size={12} />}
                  MP4 동기화
                </button>
                <button className="chip" onClick={handleOpenGrokAutomationPlan} disabled={!grokHandoff?.projectId || loadingGrokPlan}>
                  {loadingGrokPlan ? <RefreshCw size={12} className="spin" /> : <Clapperboard size={12} />}
                  자동화 플랜
                </button>
                <button className="chip" onClick={handleOpenGrokReviewPacket} disabled={!grokHandoff?.reviewPacketUrl}>
                  <Captions size={12} />
                  Grok 검수
                </button>
                <button
                  className="chip"
                  onClick={handleRenderGrokPreview}
                  disabled={!grokPreviewReady || renderingGrok}
                  title="현재 반입된 Grok MP4만 먼저 렌더해 품질을 빠르게 확인합니다."
                >
                  {renderingGrok ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                  미리 렌더
                </button>
                <button className="chip" onClick={handleRenderGrok} disabled={!grokMainReady || renderingGrok}>
                  {renderingGrok ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                  Grok 렌더
                </button>
              </div>
              <div className="button-row" style={{ marginTop: 8 }}>
                <input
                  className="editable-input"
                  value={grokDownloadDir}
                  onChange={(e) => setGrokDownloadDir(e.target.value)}
                  placeholder={grokHandoff?.defaultDownloadDir || "C:\\Users\\...\\Downloads"}
                />
                {grokHandoff?.defaultDownloadDir && (
                  <button
                    className="chip"
                    onClick={() => setGrokDownloadDir(grokHandoff.defaultDownloadDir || "")}
                  >
                    기본 Downloads
                  </button>
                )}
                <button className="chip" onClick={handleImportGrokDownloads} disabled={!grokHandoff?.projectId || importingGrokDownloads}>
                  {importingGrokDownloads ? <RefreshCw size={12} className="spin" /> : <Upload size={12} />}
                  로컬 MP4 fallback
                </button>
                <button
                  className="chip"
                  onClick={handleWatchGrokDownloads}
                  disabled={nativeGrokDownloadFallbackBlocked || !grokHandoff?.projectId || watchingGrokDownloads || renderingGrok}
                  title={nativeGrokDownloadFallbackTitle}
                >
                  {watchingGrokDownloads ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                  감시 차단
                </button>
                <button
                  className="chip"
                  onClick={handleStartGrokManualWatch}
                  disabled={nativeGrokDownloadFallbackBlocked || !grokHandoff?.projectId || startingGrokManualWatch || isGrokManualWatchPolling || renderingGrok || !grokEffectiveDownloadDir}
                  title={nativeGrokDownloadFallbackTitle}
                >
                  {startingGrokManualWatch || isGrokManualWatchPolling ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                  수동 감시 차단
                </button>
                <button
                  className="chip"
                  onClick={handleStartGrokManualWatchAll}
                  disabled={nativeGrokDownloadFallbackBlocked || !grokHandoff?.projectId || startingGrokManualWatchAll || isGrokManualWatchPolling || renderingGrok || !grokEffectiveDownloadDir}
                  title={nativeGrokDownloadFallbackTitle}
                >
                  {startingGrokManualWatchAll || isGrokManualWatchPolling ? <RefreshCw size={12} className="spin" /> : <Clapperboard size={12} />}
                  전체 감시 차단
                </button>
                <button
                  className="chip"
                  onClick={handleRunGrokOperator}
                  disabled={nativeGrokDownloadFallbackBlocked || !grokHandoff?.projectId || runningGrokOperator || renderingGrok}
                  title={nativeGrokDownloadFallbackTitle}
                >
                  {runningGrokOperator ? <RefreshCw size={12} className="spin" /> : <Clapperboard size={12} />}
                  실행+감시 차단
                </button>
                <input
                  className="editable-input"
                  type="number"
                  min={30}
                  max={GROK_OPERATOR_WAIT_MAX_SECONDS}
                  step={30}
                  value={grokAuthWaitSeconds}
                  onChange={(e) => setGrokAuthWaitSeconds(e.target.value)}
                  title="Grok auth wait seconds"
                  style={{ maxWidth: 112 }}
                />
                <select
                  className="editable-input"
                  value={grokAuthProvider}
                  onChange={(e) => setGrokAuthProvider(e.target.value as GrokAuthProvider)}
                  title="xAI sign-in provider"
                  style={{ maxWidth: 124 }}
                >
                  {GROK_AUTH_PROVIDER_OPTIONS.map((option) => (
                    <option key={option.key} value={option.key}>{option.label}</option>
                  ))}
                </select>
                <button
                  className="chip"
                  onClick={handleRunGrokBrowserAutomation}
                  disabled={!grokHandoff?.projectId || runningGrokBrowserAutomation || renderingGrok}
                  title="승인된 브라우저에서 prompt fill/generate까지만 실행합니다. MP4는 direct import 또는 로컬 업로드로만 반입합니다."
                >
                  {runningGrokBrowserAutomation ? <RefreshCw size={12} className="spin" /> : <Clapperboard size={12} />}
                  승인 대기+생성
                </button>
                <button
                  className="chip"
                  onClick={handleStartGrokBackgroundAutomation}
                  disabled={startingGrokBackgroundAutomation || renderingGrok}
                  title="패킷이 없으면 먼저 만들고, 승인된 브라우저 세션에서 prompt generation까지만 백그라운드로 실행합니다. 다운로드 감시는 차단됩니다."
                >
                  {startingGrokBackgroundAutomation ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                  승인 자동 생성
                </button>
                <button
                  className="chip"
                  onClick={handleStartNextGrokBackgroundAutomation}
                  disabled={!grokHandoff?.nextMissingSceneId || startingNextGrokBackgroundAutomation || renderingGrok}
                  title="다음 미완료/탈락 Grok 씬을 승인된 브라우저에서 prompt generation까지만 이어서 생성합니다. 다운로드 감시는 차단됩니다."
                >
                  {startingNextGrokBackgroundAutomation ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                  다음 씬 자동 생성
                </button>
                <button
                  className="chip"
                  onClick={handleRestartGrokBackgroundAutomationWithIsolatedProfile}
                  disabled={!grokHandoff?.automationJob?.activeThread || restartingGrokBackgroundAutomation || renderingGrok}
                  title="현재 Grok auth-wait job을 승인 취소하고 9333 포트의 격리된 Grok 로그인 프로필로 prompt generation만 다시 시작합니다. 다운로드 감시는 차단됩니다."
                >
                  {restartingGrokBackgroundAutomation ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                  격리 프로필 재시작
                </button>
                <button
                  className="chip"
                  onClick={handleStartGrokBackgroundAutomationWithDefaultChromeAttach}
                  disabled={attachingDefaultChromeGrok || renderingGrok}
                  title="사용자가 직접 127.0.0.1:9222 CDP로 실행한 로그인 Chrome/SuperGrok 세션에만 붙고 prompt generation까지만 실행합니다. Video Studio는 다운로드 감시를 하지 않습니다."
                >
                  {attachingDefaultChromeGrok ? <RefreshCw size={12} className="spin" /> : <Clapperboard size={12} />}
                  로그인 Chrome attach
                </button>
                <button
                  className="chip"
                  onClick={handleResumeGrokBrowserAutomation}
                  disabled={!grokHandoff?.automationReplay || resumingGrokAutomation || renderingGrok}
                >
                  {resumingGrokAutomation ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                  승인 재개
                </button>
              </div>
              {grokHandoff?.projectId && (
                <div className="grok-handoff-review" style={{ marginTop: 8 }}>
                  {!!grokCandidateAssets.length && (
                    <div className="asset-variant-row">
                      <strong>Grok candidate MP4</strong>
                      <span>여러 take를 만들었다면 여기서 실제 렌더에 쓸 파일을 먼저 고릅니다.</span>
                      <div className="pexels-candidate-grid">
                        {grokCandidateAssets.map((candidate) => {
                          const selected = candidate.fileName === selectedGrokCandidateFileName;
                          const probeOk = candidate.clipProbe?.ok !== false;
                          return (
                            <button
                              type="button"
                              key={candidate.fileName || candidate.previewUrl || candidate.sourcePath}
                              className={`pexels-candidate ${selected ? "selected" : ""}`}
                              onClick={() => setSelectedGrokCandidateFileName(candidate.fileName || "")}
                            >
                              {candidate.previewUrl ? (
                                <video src={candidate.previewUrl} muted playsInline preload="metadata" controls />
                              ) : (
                                <span>preview unavailable</span>
                              )}
                              <span>{candidate.fileName || "candidate.mp4"}</span>
                              <small>{grokCandidateLabel(candidate)}</small>
                              <small>
                                source: {grokSourceProvenanceLabel(candidate.sourceProvenance?.status)}
                                {candidate.sourceProvenance?.sourceKind ? ` / ${candidate.sourceProvenance.sourceKind}` : ""}
                              </small>
                              <small>{selected ? "selected for review" : candidate.selected ? "server matched" : "candidate"} / {probeOk ? "probe ok" : "probe needs review"}</small>
                              {candidate.sourceProvenance?.operatorAction && (
                                <small>{candidate.sourceProvenance.operatorAction}</small>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  <div className="grok-quality-chip-row">
                    {([
                      ["firstTwoSecondHook", "first 2s hook"],
                      ["artifactFree", "artifact-free"],
                      ["continuityOk", "continuity"],
                      ["captionSafe", "caption-safe"],
                    ] as const).map(([key, label]) => (
                      <label key={key} className={`grok-quality-chip ${grokReviewChecks[key] ? "pass" : "neutral"}`}>
                        <input
                          type="checkbox"
                          checked={grokReviewChecks[key]}
                          onChange={(e) => setGrokReviewChecks((prev) => ({ ...prev, [key]: e.target.checked }))}
                        />
                        {label}
                      </label>
                    ))}
                  </div>
                  <textarea
                    className="editable-input"
                    value={grokReviewOperatorNote}
                    onChange={(e) => setGrokReviewOperatorNote(e.target.value)}
                    rows={2}
                    placeholder="Grok 검수 메모: artifact, watermark, continuity, safe zone"
                  />
                  <textarea
                    className="editable-input"
                    value={grokCandidateSummary}
                    onChange={(e) => setGrokCandidateSummary(e.target.value)}
                    rows={2}
                    placeholder="후보 비교 메모: 선택한 take가 다른 Grok take보다 나은 이유"
                  />
                  {grokSourceConfirmationRequired && (
                    <div className="source-guidance-card compact">
                      <label className={`grok-quality-chip ${grokReviewQualityFields.sourceProvenanceConfirmed ? "pass" : "neutral"}`}>
                        <input
                          type="checkbox"
                          checked={grokReviewQualityFields.sourceProvenanceConfirmed}
                          onChange={(e) => setGrokReviewQualityFields((prev) => ({
                            ...prev,
                            sourceProvenanceConfirmed: e.target.checked,
                          }))}
                        />
                        Grok 원본 저장 확인
                      </label>
                      <textarea
                        className="editable-input"
                        value={grokReviewQualityFields.sourceProvenanceNote}
                        onChange={(e) => setGrokReviewQualityFields((prev) => ({
                          ...prev,
                          sourceProvenanceNote: e.target.value,
                        }))}
                        rows={2}
                        placeholder="operator-owned manual download/import 또는 explicit upload인지와 현재 take 파일명 확인 메모"
                      />
                    </div>
                  )}
                  {grokDetailedReviewRequired && (
                    <div className="source-guidance-card compact">
                      <div className="field-row">
                        <label>
                          Visual verdict
                          <select
                            value={grokReviewQualityFields.visualQualityVerdict}
                            onChange={(e) => setGrokReviewQualityFields((prev) => ({
                              ...prev,
                              visualQualityVerdict: e.target.value as GrokReviewVisualVerdict,
                            }))}
                          >
                            <option value="">미검수</option>
                            <option value="pass">pass</option>
                            <option value="needs-retry">needs-retry</option>
                            <option value="fail">fail</option>
                          </select>
                        </label>
                      </div>
                      <div className="grok-quality-chip-row">
                        <label className={`grok-quality-chip ${grokReviewQualityFields.shotLockMatch ? "pass" : "neutral"}`}>
                          <input
                            type="checkbox"
                            checked={grokReviewQualityFields.shotLockMatch}
                            onChange={(e) => setGrokReviewQualityFields((prev) => ({
                              ...prev,
                              shotLockMatch: e.target.checked,
                            }))}
                          />
                          shot-lock
                        </label>
                        <label className={`grok-quality-chip ${grokReviewQualityFields.sceneAssemblyOk ? "pass" : "neutral"}`}>
                          <input
                            type="checkbox"
                            checked={grokReviewQualityFields.sceneAssemblyOk}
                            onChange={(e) => setGrokReviewQualityFields((prev) => ({
                              ...prev,
                              sceneAssemblyOk: e.target.checked,
                            }))}
                          />
                          edit role
                        </label>
                      </div>
                      <textarea
                        className="editable-input"
                        value={grokReviewQualityFields.shotLockEvidenceNote}
                        onChange={(e) => setGrokReviewQualityFields((prev) => ({ ...prev, shotLockEvidenceNote: e.target.value }))}
                        rows={2}
                        placeholder="Shot-lock evidence: 고정한 액션/피사체/카메라/첫 움직임과 실제 take가 일치하는 근거"
                      />
                      <textarea
                        className="editable-input"
                        value={grokReviewQualityFields.sceneAssemblyRoleNote}
                        onChange={(e) => setGrokReviewQualityFields((prev) => ({ ...prev, sceneAssemblyRoleNote: e.target.value }))}
                        rows={2}
                        placeholder="Scene assembly: 이 take가 hook/build/proof/payoff 중 어떤 역할이고 앞뒤 컷과 어떻게 이어지는지"
                      />
                      <textarea
                        className="editable-input"
                        value={grokReviewQualityFields.captionLayoutReviewNote}
                        onChange={(e) => setGrokReviewQualityFields((prev) => ({ ...prev, captionLayoutReviewNote: e.target.value }))}
                        rows={2}
                        placeholder="Caption/layout: 피사체가 자막 safe zone, 오른쪽 Shorts UI, 하단 danger zone에 가리지 않는지"
                      />
                      <textarea
                        className="editable-input"
                        value={grokReviewQualityFields.hookNote}
                        onChange={(e) => setGrokReviewQualityFields((prev) => ({ ...prev, hookNote: e.target.value }))}
                        rows={2}
                        placeholder="First 2s hook: 첫 2초 안에 무슨 움직임이 보이고 왜 멈추지 않는지"
                      />
                      <textarea
                        className="editable-input"
                        value={grokReviewQualityFields.continuityNote}
                        onChange={(e) => setGrokReviewQualityFields((prev) => ({ ...prev, continuityNote: e.target.value }))}
                        rows={2}
                        placeholder="Continuity: 인물/장소/소품/색감/카메라 움직임이 이전·다음 씬과 이어지는지"
                      />
                      <textarea
                        className="editable-input"
                        value={grokReviewQualityFields.layoutVariantNote}
                        onChange={(e) => setGrokReviewQualityFields((prev) => ({ ...prev, layoutVariantNote: e.target.value }))}
                        rows={2}
                        placeholder="Layout variant: no caption/top hook/lower info 등 어떤 레이아웃이 이 take에 맞는지"
                      />
                      <textarea
                        className="editable-input"
                        value={grokReviewQualityFields.thumbnailReviewNote}
                        onChange={(e) => setGrokReviewQualityFields((prev) => ({ ...prev, thumbnailReviewNote: e.target.value }))}
                        rows={2}
                        placeholder="Thumbnail/first frame: 첫 프레임이 클릭 가능한지, 텍스트/워터마크/흐림이 없는지"
                      />
                      <textarea
                        className="editable-input"
                        value={grokReviewQualityFields.audioMixReviewNote}
                        onChange={(e) => setGrokReviewQualityFields((prev) => ({ ...prev, audioMixReviewNote: e.target.value }))}
                        rows={2}
                        placeholder="Audio mix: native audio를 쓸지, BGM/SFX/TTS와 충돌하지 않는지"
                      />
                      <textarea
                        className="editable-input"
                        value={grokReviewQualityFields.platformComparisonNote}
                        onChange={(e) => setGrokReviewQualityFields((prev) => ({ ...prev, platformComparisonNote: e.target.value }))}
                        rows={2}
                        placeholder="Platform benchmark: 한국 Shorts/롱폼의 실제 상위권 스타일 대비 무엇이 나은지/부족한지"
                      />
                    </div>
                  )}
                  <div className={`source-guidance-card compact ${grokReviewEvidenceReady && grokSelectedSourceAcceptable && grokSourceConfirmationReady ? "" : "blocked"}`}>
                    <div className="source-guidance-list">
                      <span>
                        source provenance: {grokSelectedSourceAcceptable ? grokSourceProvenanceLabel(grokSelectedSourceStatus) : "proof-only fallback blocked"}
                      </span>
                      {!grokSelectedSourceAcceptable && (
                        <span>{grokSelectedSourceProvenance?.operatorAction || "Use operator-owned Grok MP4 download/import or explicit manual batch upload before accepting this scene."}</span>
                      )}
                      <span>approval evidence: {grokReviewEvidenceReady ? "ready" : "선택 근거와 채널 품질 검수 메모를 먼저 구체적으로 작성"}</span>
                      <span>선택 근거는 generic 업로드 문구가 아니라 이 take를 고른 이유여야 합니다.</span>
                      <span>품질 메모에는 watermark/artifact/자막 safe zone/컷 자연스러움 확인을 남깁니다.</span>
                      {grokCandidateEvidenceRequired && (
                        <span>candidate curation: {grokCandidateEvidenceReady ? "ready" : "Grok take 2개 이상 가져온 뒤 선택 후보 비교 메모 필요"}</span>
                      )}
                      {grokSourceConfirmationRequired && (
                        <span>original MP4 confirmation: {grokSourceConfirmationReady ? "ready" : "manual download/import 또는 explicit upload 확인 체크와 24자 이상 메모 필요"}</span>
                      )}
                      {grokDetailedReviewRequired && (
                        <span>detailed review: {grokDetailedReviewReady ? "ready" : `필수 미작성: ${grokDetailedReviewMissing.join(", ")}`}</span>
                      )}
                    </div>
                  </div>
                  <div className="button-row" style={{ marginTop: 8 }}>
                    <button
                      className="chip"
                      onClick={() => handleSaveGrokReview(true)}
                      disabled={!canReviewGrokScene || savingGrokReview || !grokReviewApprovalReady}
                      title={!grokSelectedSourceAcceptable
                        ? "Grok-main approval requires operator-owned manual download/import or explicit manual upload; visible-video/currentSrc fallback is proof-only."
                        : !grokReviewAllRequiredChecks
                        ? "Grok clip approval requires first hook, artifact-free, continuity, and caption-safe checks."
                        : !grokReviewEvidenceReady
                          ? "Grok clip approval requires concrete selection rationale and quality review notes."
                          : !grokCandidateEvidenceReady
                            ? "Grok-main approval requires at least two Grok take candidates and a comparison note."
                            : !grokSourceConfirmationReady
                              ? "Grok-main approval requires confirmation that the local MP4 came through operator-owned manual download/import or explicit manual upload."
                            : !grokDetailedReviewReady
                              ? "Grok-main approval requires explicit visual/layout/audio/platform review fields."
                          : undefined}
                    >
                      {savingGrokReview ? <RefreshCw size={12} className="spin" /> : <Captions size={12} />}
                      검수 승인
                    </button>
                    <button
                      className="chip"
                      onClick={() => handleSaveGrokReview(false)}
                      disabled={!canReviewGrokScene || savingGrokReview}
                    >
                      {savingGrokReview ? <RefreshCw size={12} className="spin" /> : <X size={12} />}
                      탈락 저장
                    </button>
                  </div>
                </div>
              )}
              {grokHandoff?.incomingDir && (
                <div className="grok-handoff-meta">
                  <span>incoming: {grokHandoff.incomingDir}</span>
                  {grokHandoff.worksheetUrl && <span>worksheet: {grokHandoff.worksheetUrl}</span>}
                  {grokHandoff.automationPlanUrl && <span>automation: {grokHandoff.automationPlanUrl}</span>}
                  {grokHandoff.reviewPacketUrl && <span>review: {grokHandoff.reviewPacketUrl}</span>}
                  {grokHandoff.defaultDownloadDir && (
                    <span>downloads: {grokHandoff.defaultDownloadDir}{grokHandoff.defaultDownloadDirExists === false ? " (missing)" : ""}</span>
                  )}
                  {grokAutomationStatus?.browserProfileMode === "default-chrome-cdp-attach" && (
                    <span>profile: logged-in Chrome attach / port {grokAutomationStatus.remoteDebuggingPort || 9222}</span>
                  )}
                  {grokAutomationStatus?.useDefaultChromeProfile && grokAutomationStatus?.browserProfileMode !== "default-chrome-cdp-attach" && (
                    <span>profile: default Chrome attach requested / {grokAutomationStatus.browserProfileDirectory || "Default"}</span>
                  )}
                  {grokAutomationStatus?.launched && !grokAutomationStatus.useDefaultChromeProfile && (
                    <span>profile: isolated Grok login / {grokAutomationStatus.browserProfileDirectory || "Default"}</span>
                  )}
                  <span>sign-in provider: {grokAutomationStatus?.authProviderPreference || grokAuthProvider}</span>
                  <span>Chrome 136+: 일반 기본 프로필 CDP는 차단될 수 있어 attach 실패 시 격리 프로필 사용</span>
                  <span>검수: {grokReviewStatusLabel}</span>
                  {grokReviewDecision?.qualityReviewNote && <span>quality: {grokReviewDecision.qualityReviewNote}</span>}
                  {grokReviewDecision?.operatorNote && <span>operator: {grokReviewDecision.operatorNote}</span>}
                {typeof grokHandoff.readyScenes === "number" && typeof grokHandoff.totalScenes === "number" && (
                  <span>ready: {grokHandoff.readyScenes}/{grokHandoff.totalScenes}</span>
                )}
                  {grokHandoff.nextMissingSceneId && (
                    <span>next missing: {grokHandoff.nextMissingSceneId} / {grokHandoff.nextMissingExpectedFileName || "mp4"}</span>
                  )}
                  {!!grokHandoff.missingSceneIds?.length && <span>missing: {grokHandoff.missingSceneIds.join(", ")}</span>}
                  {!!grokHandoff.rejectedSceneIds?.length && <span>rejected: {grokHandoff.rejectedSceneIds.join(", ")}</span>}
                  <span>expected: {grokHandoffScene?.expectedFileName || `${handoffSceneId}.grok.mp4`}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {currentSource === "pexels-video" && (
        <div className="scene-detail-section">
          <div className="scene-detail-section-title">Pexels 후보</div>
          <div className="source-guidance-card compact">
            <div className="source-guidance-list">
              <span>support B-roll로만 사용하고, 첫 결과 자동 채택은 실패로 봅니다.</span>
              <span>후보마다 source URL, creator, 왜 이 컷인지 선택 근거를 남겨야 합니다.</span>
            </div>
          </div>
          <button
            className="chip"
            onClick={handleSearchPexels}
            disabled={!scene.image_prompt || searchingPexels}
          >
            {searchingPexels ? <><RefreshCw size={12} className="spin" /> 검색 중...</> : <><Search size={12} /> 후보 검색</>}
          </button>
          {!!scene._pexels_video_candidates?.length && (
            <div className="pexels-candidate-grid">
              {scene._pexels_video_candidates.map((candidate) => (
                <button
                  key={candidate.id}
                  className={`pexels-candidate ${scene._selected_pexels_video?.id === candidate.id ? "selected" : ""}`}
                  onClick={() => actions.selectPexelsVideo(selectedSceneIndex, candidate)}
                >
                  <video src={candidate.url} muted playsInline preload="metadata" />
                  <span>{candidateLabel(candidate)}</span>
                  {(candidate.author || candidate.sourceUrl) && (
                    <small>{candidate.author || "Pexels"}{candidate.sourceUrl ? ` / ${candidate.sourceUrl}` : ""}</small>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {currentSource !== "upload" && currentSource !== "grok" && !isLocalModel && (
        <div className="scene-detail-section">
          <div className="scene-detail-section-title">
            {currentSource === "pexels" ? "검색어" : "영상 프롬프트"}
          </div>
          {editingPrompt ? (
            <textarea
              className="editable-input"
              value={promptDraft}
              onChange={(e) => setPromptDraft(e.target.value)}
              onBlur={commitPrompt}
              onKeyDown={(e) => { if (e.key === "Escape") setEditingPrompt(false); }}
              rows={2}
              autoFocus
            />
          ) : (
            <div className="editable-text" onClick={handlePromptEdit}>
              {scene.image_prompt || <span className="editable-placeholder">프롬프트 입력...</span>}
            </div>
          )}
        </div>
      )}

      <div className="scene-detail-section">
        <div className="scene-detail-section-title">선택 근거</div>
        <textarea
          className="editable-input"
          value={scene.source_rationale || ""}
          onChange={(e) => actions.editScene(selectedSceneIndex, "source_rationale", e.target.value)}
          rows={2}
          placeholder="이 컷을 고른 이유"
        />
      </div>

      <div className="scene-detail-section">
        <div className="scene-detail-section-title">연속성 메모</div>
        <textarea
          className="editable-input"
          value={scene.continuity_note || ""}
          onChange={(e) => actions.editScene(selectedSceneIndex, "continuity_note", e.target.value)}
          rows={2}
          placeholder="인물, 장소, 소품, 색감, 카메라 움직임"
        />
      </div>

      <div className="scene-detail-section">
        <div className="scene-detail-section-title">레이아웃 변형</div>
        {scene.layout_variant_label && (
          <div className="asset-packet-tags">
            <span>{scene.layout_variant_label}</span>
          </div>
        )}
        <textarea
          className="editable-input"
          value={scene.layout_variant_note || ""}
          onChange={(e) => actions.editScene(selectedSceneIndex, "layout_variant_note", e.target.value)}
          rows={2}
          placeholder="씬 패턴, 자막 배치, 컷 리듬 선택 근거"
        />
      </div>

      <div className="scene-detail-section">
        <div className="scene-detail-section-title">원본 / AI handoff 증거</div>
        <textarea
          className="editable-input"
          value={scene.originality_evidence || ""}
          onChange={(e) => actions.editScene(selectedSceneIndex, "originality_evidence", e.target.value)}
          rows={2}
          placeholder="직접 촬영, Grok 앱/웹 MP4, Wan/LTX/Hunyuan 로컬 생성 근거"
        />
      </div>

      <div className="scene-detail-section">
        <div className="scene-detail-section-title">채널 품질 검수</div>
        <div className="mode-toggle caption-toggle">
          {VISUAL_VERDICT_OPTIONS.map((option) => {
            const Icon = option.icon;
            const active = (scene.visual_quality_verdict || "") === option.key;
            return (
              <button
                key={option.key || "missing"}
                className={`mode-toggle-btn ${active ? "active" : ""}`}
                onClick={() => actions.editScene(selectedSceneIndex, "visual_quality_verdict", option.key)}
                title={option.title}
              >
                <Icon size={12} />
                {option.label}
              </button>
            );
          })}
        </div>
        <textarea
          className="editable-input"
          value={scene.quality_review_note || ""}
          onChange={(e) => actions.editScene(selectedSceneIndex, "quality_review_note", e.target.value)}
          rows={2}
          placeholder="주 피사체, 자막 가림, 워터마크, 압축 티, 컷 연결 확인"
        />
      </div>

      {scene.scene_num === 1 && (
        <>
          <div className="scene-detail-section">
            <div className="scene-detail-section-title">첫 2초 hook</div>
            <textarea
              className="editable-input"
              value={scene.hook_note || ""}
              onChange={(e) => actions.editScene(selectedSceneIndex, "hook_note", e.target.value)}
              rows={2}
              placeholder="처음 보여줄 시각적 payoff"
            />
          </div>

          <div className="scene-detail-section">
            <div className="scene-detail-section-title">최종 업로드 검수</div>
            <textarea
              className="editable-input"
              value={scene.thumbnail_review_note || ""}
              onChange={(e) => actions.editScene(selectedSceneIndex, "thumbnail_review_note", e.target.value)}
              rows={2}
              placeholder="썸네일/첫 프레임 후보와 선택 이유"
            />
            <textarea
              className="editable-input"
              value={scene.audio_mix_review_note || ""}
              onChange={(e) => actions.editScene(selectedSceneIndex, "audio_mix_review_note", e.target.value)}
              rows={2}
              placeholder="BGM/TTS 볼륨, 클리핑, 자막과 음성 전달 확인"
            />
            <textarea
              className="editable-input"
              value={scene.platform_comparison_note || ""}
              onChange={(e) => actions.editScene(selectedSceneIndex, "platform_comparison_note", e.target.value)}
              rows={2}
              placeholder="YouTube Shorts/롱폼 기준 hook, pacing, AI 티, 부족한 점"
            />
          </div>
        </>
      )}

      {currentSource === "pexels" && (
        <div className="scene-detail-section">
          <button
            className="chip"
            onClick={handleRegenImage}
            disabled={!scene.image_prompt || regeneratingImage}
          >
            {regeneratingImage ? (
              <><RefreshCw size={12} className="spin" /> 생성 중...</>
            ) : currentSource === "pexels" ? (
              <><Search size={12} /> {scene._image_url ? "다른 이미지 검색" : "Pexels 검색"}</>
            ) : (
              <><ImagePlus size={12} /> 이미지 fallback 생성</>
            )}
          </button>
        </div>
      )}

      <div className="scene-detail-section">
        <div className="scene-detail-section-title">자막 위치</div>
        <div className="mode-toggle caption-toggle">
          {CAPTION_PRESETS.map((preset) => (
            <button
              key={preset.key}
              className={`mode-toggle-btn ${captionPreset === preset.key ? "active" : ""}`}
              onClick={() => actions.setSceneCaptionPreset(selectedSceneIndex, preset.key)}
            >
              <Captions size={12} />
              {preset.label}
            </button>
          ))}
        </div>
      </div>

      <div className="scene-detail-section">
        <div className="scene-detail-section-title">나레이션</div>
        {editingNarration ? (
          <textarea
            className="editable-input"
            value={narrationDraft}
            onChange={(e) => setNarrationDraft(e.target.value)}
            onBlur={commitNarration}
            onKeyDown={(e) => { if (e.key === "Escape") setEditingNarration(false); }}
            rows={4}
            autoFocus
          />
        ) : (
          <div className="editable-text" onClick={handleNarrationEdit} style={{ lineHeight: 1.6 }}>
            {scene.narration || <span className="editable-placeholder">나레이션 입력...</span>}
          </div>
        )}
      </div>

      <div className="button-row scene-detail-section">
        {scene._tts_url && (
          playing ? (
            <button className="chip" onClick={stopTts}>
              <Square size={12} /> 정지
            </button>
          ) : (
            <button className="chip" onClick={() => playTts(scene._tts_url!)}>
              <Play size={12} /> TTS 미리듣기
            </button>
          )
        )}
        <button
          className="chip"
          onClick={handleRegenTts}
          disabled={regenerating || !scene.narration}
          title="나레이션 텍스트로 TTS 재생성"
        >
          <RefreshCw size={12} className={regenerating ? "spin" : ""} />
          {regenerating ? "생성 중..." : "TTS 재생성"}
        </button>
      </div>

      <div className="scene-detail-meta">
        <div className="scene-detail-scores">
          <span>감정: {scene.emotion}</span>
          {scene.rank != null && <span>순위: #{scene.rank}</span>}
          <span>소스: {videoPreview ? "video" : imagePreview ? "image" : scene.has_image ? "대기" : "없음"}</span>
        </div>
      </div>

      {scene.display_text && (
        <div className="scene-detail-section">
          <div className="scene-detail-section-title">표시 자막</div>
          <div className="scene-caption-preview">
            {scene.display_text}
          </div>
        </div>
      )}
    </div>
  );
}

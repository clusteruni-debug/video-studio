const BRIDGE_URL = "http://127.0.0.1:5161";

// ── Types ──

export type TemplateType = "community_read" | "news_explainer" | "reddit_translation" | "ranking_list" | "origin_story" | "vs_comparison" | "myth_buster" | "tutorial_steps" | "before_after" | "hot_take" | "authentic_vlog" | "persona_story" | "kculture_fandom" | "podcast_clip" | "longform_deep_dive" | "interview_documentary" | "live_recap";
export type GrokOpenTarget = "worksheet" | "grok" | "both" | "grok-prep-generate" | "observed-post" | "observed-asset" | "observed-asset-runway" | "observed-asset-manual-runway" | "companion-setup" | "companion-guide" | "chrome-extensions";
export type TonePreset = "casual_heyo" | "commentary" | "banmal" | "story" | "formal_soft";
export type GrokAuthProvider = "google" | "x" | "email" | "apple" | "manual";

export interface LiveChannelOperatingTemplate {
  key?: string;
  label?: string;
  platform?: string;
  templateTypes?: string[];
  captionPreset?: Record<string, unknown>;
  safeZone?: Record<string, string>;
  hookTextPosition?: string;
  bgmVoicePolicy?: string;
  cutTransition?: string;
  thumbnailFirstFrameRule?: string;
  sceneCountDurationRule?: string;
  longformExpansion?: string;
}

export interface LiveChannelTemplatesResult {
  ok: boolean;
  templates?: Record<string, LiveChannelOperatingTemplate>;
  templateOrder?: string[];
  error?: string;
}

export interface BridgeHealth {
  bridge: string;
  vectcut: string;
  zero_paid?: Record<string, unknown>;
  provider_policy?: Record<string, string[]>;
  media?: Record<string, MediaAdapterHealth>;
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

export interface MediaAdapterHealth {
  key: string;
  label: string;
  mode: string;
  outputKind: string;
  model: string;
  ready: boolean;
  fallbackAvailable: boolean;
  entryPoint?: string | null;
  commandPreview?: string | null;
  detail: string;
}

export type VisualSource =
  | "upload"
  | "grok"
  | "pexels-video"
  | "wan"
  | "ltx-video"
  | "hunyuan-video"
  | "pexels"
  | "imagen";

export type LocalVideoProvider = "wan" | "ltx-video" | "hunyuan-video";
export type UploadKind = "image" | "video";
export type CaptionPreset = "none" | "center-short" | "top-hook" | "lower-info";
export type VisualQualityVerdict = "pass" | "fail" | "needs-review" | "needs-rework" | "not-ready";

export interface PexelsVideoCandidate {
  id: string;
  url: string;
  width: number;
  height: number;
  duration: number;
  sourceUrl?: string;
  thumbnailUrl?: string;
  author?: string;
  candidateCount?: number;
  selectionMethod?: string;
  selectionKey?: string;
  selectionRationale?: string;
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
  image_source?: string;
  _tts_url?: string | null;
  _image_url?: string | null;
  _upload_preview?: string | null;
  _upload_file?: File | null;
  _upload_kind?: UploadKind | null;
  _upload_name?: string | null;
  _upload_mime?: string | null;
  _server_asset_path?: string | null;
  _server_asset_preview_url?: string | null;
  _server_asset_mime?: string | null;
  _sfx_asset_path?: string | null;
  _sfx_asset_name?: string | null;
  _sfx_asset_mime?: string | null;
  _sfx_asset_title?: string | null;
  _sfx_asset_provider?: string | null;
  _sfx_asset_source_url?: string | null;
  _sfx_asset_source_license?: string | null;
  _sfx_asset_license_url?: string | null;
  _sfx_asset_attribution?: string | null;
  _sfx_asset_kind?: string | null;
  _voiceover_asset_path?: string | null;
  _voiceover_asset_name?: string | null;
  _voiceover_asset_mime?: string | null;
  _voiceover_asset_title?: string | null;
  _voiceover_asset_provider?: string | null;
  _voiceover_asset_source_origin?: string | null;
  _voiceover_asset_source_license?: string | null;
  _voiceover_asset_kind?: string | null;
  _video_url?: string | null;
  _selected_pexels_video?: PexelsVideoCandidate | null;
  _pexels_video_candidates?: PexelsVideoCandidate[];
  caption_preset?: CaptionPreset;
  grok_prompt?: string;
  source_rationale?: string;
  continuity_note?: string;
  hook_note?: string;
  originality_evidence?: string;
  quality_review_note?: string;
  visual_quality_verdict?: VisualQualityVerdict | "";
  thumbnail_review_note?: string;
  audio_mix_review_note?: string;
  platform_comparison_note?: string;
  layout_variant_key?: string;
  layout_variant_label?: string;
  layout_variant_note?: string;
  local_video_provider?: LocalVideoProvider;
  local_generation_status?: string;
  local_generation_detail?: string;
  local_generation_request_path?: string;
  local_generation_prompt_path?: string;
  local_generation_log_path?: string;
  local_generation_command_preview?: string;
  local_command_template_json?: string;
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
  status?: "pending" | "running" | "completed" | "failed";
  completed?: number;
  failed?: number;
  progress?: number;
  total?: number;
  results?: DraftResult[];
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

export interface SearchPexelsVideoResult {
  ok: boolean;
  videos?: PexelsVideoCandidate[];
  video?: PexelsVideoCandidate;
  error?: string;
}

export interface FreeAssetProviderPlan {
  provider: string;
  label?: string;
  kind?: string;
  role?: string;
  officialUrl?: string;
  manualUrl?: string;
  searchUrl?: string;
  requires?: string;
  licenseNote?: string;
  reason?: string;
  proofFields?: string[];
}

export interface FreeAssetLayoutVariant {
  key: string;
  label: string;
  scenePattern?: string;
  captionPlan?: string;
  assetPlan?: string;
}

export interface FreeAssetAcquisitionMethod {
  method: string;
  role?: string;
  freePath?: string;
  fallback?: string;
  proofFields?: string[];
}

export interface FreeAssetProductionRecipe {
  key: string;
  label?: string;
  goal?: string;
  whenToUse?: string;
  steps?: string[];
  freeTools?: string[];
  proofFields?: string[];
  qualityGate?: string;
}

export interface FreeAssetBgmTrack {
  path: string;
  mood: string;
  title?: string;
  provider?: string;
  sourceUrl?: string;
  license?: string;
  provenanceReady?: boolean;
}

export interface FreeAssetBgmPlan {
  recommendedMood?: string;
  templateAudioMood?: string;
  localLibrary?: {
    recommendedMood?: string;
    libraryPath?: string;
    totalTracks?: number;
    tracksWithProvenance?: number;
    tracksMissingProvenance?: number;
    byMood?: Record<string, { total?: number; withProvenance?: number; missingProvenance?: number }>;
    recommendedTracks?: FreeAssetBgmTrack[];
    missingProvenanceSamples?: FreeAssetBgmTrack[];
    status?: string;
    operatorAction?: string;
  };
  freeAlternatives?: FreeAssetProviderPlan[];
  mixRule?: string;
}

export interface FreeAudioSidecarTemplate {
  provider?: string;
  title?: string;
  artist?: string;
  creator?: string;
  sourceUrl?: string;
  sourceLicense?: string;
  license?: string;
  licenseUrl?: string;
  attributionRequired?: boolean;
  attribution?: string;
  mood?: string;
  kind?: string;
  durationSec?: number | null;
  templateFamilies?: string[];
  downloadDate?: string;
  editNotes?: string;
  riskNote?: string;
  operatorOwned?: boolean;
  sourceOrigin?: string;
  speaker?: string;
  recordedAt?: string;
}

export interface FreeAudioImportPayloadTemplate {
  candidateId: string;
  sourcePath: string;
  targetRole: "bgm" | "sfx" | "voiceover";
  mood?: string;
  operatorApproved: boolean;
}

export interface FreeAudioCandidate {
  id: string;
  provider: string;
  kind: string;
  title: string;
  artist?: string;
  sourceUrl: string;
  sourceLicense?: string;
  licenseUrl?: string;
  attributionRequired?: boolean;
  attribution?: string;
  mood?: string;
  templateFamilies?: string[];
  durationSec?: number | null;
  editNotes?: string;
  riskLevel?: "low" | "medium" | "high" | string;
  riskNote?: string;
  matchReason?: "exact" | "fallback-mood" | "template-fallback" | string;
  matchedMood?: string;
  requiresOperatorSelection?: boolean;
  sidecarTemplate?: FreeAudioSidecarTemplate;
  importPayloadTemplate?: FreeAudioImportPayloadTemplate;
}

export interface FreeTemplateAudioVariantPlan {
  key: string;
  label: string;
  captionPlan?: string;
  assetPlan?: string;
  recommendedMood?: string;
  bgmRule?: string;
  sfxRule?: string;
  sourceRoutes?: string[];
}

export interface FreeTemplateAudioPlan {
  templateType: TemplateType | string;
  recommendedMood?: string;
  fallbackMoods?: string[];
  sourceRoutes?: string[];
  bgmRule?: string;
  sfxPolicy?: string;
  layoutVariants?: FreeTemplateAudioVariantPlan[];
  selectedVariant?: FreeTemplateAudioVariantPlan | null;
  avoid?: string[];
  operatorAction?: string;
}

export interface FreeAudioCandidatesResult {
  ok: boolean;
  templateType?: TemplateType;
  variantKey?: string;
  recommendedMood?: string;
  kind?: string;
  includeRisky?: boolean;
  fallbackUsed?: boolean;
  templateAudioPlan?: FreeTemplateAudioPlan;
  candidates?: FreeAudioCandidate[];
  operatorAction?: string;
  error?: string;
}

export interface FreeAudioImportResult {
  ok: boolean;
  asset?: {
    role: "bgm" | "sfx" | "audio";
    path: string;
    sidecarPath: string;
    provider?: string;
    title?: string;
    artist?: string;
    licenseUrl?: string;
    attribution?: string;
    sourceUrl?: string;
    sourceLicense?: string;
    mood?: string;
    kind?: string;
    targetRole?: "bgm" | "sfx" | "voiceover";
    operatorOwned?: boolean;
    importMethod?: string;
    provenanceReady?: boolean;
    operatorAction?: string;
  };
  sidecar?: FreeAudioSidecarTemplate & Record<string, unknown>;
  error?: string;
}

export interface BgmAssetPayload {
  role?: "bgm";
  path: string;
  sidecarPath?: string;
  provider?: string;
  sourceProvider?: string;
  sourceUrl?: string;
  sourceLicense?: string;
  license?: string;
  licenseUrl?: string;
  attribution?: string;
  sourceAttribution?: string;
  sourceLabel?: string;
  title?: string;
  artist?: string;
  mood?: string;
  kind?: string;
  candidateId?: string;
  operatorApproved?: boolean;
  operatorSelected?: boolean;
}

export interface FreeAssetScenePlan {
  sceneId: string;
  title?: string;
  queries: string[];
  preferredSourceOrder: string[];
  layoutVariants?: FreeAssetLayoutVariant[];
  assetSlots: FreeAssetProviderPlan[];
  candidateSearches: FreeAssetProviderPlan[];
  templatePlaybook?: FreeAssetTemplatePlaybook;
  assetProductionRecipes?: FreeAssetProductionRecipe[];
  freeAssetFallbacks?: string[];
  repeatGuard?: {
    distinctKey?: string;
    rule?: string;
  };
  qualityReviewPrompts?: string[];
  avoid?: string[];
}

export interface FreeAssetTemplateAlternative {
  templateType: TemplateType;
  family: string;
  layout: string;
  sourceMix: string;
  preferredSourceOrder: string[];
}

export interface FreeAssetEvidenceSource {
  key: string;
  label: string;
  sourceType?: string;
  url: string;
  appliesTo?: string[];
  operatorUse?: string;
}

export interface FreeAssetTemplatePlaybook {
  templateType: TemplateType;
  family: string;
  pattern?: string;
  layout?: string;
  primaryAssets?: string[];
  freeAssetSubstitutes?: string[];
  qualityGate?: string;
}

export interface FreeAssetSourcingPacket {
  ok: boolean;
  projectId?: string;
  templateType?: TemplateType;
  templateFamily?: string;
  layout?: string;
  layoutVariants?: FreeAssetLayoutVariant[];
  sourceMix?: string;
  audioMood?: string;
  recommendedBgmMood?: string;
  preferredSourceOrder?: string[];
  stockProviderOrder?: string[];
  artifactDir?: string;
  packetPath?: string;
  worksheetPath?: string;
  createdAt?: string;
  freeAssetSources?: FreeAssetProviderPlan[];
  audioSources?: FreeAssetProviderPlan[];
  assetAcquisitionMethods?: FreeAssetAcquisitionMethod[];
  assetProductionRecipes?: FreeAssetProductionRecipe[];
  bgmPlan?: FreeAssetBgmPlan;
  scenes?: FreeAssetScenePlan[];
  templateAlternatives?: FreeAssetTemplateAlternative[];
  evidenceSources?: FreeAssetEvidenceSource[];
  templatePlaybook?: FreeAssetTemplatePlaybook[];
  selectedTemplatePlaybook?: FreeAssetTemplatePlaybook;
  globalRules?: string[];
  koreanYoutubePatterns?: string[];
  error?: string;
}

export interface SceneAssetPayload {
  sceneId: string;
  role: "visual" | "audio" | "sfx";
  fileName: string;
  mimeType?: string;
  base64?: string;
  sourcePath?: string;
  provider?: string;
  sourceProvider?: string;
  sourceUrl?: string;
  sourceLicense?: string;
  license?: string;
  licenseUrl?: string;
  attribution?: string;
  sourceAttribution?: string;
  sourceExternalId?: string;
  sourceLabel?: string;
  sourceOrigin?: string;
  kind?: string;
  operatorOwned?: boolean;
  sourceGenerator?: string;
  sourceGeneratorRequestPath?: string;
  sourceGeneratorPromptPath?: string;
  sourceGeneratorLogPath?: string;
  sourceGeneratorCommand?: string | null;
}

export interface LocalVideoGeneratedAsset extends SceneAssetPayload {
  previewUrl?: string;
  provider?: LocalVideoProvider;
}

export interface LocalVideoFolderImportedAsset extends SceneAssetPayload {
  previewUrl?: string;
  provider?: "local-folder";
  originalPath?: string;
  importMatch?: string;
}

export interface LocalVideoGenerateResult {
  ok: boolean;
  provider?: LocalVideoProvider;
  projectId?: string;
  sceneId?: string;
  adapterStatus?: Record<string, unknown>;
  result?: Record<string, unknown>;
  asset?: LocalVideoGeneratedAsset | null;
  requestPath?: string;
  promptPath?: string;
  logPath?: string;
  commandPreview?: string | null;
  status?: string;
  detail?: string;
  error?: string;
}

export interface LocalVideoFolderImportResult {
  ok: boolean;
  projectId?: string;
  sourceDir?: string;
  packetDir?: string;
  manifestPath?: string;
  importedCount?: number;
  availableMp4Count?: number;
  assets?: LocalVideoFolderImportedAsset[];
  imports?: Array<Record<string, unknown>>;
  error?: string;
}

export interface DraftScenePayload {
  sceneId: string;
  scene_num: number;
  title?: string;
  narration: string;
  display_text: string;
  image_prompt: string;
  image_source?: string;
  emotion?: string;
  duration: number;
  upload_kind?: UploadKind | null;
  caption_preset?: CaptionPreset;
  grok_prompt?: string;
  source_rationale?: string;
  continuity_note?: string;
  hook_note?: string;
  originality_evidence?: string;
  quality_review_note?: string;
  visual_quality_verdict?: VisualQualityVerdict | "";
  thumbnail_review_note?: string;
  audio_mix_review_note?: string;
  platform_comparison_note?: string;
  layout_variant_key?: string;
  layout_variant_label?: string;
  layout_variant_note?: string;
  selected_pexels_video?: PexelsVideoCandidate | null;
  local_video_provider?: LocalVideoProvider;
}

export interface RenderSmokeResult {
  ok: boolean;
  saveResult?: Record<string, unknown>;
  renderResult?: {
    ok: boolean;
    projectId: string;
    outputPath: string;
    manifestPath: string;
    logPath: string;
    qualityReportPath?: string;
    qualityReport?: RenderQualityReport | null;
    ffmpeg?: Record<string, unknown>;
    localMediaSummary?: Record<string, unknown>;
    localMedia?: Record<string, unknown>[];
    warnings?: string[] | null;
  };
  finalizeResult?: PublishPacketResult | null;
  error?: string;
  [key: string]: unknown;
}

export interface PublishPacketResult {
  ok: boolean;
  projectId?: string;
  finalVideoPath?: string;
  finalQualityReportPath?: string;
  publishChecklistPath?: string;
  qualityChecklistPath?: string;
  qualityAuditPath?: string;
  publishPacketPath?: string;
  publishPacketMarkdownPath?: string;
  publishPacket?: {
    decision?: {
      key?: string;
      label?: string;
      reason?: string;
      scope?: string;
      uploadApproval?: boolean;
      sameDayUploadApproval?: boolean;
    };
    decisionScope?: string;
    preUploadBoundary?: string;
    sameDayUploadDecision?: {
      status?: string;
      label?: string;
      reason?: string;
    };
    finalMp4?: string;
    thumbnailCandidates?: {
      firstFrame?: string | null;
      reviewFrames?: string[];
      contactSheet?: string | null;
      rule?: string;
    };
    titleCandidates?: string[];
    description?: string;
    hashtags?: string[];
    operatingTemplate?: LiveChannelOperatingTemplate;
    uploadChecklist?: Array<{ key?: string; label?: string; status?: string; detail?: string; source?: string }>;
    sceneReview?: Array<Record<string, unknown>>;
    shortcomings?: string[];
    nextImprovementActions?: string[];
  };
  blockedQualityAuditPath?: string;
  qualityAudit?: {
    summary?: {
      passed?: number;
      total?: number;
      checksNeeded?: string[];
      readyForUpload?: boolean;
      channelReady?: boolean;
      grokOrLocalHeroReady?: boolean;
      originalHeroReady?: boolean;
      benchmarkGap?: string;
    };
    checklist?: Array<{
      key?: string;
      label?: string;
      status?: string;
      detail?: string;
      source?: string;
    }>;
    [key: string]: unknown;
  };
  contactSheetPath?: string;
  reviewFramePaths?: string[];
  audioLevel?: {
    ok?: boolean;
    meanVolumeDb?: number | null;
    maxVolumeDb?: number | null;
    error?: string;
  };
  renderManifestPath?: string;
  publishReadiness?: PublishReadiness;
  channelReadiness?: ChannelReadiness;
  uploadReview?: UploadReview;
  topTierReadiness?: TopTierReadiness;
  channelReadyRequired?: boolean;
  topTierRequired?: boolean;
  requiredFixes?: string[];
  recommendedFixes?: string[];
  sourcePipelineStatus?: SourcePipelineStatus;
  nextActions?: PipelineNextAction[];
  error?: string;
}

export interface PipelineNextAction {
  key?: string;
  priority?: "required" | "recommended" | "next" | string;
  label?: string;
  detail?: string;
  operatorAction?: string;
}

export interface StockCandidateCurationEvidence {
  recorded?: boolean;
  ready?: boolean | null;
  status?: string;
  detail?: string;
  scenes?: string[];
  readyScenes?: string[];
  missingScenes?: string[];
  missingCandidateCountScenes?: string[];
  missingCreatorScenes?: string[];
  missingSelectionSummaryScenes?: string[];
  issuesByScene?: Record<string, string[]>;
}

export interface PexelsReplacementResearchCandidate {
  sceneId?: string;
  provider?: string;
  sourceOrigin?: string;
  candidateFileName?: string;
  pexelsId?: string;
  creator?: string;
  sourcePageUrl?: string;
  downloadUrl?: string;
  localPath?: string;
  localFileExists?: boolean;
  contactSheetPath?: string;
  contactSheetExists?: boolean;
  reframeSmokePath?: string;
  reframeSmokeExists?: boolean;
  reframeSmokeReviewPath?: string;
  reframeSmokeReviewExists?: boolean;
  reframeSmokeVerdict?: string;
  previousLowerEmptyAreaConcernCorrected?: boolean;
  ffprobe?: Record<string, unknown>;
  verdict?: string;
  uploadReady?: boolean;
  requiresScriptRewrite?: boolean;
  requiresPhoneFirstFrameReview?: boolean;
  requiresCropReframeTest?: boolean;
  reason?: string;
}

export interface PexelsReplacementResearch {
  available?: boolean;
  projectId?: string;
  status?: string;
  reviewPath?: string;
  downloadsPath?: string;
  directPexelsUrlOnly?: boolean;
  chromeDownloadUi?: boolean;
  grokDownloadSaveExport?: boolean;
  notFreshGrokProof?: boolean;
  notPublishPacket?: boolean;
  notUploadReadyEvidence?: boolean;
  uploadReady?: boolean;
  doesNotSatisfy?: string[];
  totalCandidates?: number;
  conditionalFallbackCandidates?: number;
  failedDirectUseCandidates?: number;
  uploadReadyCandidates?: number;
  videoOnlyNoAudioCandidates?: number;
  scenes?: string[];
  candidates?: PexelsReplacementResearchCandidate[];
  operatorAction?: string;
}

export interface PexelsExpandedSearchCandidate {
  sceneId?: string;
  provider?: string;
  pexelsId?: string;
  query?: string;
  creator?: string;
  sourcePageUrl?: string;
  downloadUrl?: string;
  thumbnailUrl?: string;
  durationSeconds?: number;
  width?: number;
  height?: number;
  localPath?: string;
  localFileExists?: boolean;
  contactSheetPath?: string;
  contactSheetExists?: boolean;
  verdict?: string;
  uploadReady?: boolean;
  requiresScriptRewrite?: boolean;
  requiresPhoneFirstFrameReview?: boolean;
  recommendedUse?: string;
  reason?: string;
}

export interface PexelsExpandedSearch {
  available?: boolean;
  projectId?: string;
  status?: string;
  reviewDir?: string;
  reviewPath?: string;
  searchResultPath?: string;
  sceneIds?: string[];
  candidateCount?: number;
  reviewedCandidateCount?: number;
  rewriteCandidateCount?: number;
  rejectedCandidateCount?: number;
  uploadReadyCandidates?: number;
  uploadReady?: boolean;
  doesNotSatisfy?: string[];
  candidates?: PexelsExpandedSearchCandidate[];
  operatorAction?: string;
}

export interface SourceRecoveryPlanScene {
  sceneId?: string;
  status?: string;
  recommendedLane?: string;
  directRenderAllowed?: boolean;
  uploadReady?: boolean;
  blocksRender?: boolean;
  blocksFreshSourceProof?: boolean;
  renderBlockers?: string[];
  freshSourceProofBlockers?: string[];
  renderBlockerCount?: number;
  freshSourceProofBlockerCount?: number;
  directImportRunway?: {
    available?: boolean;
    status?: string;
    sceneId?: string;
    projectId?: string;
    expectedFileName?: string;
    prompt?: {
      source?: string;
      promptPath?: string;
      promptText?: string;
      promptPreview?: string;
      copyLabel?: string;
    };
    uploadEndpoint?: string;
    proofMonitorUrl?: string;
    observedPostUrl?: string;
    observedPostDownloadScriptUrl?: string;
    requiresOperatorGeneration?: boolean;
    forbiddenActions?: string[];
    allowedRoutes?: string[];
    operatorAction?: string;
  };
  failCategories?: string[];
  selectedFileName?: string;
  localCandidateCount?: number;
  readyLocalCandidateCount?: number;
  unreviewedLocalCandidateCount?: number;
  unreviewedLocalCandidates?: string[];
  selectedStockRewriteAvailable?: boolean;
  pexelsCandidateFileName?: string;
  pexelsVerdict?: string;
  pexelsRequiresScriptRewrite?: boolean;
  pexelsReframeSmokeVerdict?: string;
  pexelsLowerFrameConcernCorrected?: boolean;
  pexelsUploadReady?: boolean;
  expandedPexelsSearch?: PexelsExpandedSearch | null;
  localReview?: LocalCandidateReviewScene | null;
  operatorAction?: string;
}

export interface LocalCandidateReviewScene {
  sceneId?: string;
  status?: string;
  verdict?: string;
  uploadReady?: boolean;
  reviewedAllLocalCandidates?: boolean;
  reviewedCandidateCount?: number;
  selectedFileName?: string;
  contactSheetPaths?: string[];
  failCategories?: string[];
  operatorAction?: string;
  notes?: string;
}

export interface LocalCandidateReviewEvidence {
  available?: boolean;
  projectId?: string;
  status?: string;
  structured?: boolean;
  reviewPath?: string;
  markdownPath?: string;
  reviewedAt?: string;
  uploadReady?: boolean;
  reviewedScenes?: number;
  uploadReadyScenes?: number;
  failedScenes?: number;
  conditionalRewriteScenes?: number;
  doesNotSatisfy?: string[];
  scenes?: LocalCandidateReviewScene[];
  operatorAction?: string;
}

export interface SourceRecoveryPlan {
  available?: boolean;
  projectId?: string;
  status?: string;
  uploadReady?: boolean;
  directRenderAllowed?: boolean;
  blockedByNativeDownloadPrompt?: boolean;
  totalScenes?: number;
  localReviewScenes?: number;
  selectedStockRewriteAvailableScenes?: number;
  regenerateDirectImportScenes?: number;
  expandedPexelsSearchScenes?: number;
  directImportRunwayScenes?: number;
  renderBlockerCount?: number;
  freshSourceProofBlockerCount?: number;
  scenesBlockingRender?: string[];
  scenesBlockingFreshSourceProof?: string[];
  latestLocalReview?: LocalCandidateReviewEvidence;
  latestExpandedPexelsSearch?: PexelsExpandedSearch;
  reviewedLocalCandidateScenes?: number;
  failedLocalCandidateScenes?: number;
  conditionalRewriteLocalCandidateScenes?: number;
  scenes?: SourceRecoveryPlanScene[];
  operatorAction?: string;
}

export interface SourceRecoveryExecutionChecklistItem {
  sceneId?: string;
  status?: string;
  recommendedLane?: string;
  blocksRender?: boolean;
  blocksFreshSourceProof?: boolean;
  selectedFileName?: string;
  failCategories?: string[];
  nextRequiredAction?: string;
  operatorAction?: string;
  acceptanceCriteria?: string[];
  recoveryInputs?: {
    localReviewStatus?: string;
    localReviewUploadReady?: boolean;
    localReviewContactSheets?: string[];
    selectedStockCandidateFileName?: string;
    selectedStockVerdict?: string;
    selectedStockRequiresScriptRewrite?: boolean;
    expandedPexelsStatus?: string;
    expandedPexelsReviewPath?: string;
    expandedPexelsRewriteCandidates?: number;
    directImportStatus?: string;
    directImportExpectedFileName?: string;
    directImportUploadEndpoint?: string;
    directImportProofMonitorUrl?: string;
    observedPostUrl?: string;
    observedPostDownloadScriptUrl?: string;
    recoveryPromptSource?: string;
    recoveryPromptPreview?: string;
    forbiddenActions?: string[];
    allowedRoutes?: string[];
  };
}

export interface SourceRecoveryAcceptanceSceneStatus {
  sceneId?: string;
  status?: string;
  accepted?: boolean;
  acceptanceStatus?: string;
  recommendedLane?: string;
  acceptedReplacementFileName?: string;
  acceptedReplacementPath?: string;
  acceptedReplacementPathCheck?: {
    ok?: boolean;
    path?: string;
    reason?: string;
    issues?: string[];
    actualSha256?: string;
    expectedSha256?: string;
    fileNameCheck?: {
      ok?: boolean;
      expectedFileName?: string;
      actualFileName?: string;
      issue?: string;
    };
    videoCheck?: {
      ok?: boolean;
      path?: string;
      issues?: string[];
      ffprobe?: {
        ok?: boolean;
        width?: number;
        height?: number;
        frameRate?: number;
        durationSeconds?: number;
        hasAudio?: boolean;
        specReady?: boolean;
        error?: string;
      };
    };
  };
  reviewerId?: string;
  acceptedAt?: string;
  acceptedAtCheck?: {
    ok?: boolean;
    value?: string;
    timezoneRequired?: boolean;
    timezoneProvided?: boolean;
    issues?: string[];
  };
  missingFields?: string[];
  requiredAcceptanceFields?: string[];
  blocksRender?: boolean;
  blocksFreshSourceProof?: boolean;
  proofReady?: boolean;
}

export interface SourceRecoveryAcceptanceStatus {
  available?: boolean;
  projectId?: string;
  status?: string;
  requiredArtifactPath?: string;
  templatePath?: string;
  artifactPath?: string;
  templateOnly?: boolean;
  proofArtifactCreated?: boolean;
  freshSourceProofCreated?: boolean;
  goalComplete?: boolean;
  blocksRender?: boolean;
  blocksFreshSourceProof?: boolean;
  acceptedSceneCount?: number;
  incompleteSceneCount?: number;
  totalScenes?: number;
  missingFieldsByScene?: Record<string, string[]>;
  scenes?: SourceRecoveryAcceptanceSceneStatus[];
  operatorAction?: string;
  goalBoundary?: string;
}

export interface SourcePipelineStatus {
  paidApiPolicy?: {
    paidAiApiAllowed?: boolean;
    disallowedByDefault?: string[];
    allowedAutomation?: string;
  };
  grok?: {
    mode?: string;
    apiIntegration?: boolean;
    nextAction?: string;
    nativeDownloadPromptPolicy?: {
      status?: string;
      allowedForCodexAutomation?: boolean;
      allowedForGoalCompletion?: boolean;
      blocksIfPromptAppears?: boolean;
      forbiddenActions?: string[];
      allowedAlternatives?: string[];
      reason?: string;
      operatorAction?: string;
    };
    proofMonitorUrl?: string;
    observedPostUrl?: string;
    observedPostDownloadScriptUrl?: string;
    handoffSelection?: {
      selectedProjectId?: string;
      selectedScore?: number;
      selectedReasons?: string[];
      latestByMtimeProjectId?: string;
      latestByMtimeScore?: number;
      preferredProductionHandoff?: boolean;
      nonSelectedLatestReason?: string;
      candidates?: Array<{
        projectId?: string;
        productionScore?: number;
        sceneCount?: number;
        qualityGateRequired?: boolean;
        grokMainSourceRequired?: boolean;
        promptNeedsRewriteScenes?: number;
      }>;
    };
    observedPostAction?: string;
    latestHandoff?: {
      available?: boolean;
      projectId?: string;
      createdAt?: string;
      status?: string;
      operatorDecision?: {
        status?: string;
        label?: string;
        detail?: string;
        nextAction?: string;
      };
      blocksOperatingGoal?: boolean;
      totalScenes?: number;
      importedScenes?: number;
      acceptedScenes?: number;
      rejectedScenes?: number;
      missingScenes?: string[];
      importedSceneIds?: string[];
      acceptedSceneIds?: string[];
      rejectedSceneIds?: string[];
      liveFailCategories?: string[];
      replacementBacklog?: Array<{
        sceneId?: string;
        expectedFileName?: string;
        selectedFileName?: string;
        status?: string;
        failCategories?: string[];
        liveFailSummary?: string;
        qualityReviewNote?: string;
        operatorNote?: string;
        retryAttempt?: number;
        nextRetryPrompt?: string;
        localCandidateCount?: number;
        readyLocalCandidateCount?: number;
        unreviewedLocalCandidateCount?: number;
        unreviewedLocalCandidates?: string[];
        candidatePool?: {
          totalCandidates?: number;
          readyCandidates?: number;
          unreviewedReplacementCandidates?: string[];
          unreviewedReplacementCount?: number;
          selectedFileName?: string;
          candidates?: Array<Record<string, unknown>>;
          operatorAction?: string;
        };
        operatorAction?: string;
      }>;
      nextMissingSceneId?: string;
      scenes?: Array<{
        sceneId?: string;
        expectedFileName?: string;
        imported?: boolean;
        accepted?: boolean;
        promptQualityStatus?: string;
        review?: {
          status?: string;
          accepted?: boolean;
          visualQualityVerdict?: string;
          failCategories?: string[];
          qualityReviewNote?: string;
          captionLayoutReviewNote?: string;
          operatorNote?: string;
          sourceRationale?: string;
          selectedCandidateSummary?: string;
          selectedFileName?: string;
          retryAttempt?: number;
          nextRetryPrompt?: string;
          sourceProvenanceConfirmed?: boolean;
          sourceProvenanceStatus?: string;
          firstTwoSecondHook?: boolean;
          artifactFree?: boolean;
          captionSafe?: boolean;
          continuityOk?: boolean;
          shotLockMatch?: boolean;
          sceneAssemblyOk?: boolean;
          liveFailSummary?: string;
        };
        candidatePool?: {
          totalCandidates?: number;
          readyCandidates?: number;
          unreviewedReplacementCandidates?: string[];
          unreviewedReplacementCount?: number;
          selectedFileName?: string;
          candidates?: Array<Record<string, unknown>>;
          operatorAction?: string;
        };
        importPreflight?: {
          sourcePath?: string;
          exists?: boolean;
          sizeBytes?: number;
          modifiedAt?: string;
          freshEnough?: boolean;
          usableVideoReady?: boolean;
          readyForReview?: boolean;
          status?: string;
          detail?: string;
          ffprobe?: Record<string, unknown>;
        };
        browserGeneration?: {
          sceneId?: string;
          generated?: boolean;
          postUrl?: string;
          shareUrl?: string;
          observedAt?: string;
          expectedFileName?: string;
          downloadStatus?: string;
          importedNativeMp4?: boolean;
        };
      }>;
      importPreflight?: {
        totalScenes?: number;
        presentScenes?: number;
        readyScenes?: number;
        missingScenes?: string[];
        staleScenes?: string[];
        invalidScenes?: string[];
        needsImportScenes?: string[];
        nextSceneId?: string;
        readyForReview?: boolean;
        operatorAction?: string;
      };
      importPreflightSummary?: {
        totalScenes?: number;
        presentScenes?: number;
        readyScenes?: number;
        missingScenes?: string[];
        staleScenes?: string[];
        invalidScenes?: string[];
        needsImportScenes?: string[];
        nextSceneId?: string;
        readyForReview?: boolean;
        operatorAction?: string;
      };
      browserGenerationProof?: {
        artifactPath?: string;
        exists?: boolean;
        status?: string;
        generatedScenes?: number;
        generatedSceneIds?: string[];
        missingSceneIds?: string[];
        readyForImport?: boolean;
        proofOnly?: boolean;
        doesNotSatisfyFreshSourceProof?: boolean;
        detail?: string;
        operatorAction?: string;
        downloadStatus?: string;
      };
      downloadFreshness?: {
        downloadDir?: string;
        freshCandidateCount?: number;
        excludedOldCandidateCount?: number;
        newestFreshCandidateAt?: string;
        newestExcludedOldCandidateAt?: string;
        freshnessPolicy?: string;
      };
      worksheetUrl?: string;
      productionQueueUrl?: string;
      reviewPacketUrl?: string;
      freshSourceIntakeTemplatePath?: string;
      freshSourceIntakeUrl?: string;
      statusUrl?: string;
      operatorAction?: string;
    };
    companionDirectImport?: {
      available?: boolean;
      operatorReady?: boolean;
      setupRequired?: boolean;
      installedInExistingProfile?: boolean;
      uploadEndpointDriven?: boolean;
      avoidsChromeDownloadPrompt?: boolean;
      sourceKind?: string;
      qualityNote?: string;
      fallback?: string;
      operatorAction?: string;
      chromeProfile?: {
        profileDir?: string | null;
        profileDetected?: boolean;
        loadUnpackedPath?: string;
        companionInstalled?: boolean;
        codexExtensionInstalled?: boolean;
        recognizedExtensions?: Array<{
          id?: string;
          name?: string;
          defaultTitle?: string;
          path?: string;
          isVideoStudioCompanion?: boolean;
          isCodexExtension?: boolean;
        }>;
        remoteDebuggingPort?: number;
        remoteDebuggingListening?: boolean;
        operatorReady?: boolean;
        setupRequired?: boolean;
        note?: string;
      };
    };
    bookmarkletDirectImport?: {
      available?: boolean;
      operatorReady?: boolean;
      setupRequired?: boolean;
      uploadEndpointDriven?: boolean;
      avoidsChromeDownloadPrompt?: boolean;
      observedPostUrl?: string;
      observedPostDownloadScriptUrl?: string;
      sourceKinds?: string[];
      qualityNote?: string;
      operatorAction?: string;
    };
    dashboardControls?: string[];
  };
  localVideo?: {
    providers?: Record<string, MediaAdapterHealth>;
    anyReady?: boolean;
    nextAction?: string;
  };
  pexels?: {
    videoSearchReady?: boolean;
    role?: string;
    candidateCuration?: StockCandidateCurationEvidence;
    replacementResearch?: PexelsReplacementResearch;
    expandedSearch?: PexelsExpandedSearch;
    nextAction?: string;
  };
  sourceRecoveryPlan?: SourceRecoveryPlan;
  sourceRecoveryAcceptance?: SourceRecoveryAcceptanceStatus;
  currentEvidence?: Record<string, unknown>;
}

export interface FinalVideoLibraryPacket {
  projectId: string;
  packetDir: string;
  updatedAt?: string;
  finalVideoPath?: string | null;
  qualityAuditPath?: string | null;
  qualityReportPath?: string | null;
  publishPacketPath?: string | null;
  publishPacketMarkdownPath?: string | null;
  hasFinalMp4: boolean;
  hasQualityAudit: boolean;
  hasPublishPacket?: boolean;
  publishPacketAudit?: {
    ready?: boolean;
    status?: "ready" | "missing" | "unreadable" | "missing-fields" | string;
    requiredFields?: string[];
    presentFields?: string[];
    missingFields?: string[];
    operatorAction?: string;
  };
  ffprobe?: {
    ok?: boolean;
    width?: number;
    height?: number;
    frameRate?: number | null;
    durationSeconds?: number | null;
    hasAudio?: boolean;
    specReady?: boolean;
    error?: string;
  };
  summary: {
    readyForUpload?: boolean;
    uploadReady?: boolean;
    channelReady?: boolean;
    topTierReady?: boolean;
    grokOrLocalHeroReady?: boolean;
    originalHeroReady?: boolean;
    stockCandidateCurationRecorded?: boolean;
    stockCandidateCurationReady?: boolean | null;
    stockCandidateCurationStatus?: string;
    stockCandidateCurationScenes?: string[];
    stockCandidateCurationReadyScenes?: string[];
    missingStockCandidateCurationScenes?: string[];
    stockCandidateCurationIssuesByScene?: Record<string, string[]>;
    publishStatus?: string;
    publishPacketContentReady?: boolean;
    publishPacketStatus?: string;
    missingPublishPacketFields?: string[];
    channelStatus?: string;
    uploadStatus?: string;
    benchmarkGap?: string;
    nextActionKeys?: string[];
  };
  nextActions?: PipelineNextAction[];
}

export interface QualityGatePhaseState {
  phaseKey?: string;
  status?: string;
  blocking?: boolean;
  detail?: string;
  source?: string;
  checkCount?: number;
  statusCounts?: Record<string, number>;
}

export interface QualityGateSystem {
  schema?: string;
  systemVersion?: string;
  surface?: string;
  status?: string;
  blockingPhaseKey?: string;
  phaseStates?: QualityGatePhaseState[];
  contractSummary?: {
    requiredContractCount?: number;
    requiredContractKeys?: string[];
  };
  renderQualitySummary?: {
    checkCount?: number;
    failedOrMissingKeys?: string[];
    warnKeys?: string[];
  };
  finalReadinessSummary?: {
    gateCount?: number;
    blockingGateKeys?: string[];
    goalComplete?: boolean;
    preUploadReady?: boolean;
  };
  qualityIterationSummary?: {
    iterationCount?: number;
    nextRequiredActionStatus?: string;
    nextRequiredActionSummary?: string;
    latestIterationId?: string;
    latestStage?: string;
    latestStatus?: string;
    changedLever?: string[];
    observedFailure?: string;
    nextMutation?: Record<string, unknown>;
    appliedMutation?: Record<string, unknown>;
    evidencePaths?: string[];
    requiresMutationResolution?: boolean;
  };
  [key: string]: unknown;
}

export interface GoalReadinessRequirement {
  key?: string;
  label?: string;
  status?: "pass" | "partial" | "missing" | "complete" | "incomplete" | string;
  evidence?: string;
  missing?: string[];
}

export interface GoalRunwayChecklistItem {
  key?: string;
  label?: string;
  status?: "pass" | "edit" | "rerender" | "missing" | "fail" | string;
  detail?: string;
  nextAction?: string;
  blocksTodayUpload?: boolean;
  blocksOperatingGoal?: boolean;
}

export interface GoalRunwayChecklistSummary {
  readyForTodayUpload?: boolean;
  readyForOperatingGoal?: boolean;
  primaryBlockerKey?: string;
  primaryBlockerLabel?: string;
  primaryBlockerDetail?: string;
  nextAction?: string;
}

export interface GoalReadinessAudit {
  goalComplete?: boolean;
  overallStatus?: string;
  operatorDecision?: {
    status?: "upload" | "edit" | "rerender" | string;
    label?: string;
    detail?: string;
    nextAction?: string;
  };
  preUploadDecision?: {
    status?: "upload" | "edit" | "rerender" | string;
    label?: string;
    detail?: string;
    nextAction?: string;
  };
  preUploadReady?: boolean;
  preUploadBoundary?: string;
  operatingRunwayChecklist?: GoalRunwayChecklistItem[];
  runwayChecklistSummary?: GoalRunwayChecklistSummary;
  artifactGateComplete?: boolean;
  artifactGateStatus?: string;
  artifactRemainingGaps?: string[];
  operatingSystemComplete?: boolean;
  operatingSystemRequirements?: GoalReadinessRequirement[];
  operatingSystemRemainingGaps?: string[];
  artifactReady?: boolean;
  topTierPacketCount?: number;
  freshSourceBatchProven?: boolean;
  freshSourceRepeatability?: {
    recorded?: boolean;
    ready?: boolean;
    status?: "pass" | "missing" | "needs-proof" | "summary-only" | "fail" | string;
    artifactPath?: string;
    templateArtifactPath?: string;
    template?: Record<string, unknown>;
    requiredFields?: string[];
    missingFields?: string[];
    failedFields?: string[];
    legacySummaryReady?: boolean;
    sourceFlow?: string;
    topic?: string;
    handoffProjectId?: string;
    renderedProjectId?: string;
    evidenceArtifactPaths?: Record<string, string>;
    evidenceArtifactChecks?: Record<string, unknown>;
    evidenceDigestChecks?: Record<string, unknown>;
    finalVideoDigestCheck?: Record<string, unknown>;
    recordedAtCheck?: Record<string, unknown>;
    detail?: string;
    operatorAction?: string;
  };
  phoneSizedHumanReviewReady?: boolean;
  phoneSizedHumanReview?: {
    recorded?: boolean;
    ready?: boolean;
    status?: "pass" | "missing" | "needs-review" | "summary-only" | "fail" | string;
    artifactPath?: string;
    templateArtifactPath?: string;
    template?: Record<string, unknown>;
    requiredFields?: string[];
    missingFields?: string[];
    failedFields?: string[];
    reviewerDecision?: string;
    legacySummaryReady?: boolean;
    evidenceArtifactPaths?: Record<string, string>;
    evidenceArtifactChecks?: Record<string, unknown>;
    evidenceDigestChecks?: Record<string, unknown>;
    finalVideoDigestCheck?: Record<string, unknown>;
    reviewedAtCheck?: Record<string, unknown>;
    deviceViewportCheck?: Record<string, unknown>;
    detail?: string;
    operatorAction?: string;
  };
  platformAnalyticsRecorded?: boolean;
  platformAnalytics?: {
    recorded?: boolean;
    ready?: boolean;
    status?: "recorded" | "missing" | "needs-analytics" | "summary-only" | "fail" | string;
    artifactPath?: string;
    templateArtifactPath?: string;
    template?: Record<string, unknown>;
    requiredFields?: string[];
    missingFields?: string[];
    failedFields?: string[];
    decision?: string;
    legacySummaryReady?: boolean;
    evidenceArtifactPaths?: Record<string, string>;
    evidenceArtifactChecks?: Record<string, unknown>;
    finalVideoDigestCheck?: Record<string, unknown>;
    snapshotDigestCheck?: Record<string, unknown>;
    sampleWindowCheck?: Record<string, unknown>;
    nextImprovementActionCheck?: Record<string, unknown>;
    detail?: string;
    operatorAction?: string;
  };
  liveGrokDirectImportProven?: boolean;
  proofMonitorUrl?: string;
  observedPostUrl?: string;
  requirements?: GoalReadinessRequirement[];
  remainingGaps?: string[];
  completionPolicy?: string;
  gateSystem?: QualityGateSystem;
}

export interface FinalVideoLibraryAuditResult {
  ok: boolean;
  root?: string;
  scanned?: number;
  counts?: {
    withMp4?: number;
    withQualityAudit?: number;
    withPublishPacket?: number;
    withPublishPacketContentReady?: number;
    uploadReady?: number;
    channelReady?: number;
    topTierReady?: number;
    missingQualityAudit?: number;
    missingPublishPacketContent?: number;
  };
  bestPacket?: FinalVideoLibraryPacket | null;
  sourcePipelineStatus?: SourcePipelineStatus;
  goalReadiness?: GoalReadinessAudit;
  gateSystem?: QualityGateSystem;
  packets?: FinalVideoLibraryPacket[];
  error?: string;
}

export interface EvidenceTemplateMaterializeItem {
  kind?: string;
  written?: boolean;
  path?: string;
  proofArtifactPath?: string;
  proofArtifactExists?: boolean;
  proofArtifactCreated?: boolean;
  templateOnly?: boolean;
  doNotSubmitAsProof?: boolean;
  error?: string;
}

export interface EvidenceTemplateMaterializeResult {
  ok: boolean;
  projectId?: string;
  packetDir?: string;
  templates?: {
    freshSourceRepeatability?: EvidenceTemplateMaterializeItem;
    phoneSizedHumanReview?: EvidenceTemplateMaterializeItem;
    platformAnalytics?: EvidenceTemplateMaterializeItem;
  };
  proofArtifactsCreated?: boolean;
  goalComplete?: boolean;
  goalBoundary?: string;
  error?: string;
}

export interface FinalLibraryDashboardSmokeResult {
  ok: boolean;
  status?: string;
  projectId?: string;
  path?: string;
  sha256?: string;
  issues?: string[];
  smoke?: Record<string, unknown>;
  freshSourceTemplate?: EvidenceTemplateMaterializeItem;
  proofArtifactsCreated?: boolean;
  freshSourceProofCreated?: boolean;
  goalComplete?: boolean;
  goalBoundary?: string;
  error?: string;
}

export interface FinalLibraryPhoneReviewEvidenceResult {
  ok: boolean;
  status?: string;
  projectId?: string;
  packetDir?: string;
  artifactPaths?: Record<string, string>;
  artifactChecks?: Record<string, unknown>;
  pendingFields?: string[];
  issues?: string[];
  phoneTemplate?: EvidenceTemplateMaterializeItem;
  proofArtifactsCreated?: boolean;
  phoneReviewProofCreated?: boolean;
  goalComplete?: boolean;
  goalBoundary?: string;
  error?: string;
}

export interface FinalLibraryFreshSourceEvidenceResult {
  ok: boolean;
  status?: string;
  projectId?: string;
  packetDir?: string;
  artifactPaths?: Record<string, string>;
  sceneCount?: number;
  candidateReadySceneCount?: number;
  candidateReadySceneIds?: string[];
  reviewRequiredSceneCount?: number;
  acceptedSceneCount?: number;
  rejectedSceneCount?: number;
  operatorAcceptedSceneCount?: number;
  freshSourceProofReadySceneCount?: number;
  proofBlockerCount?: number;
  scenesWithProofBlockers?: string[];
  sourceRecoveryAcceptanceStatus?: SourceRecoveryAcceptanceStatus;
  sourceRecoveryAcceptanceBlockerCount?: number;
  freshSourceProofBlockedBySourceRecoveryAcceptance?: boolean;
  freshSourceTemplate?: EvidenceTemplateMaterializeItem;
  proofArtifactsCreated?: boolean;
  freshSourceProofCreated?: boolean;
  goalComplete?: boolean;
  goalBoundary?: string;
  error?: string;
}

export interface FreshSourceIntakeMaterializeResult {
  ok: boolean;
  projectId?: string;
  path?: string;
  templateOnly?: boolean;
  proofArtifactCreated?: boolean;
  freshSourceProofCreated?: boolean;
  goalComplete?: boolean;
  operatorDecision?: {
    status?: string;
    label?: string;
    detail?: string;
    nextAction?: string;
  };
  missingScenes?: string[];
  rejectedScenes?: string[];
  liveFailCategories?: string[];
  sourceRecoveryPlan?: SourceRecoveryPlan;
  sourceRecoveryExecutionChecklist?: SourceRecoveryExecutionChecklistItem[];
  sourceRecoveryBoundary?: string;
  replacementBacklog?: Array<{
    sceneId?: string;
    expectedFileName?: string;
    selectedFileName?: string;
    status?: string;
    failCategories?: string[];
    liveFailSummary?: string;
    qualityReviewNote?: string;
    operatorNote?: string;
    retryAttempt?: number;
    nextRetryPrompt?: string;
    operatorAction?: string;
  }>;
  downloadFreshness?: SourcePipelineStatus["grok"] extends infer GrokStatus
    ? GrokStatus extends { latestHandoff?: infer Handoff }
      ? Handoff extends { downloadFreshness?: infer Freshness }
        ? Freshness
        : Record<string, unknown>
      : Record<string, unknown>
    : Record<string, unknown>;
  packet?: {
    schema?: string;
    projectId?: string;
    handoffStatus?: string;
    packetPath?: string;
    templateOnly?: boolean;
    doNotSubmitAsProof?: boolean;
    proofArtifactCreated?: boolean;
    freshSourceProofCreated?: boolean;
    goalComplete?: boolean;
    missingScenes?: string[];
    sourceRecoveryPlan?: SourceRecoveryPlan;
    sourceRecoveryExecutionChecklist?: SourceRecoveryExecutionChecklistItem[];
    sourceRecoveryBoundary?: string;
    importPreflight?: SourcePipelineStatus["grok"] extends infer GrokStatus
      ? GrokStatus extends { latestHandoff?: infer Handoff }
        ? Handoff extends { importPreflight?: infer ImportPreflight }
          ? ImportPreflight
          : Record<string, unknown>
        : Record<string, unknown>
      : Record<string, unknown>;
    requiredScenes?: Array<{
      sceneId?: string;
      expectedFileName?: string;
      imported?: boolean;
      accepted?: boolean;
      promptQualityStatus?: string;
      importPreflight?: Record<string, unknown>;
      review?: Record<string, unknown>;
      candidatePool?: Record<string, unknown>;
      operatorAction?: string;
    }>;
    operatorChecklist?: string[];
    doesNotSatisfy?: string[];
    goalBoundary?: string;
  };
  goalBoundary?: string;
  error?: string;
}

export interface SourceRecoveryAcceptanceMaterializeResult {
  ok: boolean;
  status?: string;
  projectId?: string;
  path?: string;
  templateOnly?: boolean;
  proofArtifactCreated?: boolean;
  freshSourceProofCreated?: boolean;
  goalComplete?: boolean;
  directRenderAllowed?: boolean;
  uploadReady?: boolean;
  sourceRecoveryStatus?: string;
  sourceRecoveryScenes?: number;
  renderBlockerCount?: number;
  freshSourceProofBlockerCount?: number;
  scenesBlockingRender?: string[];
  scenesBlockingFreshSourceProof?: string[];
  sourceRecoveryPlan?: SourceRecoveryPlan;
  sourceRecoveryExecutionChecklist?: SourceRecoveryExecutionChecklistItem[];
  acceptanceScenes?: Array<{
    sceneId?: string;
    status?: string;
    acceptanceStatus?: string;
    recommendedLane?: string;
    selectedFileName?: string;
    blocksRender?: boolean;
    blocksFreshSourceProof?: boolean;
    directRenderAllowed?: boolean;
    uploadReady?: boolean;
    renderBlockers?: string[];
    freshSourceProofBlockers?: string[];
    renderBlockerCount?: number;
    freshSourceProofBlockerCount?: number;
    failCategories?: string[];
    acceptanceCriteria?: string[];
    requiredAcceptanceFields?: string[];
    operatorDecisionTemplate?: Record<string, unknown>;
    recoveryInputs?: SourceRecoveryExecutionChecklistItem["recoveryInputs"];
    localReview?: Record<string, unknown>;
    selectedStock?: Record<string, unknown>;
    expandedPexelsSearch?: Record<string, unknown>;
    directImportRunway?: Record<string, unknown>;
    operatorAction?: string;
    doesNotSatisfy?: string[];
  }>;
  sourceRecoveryAcceptanceStatus?: SourceRecoveryAcceptanceStatus;
  sourceRecoveryBoundary?: string;
  doesNotSatisfy?: string[];
  packet?: Record<string, unknown>;
  goalBoundary?: string;
  error?: string;
}

export interface SourceRecoveryRerenderPlanResult {
  ok: boolean;
  status?: string;
  projectId?: string;
  path?: string;
  templateOnly?: boolean;
  blockedBySourceRecoveryAcceptance?: boolean;
  sourceRecoveryAcceptanceCleared?: boolean;
  rerenderInputReady?: boolean;
  renderExecuted?: boolean;
  finalMp4Created?: boolean;
  proofArtifactCreated?: boolean;
  freshSourceProofCreated?: boolean;
  phoneReviewProofCreated?: boolean;
  platformAnalyticsProofCreated?: boolean;
  uploadReady?: boolean;
  goalComplete?: boolean;
  acceptedReplacementCount?: number;
  acceptedSceneCount?: number;
  totalScenes?: number;
  sourceRecoveryAcceptanceBlockerCount?: number;
  requiredArtifactPath?: string;
  missingFieldsByScene?: Record<string, string[]>;
  sceneReplacements?: Array<{
    sceneId?: string;
    acceptedReplacementFileName?: string;
    acceptedReplacementPath?: string;
    acceptedReplacementSha256?: string;
    reviewerId?: string;
    acceptedAt?: string;
    recommendedLane?: string;
    renderInputOverride?: Record<string, unknown>;
    postRerenderChecks?: string[];
  }>;
  renderPlan?: Record<string, unknown>;
  sourceRecoveryAcceptanceStatus?: SourceRecoveryAcceptanceStatus;
  sourceRecoveryPlan?: SourceRecoveryPlan;
  doesNotSatisfy?: string[];
  packet?: Record<string, unknown>;
  goalBoundary?: string;
  error?: string;
}

export interface RenderQualityCheck {
  status?: "pass" | "fail" | "warn" | string;
  detail?: string;
}

export interface RenderQualityReport {
  projectId?: string;
  outputPath?: string;
  generatedAt?: string;
  providers?: string[];
  captionPresets?: Array<{ sceneId?: string; captionPreset?: CaptionPreset | string }>;
  localMediaSummary?: Record<string, unknown>;
  checks?: Record<string, RenderQualityCheck>;
  productionReview?: ProductionReview;
  operatingTemplate?: LiveChannelOperatingTemplate;
  publishReadiness?: PublishReadiness;
  channelReadiness?: ChannelReadiness;
  uploadReview?: UploadReview;
  topTierReadiness?: TopTierReadiness;
  sourcePipelineStatus?: SourcePipelineStatus;
  gateSystem?: QualityGateSystem;
}

export interface PublishReadinessCriterion {
  key?: string;
  label?: string;
  status?: "pass" | "fail" | "warn" | string;
  detail?: string;
  required?: boolean;
}

export type ReadinessCriterion = PublishReadinessCriterion;

export interface PublishReadiness {
  status?: "ready" | "needs-rework" | "blocked" | string;
  score?: { passed?: number; total?: number };
  requiredFixes?: string[];
  recommendedFixes?: string[];
  strengths?: string[];
  criteria?: ReadinessCriterion[];
  summary?: Record<string, unknown>;
}

export interface ChannelReadiness {
  status?: "channel-ready" | "needs-original-footage" | "needs-hero-original-footage" | "needs-originality-proof" | "needs-quality-review" | "needs-publish-rework" | "blocked" | string;
  score?: { passed?: number; total?: number };
  requiredFixes?: string[];
  recommendedFixes?: string[];
  strengths?: string[];
  criteria?: ReadinessCriterion[];
  summary?: Record<string, unknown>;
}

export interface UploadReview {
  status?: "ready" | "needs-manual-review" | "blocked" | string;
  score?: { passed?: number; total?: number };
  requiredFixes?: string[];
  manualReviewItems?: string[];
  strengths?: string[];
  criteria?: ReadinessCriterion[];
  summary?: Record<string, unknown>;
}

export interface TopTierReadiness {
  status?: "top-tier-ready" | "needs-publish-rework" | "needs-channel-evidence" | "needs-upload-review" | "needs-grok-local-hero" | "needs-top-tier-review" | string;
  score?: { passed?: number; total?: number };
  requiredFixes?: string[];
  recommendedFixes?: string[];
  strengths?: string[];
  criteria?: ReadinessCriterion[];
  summary?: Record<string, unknown>;
}

export interface ProductionReviewScene {
  sceneId?: string;
  visualKind?: string;
  visualProvider?: string;
  sourceOrigin?: string;
  sourceIntent?: string;
  sourceRationale?: string;
  continuityNote?: string;
  hookNote?: string;
  originalityEvidence?: string;
  qualityReviewNote?: string;
  thumbnailReviewNote?: string;
  audioMixReviewNote?: string;
  platformComparisonNote?: string;
  productionMetaNarrationTerms?: string[];
  productionMetaSubtitleTerms?: string[];
  captionPreset?: CaptionPreset | string;
  captionDurationSec?: number;
  layoutVariantKey?: string;
  layoutVariantLabel?: string;
  layoutVariantNote?: string;
  candidateCount?: number;
  selectedFileName?: string;
  selectedCandidateSummary?: string;
  sourceProvenanceStatus?: string;
  sourceProvenanceConfirmed?: boolean;
  sourceProvenanceNote?: string;
  visualQualityVerdict?: string;
  visualQualityVerdictStatus?: string;
  caveats?: string[];
}

export interface TemplateSourceReview {
  status?: "pass" | "fail" | "warn" | string;
  template?: TemplateType | string;
  family?: string;
  sourceMix?: string;
  freeAssetPlan?: string;
  operatingTemplateKey?: string;
  operatingTemplate?: LiveChannelOperatingTemplate;
  counts?: Record<string, unknown>;
  requiredFixes?: string[];
  recommendedFixes?: string[];
}

export interface ProductionReviewSummary {
  totalScenes?: number;
  videoScenes?: number;
  stockVideoScenes?: number;
  uploadedVideoScenes?: number;
  grokHandoffScenes?: number;
  localModelVideoScenes?: number;
  imageFallbackScenes?: number;
  stockVideoSceneIds?: string[];
  uploadedVideoSceneIds?: string[];
  grokHandoffSceneIds?: string[];
  localModelVideoSceneIds?: string[];
  originalClipSceneIds?: string[];
  imageFallbackSceneIds?: string[];
  firstSceneId?: string;
  heroOriginalClipReady?: boolean;
  heroOriginalityEvidenceReady?: boolean;
  heroAiOrLocalReady?: boolean;
  missingRationaleScenes?: string[];
  missingContinuityScenes?: string[];
  missingOriginalityEvidenceScenes?: string[];
  missingQualityReviewScenes?: string[];
  originalityEvidenceScenes?: string[];
  qualityReviewScenes?: string[];
  thumbnailReviewScenes?: string[];
  audioMixReviewScenes?: string[];
  platformComparisonScenes?: string[];
  visualVerdictScenes?: string[];
  missingVisualVerdictScenes?: string[];
  failedVisualVerdictScenes?: string[];
  layoutVariantScenes?: string[];
  missingLayoutVariantScenes?: string[];
  layoutVariantCounts?: Record<string, number>;
  narrationScenes?: string[];
  subtitleOnlyNarrationScenes?: string[];
  missingNarrationScenes?: string[];
  thinNarrationScenes?: string[];
  productionMetaNarrationScenes?: string[];
  productionMetaSubtitleScenes?: string[];
  productionMetaTermsByScene?: Record<string, string[]>;
  narrationMinCharsByScene?: Record<string, number>;
  noVoiceAudioDesignScenes?: string[];
  voiceoverRequiredNoVoiceScenes?: string[];
  visualLedNoVoiceApprovedScenes?: string[];
  captionedSceneIds?: string[];
  captionSparsePlan?: boolean;
  longTopHookScenes?: string[];
  captionLayoutReviewScenes?: string[];
  missingCaptionLayoutReviewScenes?: string[];
  captionPresetCounts?: Record<string, number>;
  repeatedVisualAssetScenes?: string[];
  freeAssetProvenanceScenes?: string[];
  missingFreeAssetProvenanceScenes?: string[];
  freeAudioProvenanceAssets?: string[];
  missingFreeAudioProvenanceAssets?: string[];
  stockCandidateCurationScenes?: string[];
  stockCandidateCurationReadyScenes?: string[];
  missingStockCandidateCurationScenes?: string[];
  missingStockCandidateCountScenes?: string[];
  missingStockCandidateCreatorScenes?: string[];
  missingStockSelectionSummaryScenes?: string[];
  stockCandidateCurationIssuesByScene?: Record<string, string[]>;
  bgmSelectionAssets?: string[];
  weakBgmSelectionAssets?: string[];
  placeholderBgmAssets?: string[];
  placeholderBgmAssetReasons?: Record<string, string>;
  firstSceneHookReady?: boolean;
  stockOnly?: boolean;
  curatedStockReady?: boolean;
  contentTemplate?: TemplateType | string;
}

export interface ProductionReview {
  summary?: ProductionReviewSummary;
  scenes?: ProductionReviewScene[];
  templateSourceReview?: TemplateSourceReview;
}

export interface GrokTakePrompt {
  takeNumber?: number;
  label?: string;
  focus?: string;
  prompt?: string;
  promptQuality?: GrokHandoffScene["promptQuality"];
}

export interface GrokHandoffScene {
  sceneId: string;
  sceneNum?: number;
  prompt: string;
  promptQuality?: {
    score?: number;
    status?: string;
    missing?: string[];
    weakSourcePrompt?: boolean;
    sourceWordCount?: number;
    sourcePrompt?: string;
    checks?: Record<string, boolean>;
    qualityFloor?: string;
    operatorAction?: string;
  };
  promptPath?: string;
  expectedFileName: string;
  downloadInstruction?: string;
  operatorChecklist?: string[];
  takePrompts?: GrokTakePrompt[];
}

export interface GrokShotBible {
  visualContinuity?: string;
  subjectContinuity?: string;
  locationContinuity?: string;
  palette?: string;
  cameraLanguage?: string;
  productionProfile?: {
    templateType?: string;
    targetDuration?: string;
    tone?: string;
    language?: string;
    family?: string;
    narrativeShape?: string;
    hookFormula?: string;
    layoutPlan?: string;
    captionPlan?: string;
    cameraPlan?: string;
    editRhythm?: string;
  };
  layoutPlan?: string;
  captionSafePlan?: string;
  motionPlan?: string;
  editRhythm?: string;
  negativePrompts?: string[];
  promptAnchor?: string;
  grokPromptRules?: string[];
  reviewChecklist?: string[];
  hardRejectChecklist?: string[];
  sceneIntents?: Array<{ sceneId?: string; intent?: string }>;
}

export interface GrokHandoffAsset {
  sceneId?: string;
  fileName?: string;
  expectedFileName?: string;
  mimeType?: string;
  sourcePath?: string;
  previewUrl?: string;
  sizeBytes?: number;
  selected?: boolean;
  status?: "ready" | "missing" | "unmatched" | string;
  clipProbe?: GrokClipProbe;
  qualityGate?: GrokSceneQualityGate;
  candidateAssets?: GrokHandoffAsset[];
  importMetadata?: GrokImportMetadata;
  sourceProvenance?: GrokSourceProvenance;
}

export interface GrokImportMetadata {
  importedAt?: string;
  importMode?: string;
  historyImportMode?: string;
  downloadDir?: string;
  downloadFilePath?: string;
  originalPath?: string;
  uploadedFileName?: string;
}

export interface GrokSourceProvenance {
  status?: "browser-native-original-download" | "visible-video-fallback-proof-only" | "local-mp4-download-unverified" | "local-mp4-source-unverified" | string;
  label?: string;
  acceptAsGrokMainSource?: boolean;
  proofOnly?: boolean;
  originalDownloadLikely?: boolean;
  importMode?: string;
  originalPath?: string;
  sourceKind?: string;
  qualityNote?: string;
  eventType?: string;
  candidateUrl?: string;
  operatorAction?: string;
}

export interface GrokClipProbe {
  ok?: boolean;
  status?: "ok" | "needs-review" | string;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  durationSec?: number | null;
  aspectRatio?: number | null;
  hasAudio?: boolean;
  motionOk?: boolean;
  motionStatus?: "ok" | "low-motion" | "insufficient-frames" | "probe-error" | "tool-missing" | "no-video" | string;
  motionFrameCount?: number;
  motionMaxFrameDelta?: number;
  motionMeanFrameDelta?: number;
  motionIssues?: string[];
  issues?: string[];
}

export interface GrokSceneQualityGate {
  required?: boolean;
  status?: "missing" | "rejected" | "technical-review" | "source-review" | "accepted" | "pending-operator-review" | "review-recommended" | string;
  accepted?: boolean;
  firstTwoSecondHook?: boolean;
  artifactFree?: boolean;
  continuityOk?: boolean;
  captionSafe?: boolean;
  shotLockMatch?: boolean;
  sceneAssemblyOk?: boolean;
  reviewEvidenceMissing?: string[];
  technicalOk?: boolean | null;
  technicalIssues?: string[];
  sourceAcceptable?: boolean | null;
  sourceProvenanceConfirmationRequired?: boolean;
  sourceProvenanceConfirmed?: boolean;
  sourceProvenanceNote?: string;
  sourceIssues?: string[];
  sourceProvenance?: GrokSourceProvenance;
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
}

export interface GrokAggregateQualityGate {
  required?: boolean;
  allReady?: boolean;
  readySceneIds?: string[];
  pendingSceneIds?: string[];
  rejectedSceneIds?: string[];
}

export interface GrokMainSourceGate {
  required?: boolean;
  status?: "ready" | "needs-more-grok-scenes" | "needs-accepted-grok-clips" | "needs-replacement-clips" | "needs-candidate-curation" | "needs-first-hook-grok-clip" | "needs-first-hook-grok-scene" | "not-required" | string;
  allReady?: boolean;
  sourceMixTotalScenes?: number;
  plannedGrokScenes?: number;
  minAcceptedScenes?: number;
  acceptedSceneIds?: string[];
  readySceneIds?: string[];
  pendingSceneIds?: string[];
  rejectedSceneIds?: string[];
  missingSceneIds?: string[];
  firstHookRequired?: boolean;
  firstHookSceneId?: string;
  firstHookPlanned?: boolean;
  firstHookReady?: boolean;
  firstHookAccepted?: boolean;
  candidateCurationRequired?: boolean;
  candidateCurationGapSceneIds?: string[];
  candidateCountBySceneId?: Record<string, number>;
  additionalAcceptedScenesNeeded?: number;
  additionalPlannedScenesNeeded?: number;
  plannedSceneIds?: string[];
  detail?: string;
}

export interface GrokReviewDecision {
  sceneId?: string;
  accepted?: boolean;
  firstTwoSecondHook?: boolean;
  artifactFree?: boolean;
  continuityOk?: boolean;
  captionSafe?: boolean;
  selectedFileName?: string;
  shotLockMatch?: boolean;
  sceneAssemblyOk?: boolean;
  sourceRationale?: string;
  qualityReviewNote?: string;
  captionLayoutReviewNote?: string;
  visualQualityVerdict?: string;
  shotLockEvidenceNote?: string;
  sceneAssemblyRoleNote?: string;
  continuityNote?: string;
  hookNote?: string;
  layoutVariantKey?: string;
  layoutVariantLabel?: string;
  layoutVariantNote?: string;
  thumbnailReviewNote?: string;
  audioMixReviewNote?: string;
  platformComparisonNote?: string;
  sourceProvenanceConfirmed?: boolean;
  sourceProvenanceNote?: string;
  sourceProvenanceStatus?: string;
  selectedCandidateSummary?: string;
  singleCandidateJustification?: string;
  operatorNote?: string;
  updatedAt?: string;
}

export interface GrokReviewDecisionResult {
  ok: boolean;
  projectId?: string;
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
  reviewDecision?: GrokReviewDecision;
  renderPayload?: GrokHandoffRenderPayload;
  error?: string;
}

export interface GrokAutomationStatus {
  sceneId?: string;
  expectedFileName?: string;
  status?: "preflight" | "injected" | "needs-operator" | "imported" | "pending" | string;
  detail?: string;
  mode?: string;
  browserBlocker?: string | null;
  operatorAuthStage?: string;
  operatorAuthStageLabel?: string;
  authProviderPreference?: GrokAuthProvider;
  authRequired?: boolean;
  cookieChoiceRequired?: boolean;
  promptInjected?: boolean;
  generateRequested?: boolean;
  downloadResultRequested?: boolean;
  watchDownloadsRequested?: boolean;
  readyScenes?: number;
  totalScenes?: number;
  remoteDebuggingPort?: number;
  targetUrl?: string;
  targetTitle?: string;
  launched?: boolean;
  userDataDir?: string;
  useDefaultChromeProfile?: boolean;
  attachDefaultChromeApproved?: boolean;
  browserProfileMode?: string;
  browserProfileDirectory?: string;
  downloadDir?: string;
  downloadDirs?: string[];
  manualDownloadInstruction?: string;
  operatorNextAction?: string;
  downloadClickReason?: string;
  operatorReadyTimedOut?: boolean;
  operatorReadyWait?: Record<string, unknown>;
}

export interface GrokAutomationReplay {
  sceneId?: string;
  expectedFileName?: string;
  updatedAt?: string;
  downloadDir?: string;
  operatorReadyTimeoutSeconds?: number;
  operatorReadyPollIntervalSeconds?: number;
  authKickoffApproved?: boolean;
  authProviderKickoffApproved?: boolean;
  authProviderPreference?: GrokAuthProvider;
  useDefaultChromeProfile?: boolean;
  attachDefaultChromeApproved?: boolean;
  browserProfileMode?: string;
  browserProfileDirectory?: string;
  cookieRejectApproved?: boolean;
  generatePromptApproved?: boolean;
  downloadResultApproved?: boolean;
  watchDownloadsApproved?: boolean;
  waitForOperatorReadyApproved?: boolean;
  resumeEndpoint?: string | null;
  requiresFreshApproval?: boolean;
}

export interface GrokAutomationJobStatus {
  jobId?: string;
  projectId?: string;
  sceneId?: string;
  expectedFileName?: string;
  status?: "queued" | "running" | "needs-operator" | "completed" | "imported" | "failed" | string;
  detail?: string;
  createdAt?: string;
  startedAt?: string;
  updatedAt?: string;
  finishedAt?: string;
  downloadDir?: string | null;
  automationReplay?: GrokAutomationReplay | null;
  automationStatus?: GrokAutomationStatus;
  readyScenes?: number;
  totalScenes?: number;
  allReady?: boolean;
  activeThread?: boolean;
  restartAvailable?: boolean;
  stale?: boolean;
  elapsedSeconds?: number;
  operatorWaitDeadlineAt?: string;
  operatorWaitRemainingSeconds?: number;
  browserBlocker?: string | null;
  operatorNextAction?: string;
  error?: string;
}

export interface GrokManualDownloadWatchJobStatus {
  jobId?: string;
  projectId?: string;
  sceneId?: string;
  expectedFileName?: string;
  status?: string;
  detail?: string;
  createdAt?: string;
  startedAt?: string;
  updatedAt?: string;
  finishedAt?: string;
  downloadDir?: string;
  downloadDirs?: string[];
  timeoutSeconds?: number;
  pollIntervalSeconds?: number;
  allowNewestFallback?: boolean;
  sinceHandoff?: boolean;
  preserveCandidates?: boolean;
  stopOnImport?: boolean;
  sceneMappingMode?: string;
  sceneGroupedTakeSize?: number;
  sceneGroupedTakeTarget?: number;
  readyScenes?: number;
  totalScenes?: number;
  allReady?: boolean;
  attempts?: number;
  elapsedSeconds?: number;
  remainingSeconds?: number;
  deadlineAt?: string;
  importedCount?: number;
  timedOut?: boolean;
  activeThread?: boolean;
  restartAvailable?: boolean;
  stale?: boolean;
  operatorNextAction?: string;
  error?: string;
}

export interface GrokSupersededJob {
  previousJob?: GrokAutomationJobStatus | Record<string, unknown>;
  cancelRequest?: {
    jobId?: string;
    reason?: string;
    requestedAt?: string;
  };
}

export interface GrokOperatorBrowserTarget {
  targetId?: string;
  title?: string;
  url?: string;
  kind?: "grok-imagine" | "grok" | "grok-auth" | "xai-auth" | "x-oauth" | "x-login" | "page" | string;
  score?: number;
}

export interface GrokOperatorFocusResult {
  ok: boolean;
  projectId?: string;
  remoteDebuggingPort?: number;
  focused?: boolean;
  activated?: boolean;
  activationResult?: string | null;
  openedTarget?: GrokOperatorBrowserTarget | null;
  bestTarget?: GrokOperatorBrowserTarget | null;
  targets?: GrokOperatorBrowserTarget[];
  pageCount?: number;
  grokTabCount?: number;
  signInTabCount?: number;
  hasOperatorTarget?: boolean;
  operatorNextAction?: string;
  error?: string;
}

export interface GrokOperatorTabCleanupResult {
  ok: boolean;
  projectId?: string;
  remoteDebuggingPort?: number;
  preferAuthTarget?: boolean;
  keepCount?: number;
  keptTargets?: GrokOperatorBrowserTarget[];
  closedTargets?: Array<GrokOperatorBrowserTarget & { result?: string }>;
  failedTargets?: Array<GrokOperatorBrowserTarget & { error?: string }>;
  closedCount?: number;
  failedCount?: number;
  bestTarget?: GrokOperatorBrowserTarget | null;
  targets?: GrokOperatorBrowserTarget[];
  pageCount?: number;
  grokTabCount?: number;
  signInTabCount?: number;
  operatorNextAction?: string;
  error?: string;
}

export interface GrokChromeProfileProbeProfile {
  profileDir?: string;
  profileName?: string;
  videoStudioCompanion?: boolean;
  codexExtension?: boolean;
  preferencesReadable?: boolean;
}

export interface GrokChromeProfileAlignment {
  status?: string;
  primaryOperatorProfileDirectory?: string;
  primaryOperatorProfileName?: string;
  primaryOperatorProfileLabel?: string;
  automationReplayProfileDirectory?: string;
  profileMismatch?: boolean;
  codexExtensionProfileDirectories?: string[];
  videoStudioCompanionProfileDirectories?: string[];
  controlRoute?: string;
  codexChromePluginRoute?: string;
  operatorAction?: string;
  doNotOpen?: string[];
}

export interface GrokChromeProfileProbe {
  checked?: boolean;
  status?: string;
  checkedRoots?: string[];
  profiles?: GrokChromeProfileProbeProfile[];
  anyVideoStudioCompanion?: boolean;
  anyCodexExtension?: boolean;
  recommendedProfileDirectory?: string;
  recommendedProfileName?: string;
  recommendedProfileLabel?: string;
  recommendedProfileReason?: string;
  videoStudioCompanionProfileDirectories?: string[];
  codexExtensionProfileDirectories?: string[];
  automationReplayProfileDirectory?: string;
  profileMismatch?: boolean;
  codexNativeHost?: {
    checked?: boolean;
    hostName?: string;
    manifestPath?: string;
    manifestExists?: boolean;
    hostExecutablePath?: string;
    hostExecutableExists?: boolean;
    allowedOriginRegistered?: boolean;
    status?: string;
    usedByVideoStudioGrok?: boolean;
    videoStudioDirectControlAvailable?: boolean;
    controlSurfaceExposedToBridge?: boolean;
    requiredControlSurface?: string;
    directControlReason?: string;
    recommendedUse?: string;
    operatorAction?: string;
  };
  codexExtensionCanDriveVideoStudioGrok?: boolean;
  codexExtensionIsNotCompanion?: boolean;
  primaryOperatorProfileDirectory?: string;
  primaryOperatorProfileName?: string;
  primaryOperatorProfileLabel?: string;
  browserPolicy?: string;
  doNotOpenBrowsers?: string[];
  profileAlignment?: GrokChromeProfileAlignment;
  operatorAction?: string;
}

export interface GrokChromeCompanionExtension {
  mode?: string;
  primaryGenerationRail?: string;
  role?: string;
  requiredForGeneration?: boolean;
  requiredForDownload?: boolean;
  usesPaidApi?: boolean;
  usesRemoteDebugging?: boolean;
  storesCredentials?: boolean;
  opensEdge?: boolean;
  purpose?: string;
  extensionDir?: string;
  guideUrl?: string;
  operatorCommandUrl?: string;
  operatorAutostartUrl?: string;
  operatorPrepGenerateAutostartUrl?: string;
  commandUrl?: string;
  eventEndpoint?: string;
  autostartUrl?: string;
  prepGenerateAutostartUrl?: string;
  selectedSceneCommandUrl?: string;
  selectedSceneAutostartUrl?: string;
  selectedScenePrepGenerateAutostartUrl?: string;
  bookmarkletUrl?: string;
  bookmarkletGenerateUrl?: string;
  bookmarkletScriptUrl?: string;
  bookmarkletGenerateScriptUrl?: string;
  bookmarkletInlineMode?: string;
  bookmarkletInlineUrl?: string;
  bookmarkletGenerateInlineUrl?: string;
  bookmarkletInlineConsoleSnippet?: string;
  bookmarkletGenerateInlineConsoleSnippet?: string;
  bookmarkletQueueUrl?: string;
  bookmarkletQueueScriptUrl?: string;
  bookmarkletQueueInlineUrl?: string;
  bookmarkletQueueInlineConsoleSnippet?: string;
  bookmarkletImportEndpoint?: string;
  bookmarkletEventEndpoint?: string;
  profileProbe?: GrokChromeProfileProbe;
  sceneId?: string | null;
  takeCommands?: GrokCompanionCommand[];
  operatorStillDoes?: string[];
}

export interface GrokBrowserControlPrimaryRail {
  mode?: string;
  primary?: boolean;
  provider?: string;
  source?: string;
  requiresExistingSignedInChromeProfile?: boolean;
  forbidNewChromeProfile?: boolean;
  forbidEdgeFallback?: boolean;
  usesPaidApi?: boolean;
  usesRemoteDebugging?: boolean;
  extensionRequiredForGeneration?: boolean;
  companionExtensionRole?: string;
  bookmarkletRole?: string;
  downloadAuthority?: string;
  autoNativeDownloadPromptAllowed?: boolean;
  automaticDownloadClickAllowed?: boolean;
  sceneId?: string;
  expectedFileName?: string;
  recommendedTakeNumber?: number | null;
  generationObserved?: boolean;
  observedPostUrl?: string;
  observedAssetUrl?: string;
  operatorNextAction?: string;
  importEndpoints?: {
    importDownloads?: string;
    manualDownloadWatch?: string;
    manualUpload?: string;
    manualBatchUpload?: string;
  };
  successCriteria?: string[];
  doNotUse?: string[];
}

export interface GrokCompanionCommand {
  ok: boolean;
  projectId?: string;
  sceneId?: string;
  title?: string;
  takeNumber?: number;
  takeLabel?: string;
  takeFocus?: string;
  label?: string;
  focus?: string;
  prompt?: string;
  promptQuality?: GrokHandoffScene["promptQuality"];
  expectedFileName?: string;
  commandUrl?: string;
  autostartUrl?: string;
  prepGenerateAutostartUrl?: string;
  bookmarkletUrl?: string;
  bookmarkletGenerateUrl?: string;
  bookmarkletScriptUrl?: string;
  bookmarkletGenerateScriptUrl?: string;
  bookmarkletInlineMode?: string;
  bookmarkletInlineUrl?: string;
  bookmarkletGenerateInlineUrl?: string;
  bookmarkletInlineConsoleSnippet?: string;
  bookmarkletGenerateInlineConsoleSnippet?: string;
  bookmarkletQueueUrl?: string;
  bookmarkletQueueScriptUrl?: string;
  bookmarkletQueueInlineUrl?: string;
  bookmarkletQueueInlineConsoleSnippet?: string;
  bookmarkletImportEndpoint?: string;
  bookmarkletEventEndpoint?: string;
  guideUrl?: string;
  queueCommandUrl?: string;
  incomingDir?: string;
  defaultDownloadDir?: string;
  guardrails?: Record<string, unknown>;
  takeCommands?: GrokCompanionCommand[];
  operatorStillDoes?: string[];
  error?: string;
}

export interface GrokManualPrimaryPath {
  mode?: "manual-grok-app-web-primary" | string;
  browserControlRail?: string;
  companionExtensionRole?: string;
  downloadAuthority?: string;
  primarySource?: string;
  usesPaidApi?: boolean;
  paidApiPolicy?: string;
  browserAutomationRole?: string;
  browserAutomationState?: string;
  nextAction?: string;
  operatorNextAction?: string;
  automationNextAction?: string;
  projectId?: string;
  incomingDir?: string;
  defaultDownloadDir?: string;
  defaultDownloadDirExists?: boolean;
  worksheetUrl?: string;
  productionQueueUrl?: string;
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
  currentScene?: {
    sceneId?: string;
    sceneNumber?: number | null;
    expectedFileName?: string;
    promptPath?: string;
    basePrompt?: string;
    prompt?: string;
    promptExcerpt?: string;
    recommendedTakeNumber?: number | null;
    recommendedTakeLabel?: string;
    recommendedTakeFocus?: string;
    commandUrl?: string;
    prepGenerateAutostartUrl?: string;
    takeCommands?: GrokCompanionCommand[];
    downloadInstruction?: string;
    operatorChecklist?: string[];
  };
  orderedBatchUpload?: {
    supported?: boolean;
    selectionRule?: string;
    recommendedFileOrder?: Array<{
      sceneId?: string;
      expectedFileName?: string;
    }>;
    filenameStillAccepted?: boolean;
  };
  acceptedSceneIds?: string[];
  plannedSceneIds?: string[];
  requiredAcceptedScenes?: number;
  additionalAcceptedScenesNeeded?: number;
  mainSourceGate?: GrokMainSourceGate;
  endpoints?: {
    importDownloads?: string;
    watchDownloads?: string;
    manualDownloadWatch?: string;
    manualUpload?: string;
    manualBatchUpload?: string;
    operatorRun?: string;
    productionQueue?: string;
    reviewPacket?: string;
    reviewDecision?: string;
    renderPayload?: string;
  };
  operatorSteps?: string[];
  qualityRules?: string[];
}

export interface GrokObservedPostImportPlan {
  available?: boolean;
  ready?: boolean;
  mode?: "observed-grok-post-to-download-watch" | string;
  usesPaidApi?: boolean;
  storesCredentials?: boolean;
  sceneId?: string;
  expectedFileName?: string;
  postUrl?: string;
  videoUrl?: string;
  observedAssetManualRunwayUrl?: string;
  observedAssetManualRunwayEndpoint?: string;
  observedPostDownloadEndpoint?: string;
  observedPostDownloadScriptUrl?: string;
  observedPostDownloadInlineUrl?: string;
  observedPostDownloadConsoleSnippet?: string;
  downloadDir?: string;
  manualWatchEndpoint?: string;
  importDownloadsEndpoint?: string;
  manualBatchUploadEndpoint?: string;
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
  localMp4ImportRequired?: boolean;
  directAssetFetch?: {
    serverFetchSupported?: boolean;
    expectedFailure?: string;
    reason?: string;
    approvedPath?: string;
  };
  manualWatchRequest?: Record<string, unknown>;
  disabledReason?: string;
  operatorSteps?: string[];
  qualityNote?: string;
}

export interface GrokAssetAcquisitionStatus {
  state?: string;
  status?: string;
  clipGenerated?: boolean;
  localMp4Imported?: boolean;
  publishReadyLocalMp4?: boolean;
  qualityBlocked?: boolean;
  qualityBlockers?: string[];
  bestLocalCandidate?: {
    sceneId?: string;
    fileName?: string;
    width?: number | null;
    height?: number | null;
    fps?: number | null;
    durationSec?: number | null;
    technicalOk?: boolean;
    issues?: string[];
    sourceProvenance?: GrokSourceProvenance;
  };
  sourceQualityFloor?: string;
  manualWatchActive?: boolean;
  companionConnected?: boolean;
  blockerScope?: string;
  sceneId?: string;
  expectedFileName?: string;
  observedPostUrl?: string;
  observedAssetUrl?: string;
  directAssetFetchSupported?: boolean | null;
  downloadAuthority?: string;
  primaryBlocker?: string;
  approvedImportPaths?: string[];
  operatorActionPriority?: string[];
  doNotDo?: string[];
  qualityContract?: string[];
  candidateCurationPlan?: {
    required?: boolean;
    targetSceneId?: string;
    expectedFileName?: string;
    candidateCount?: number;
    publishableCandidateCount?: number;
    minimumCandidates?: number;
    reviewReadiness?: string;
    recommendation?: string;
    selectionRule?: string;
    selectedCandidate?: {
      sceneId?: string;
      fileName?: string;
      width?: number | null;
      height?: number | null;
      fps?: number | null;
      durationSec?: number | null;
      technicalOk?: boolean;
      motionOk?: boolean;
      sourceAcceptable?: boolean;
      sourceStatus?: string;
      score?: number;
      rejectReasons?: string[];
    };
    candidates?: Array<{
      sceneId?: string;
      fileName?: string;
      width?: number | null;
      height?: number | null;
      fps?: number | null;
      durationSec?: number | null;
      technicalOk?: boolean;
      motionOk?: boolean;
      sourceAcceptable?: boolean;
      sourceStatus?: string;
      score?: number;
      rejectReasons?: string[];
    }>;
  };
  originalExportPlan?: {
    required?: boolean;
    priority?: string;
    modelBlocked?: boolean;
    accountBlocked?: boolean;
    paidApiRequired?: boolean;
    cdpPrimary?: boolean;
    summary?: string;
    currentBlocker?: string;
    targetSceneId?: string;
    expectedFileName?: string;
    nativeExportRequired?: boolean;
    reason?: string;
    requiredActions?: string[];
    rejectAsMainSource?: string[];
    operatorProofNeeded?: string[];
  };
}

export interface GrokMainSourceDiagnosis {
  modelBlocked?: boolean;
  generationObserved?: boolean;
  localMp4Imported?: boolean;
  currentBlocker?: string;
  recommendedPrimaryPath?: string;
  companionExtensionRole?: string;
  downloadAuthority?: string;
  doNotDowngradeToStockOnly?: boolean;
}

export interface GrokMainPathStatus {
  mode?: "grok-app-web-mp4-primary" | string;
  status?: "ready" | "not-required" | "generated-export-pending" | "needs-first-grok-mp4" | "needs-first-hook-review" | "needs-more-grok-mp4s" | "needs-grok-review" | "needs-candidate-curation" | "needs-replacement-grok-mp4s" | "needs-accepted-grok-clips" | string;
  blocked?: boolean;
  blocker?: string;
  summary?: string;
  primaryPath?: string;
  primaryPathDetail?: string;
  primaryNextAction?: string;
  operatorNextAction?: string;
  usesPaidApi?: boolean;
  paidApiPolicy?: string;
  grokAppWebViable?: boolean;
  cdpPrimaryRecommended?: boolean;
  secondaryAutomationRole?: string;
  secondaryAutomationBlocker?: string;
  secondaryAutomationStatus?: string;
  secondaryAutomationDetail?: string;
  companionConnected?: boolean;
  companionConnectionStatus?: string;
  manualWatchActive?: boolean;
  projectId?: string;
  handoffDir?: string;
  incomingDir?: string;
  productionQueueUrl?: string;
  reviewPacketUrl?: string;
  nextSceneId?: string;
  nextExpectedFileName?: string;
  recommendedTakeNumber?: number | null;
  recommendedTakeLabel?: string;
  readyScenes?: number;
  totalScenes?: number;
  acceptedSceneIds?: string[];
  requiredAcceptedScenes?: number;
  mainSourceGateStatus?: string;
  generationObservation?: GrokCodexChromeObservation | Record<string, unknown>;
  observedPostImportPlan?: GrokObservedPostImportPlan;
  assetAcquisition?: GrokAssetAcquisitionStatus;
  originalExportPlan?: GrokAssetAcquisitionStatus["originalExportPlan"];
  notBlockedBy?: string[];
  proofPoints?: string[];
}

export interface GrokCodexChromeObservation {
  updatedAt?: string;
  projectId?: string;
  sceneId?: string;
  expectedFileName?: string;
  source?: string;
  status?: string;
  exportStatus?: string;
  exportBlocker?: string;
  postUrl?: string;
  videoUrl?: string;
  durationSeconds?: number;
  renderedWidth?: number;
  renderedHeight?: number;
  detail?: string;
  operatorNextAction?: string;
  storesCredentials?: boolean;
  usesPaidApi?: boolean;
}

export interface GrokHandoffResult {
  ok: boolean;
  projectId?: string;
  handoffDir?: string;
  manifestPath?: string;
  incomingDir?: string;
  grokUrl?: string;
  worksheetPath?: string;
  worksheetUrl?: string;
  productionQueuePath?: string;
  productionQueueUrl?: string;
  automationPlanUrl?: string;
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
  defaultDownloadDir?: string;
  defaultDownloadDirExists?: boolean;
  reviewDecisions?: Record<string, GrokReviewDecision>;
  qualityGate?: GrokAggregateQualityGate;
  mainSourceGate?: GrokMainSourceGate;
  assets?: GrokHandoffAsset[];
  readyScenes?: number;
  totalScenes?: number;
  allReady?: boolean;
  previewMode?: boolean;
  previewReady?: boolean;
  previewSceneIds?: string[];
  renderPurpose?: "grok-final-handoff" | "grok-import-preview" | string;
  missingSceneIds?: string[];
  rejectedSceneIds?: string[];
  nextMissingSceneId?: string | null;
  nextMissingExpectedFileName?: string | null;
  shotBible?: GrokShotBible;
  scenes?: GrokHandoffScene[];
  automationStatus?: GrokAutomationStatus;
  automationReplay?: GrokAutomationReplay | null;
  automationJob?: GrokAutomationJobStatus | null;
  manualDownloadWatchJob?: GrokManualDownloadWatchJobStatus | null;
  chromeCompanionExtension?: GrokChromeCompanionExtension;
  browserControlPrimaryRail?: GrokBrowserControlPrimaryRail;
  manualPrimaryPath?: GrokManualPrimaryPath;
  mainPathStatus?: GrokMainPathStatus;
  observedPostImportPlan?: GrokObservedPostImportPlan | null;
  grokAssetAcquisition?: GrokAssetAcquisitionStatus;
  grokMainSourceDiagnosis?: GrokMainSourceDiagnosis;
  codexChromeObservation?: GrokCodexChromeObservation | null;
  operatorNextAction?: string;
  primaryOperatorNextAction?: string;
  error?: string;
}

export interface GrokHandoffStatus {
  ok: boolean;
  projectId?: string;
  handoffDir?: string;
  incomingDir?: string;
  grokUrl?: string;
  worksheetUrl?: string;
  productionQueueUrl?: string;
  automationPlanUrl?: string;
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
  defaultDownloadDir?: string;
  defaultDownloadDirExists?: boolean;
  reviewDecisions?: Record<string, GrokReviewDecision>;
  qualityGate?: GrokAggregateQualityGate;
  mainSourceGate?: GrokMainSourceGate;
  assets?: GrokHandoffAsset[];
  readyScenes?: number;
  totalScenes?: number;
  allReady?: boolean;
  missingSceneIds?: string[];
  rejectedSceneIds?: string[];
  nextMissingSceneId?: string | null;
  nextMissingExpectedFileName?: string | null;
  automationStatus?: GrokAutomationStatus;
  automationReplay?: GrokAutomationReplay | null;
  automationJob?: GrokAutomationJobStatus | null;
  manualDownloadWatchJob?: GrokManualDownloadWatchJobStatus | null;
  chromeCompanionExtension?: GrokChromeCompanionExtension;
  browserControlPrimaryRail?: GrokBrowserControlPrimaryRail;
  latestExtensionEvent?: Record<string, unknown> | null;
  codexChromeObservation?: GrokCodexChromeObservation | null;
  manualPrimaryPath?: GrokManualPrimaryPath;
  mainPathStatus?: GrokMainPathStatus;
  observedPostImportPlan?: GrokObservedPostImportPlan | null;
  grokAssetAcquisition?: GrokAssetAcquisitionStatus;
  grokMainSourceDiagnosis?: GrokMainSourceDiagnosis;
  operatorNextAction?: string;
  primaryOperatorNextAction?: string;
  error?: string;
}

export interface GrokHandoffOpenResult {
  ok: boolean;
  opened?: boolean;
  projectId?: string;
  grokUrl?: string;
  worksheetUrl?: string;
  automationPlanUrl?: string;
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
  target?: "worksheet" | "grok" | "both" | string;
  incomingDir?: string;
  defaultDownloadDir?: string;
  defaultDownloadDirExists?: boolean;
  error?: string;
}

export interface GrokAutomationPlan {
  ok: boolean;
  projectId?: string;
  mode?: string;
  goal?: string;
  grokUrl?: string;
  worksheetUrl?: string;
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
  incomingDir?: string;
  defaultDownloadDir?: string;
  defaultDownloadDirExists?: boolean;
  shotBible?: GrokShotBible;
  reviewChecklist?: string[];
  mainSourceGate?: GrokMainSourceGate;
  browserControlPrimaryRail?: GrokBrowserControlPrimaryRail;
  manualPrimaryPath?: GrokManualPrimaryPath;
  mainPathStatus?: GrokMainPathStatus;
  expectedFiles?: Array<{ sceneId: string; expectedFileName: string; promptPath?: string; operatorChecklist?: string[] }>;
  approvalRequired?: boolean;
  automationBoundaries?: Record<string, unknown>;
  downloadImport?: Record<string, unknown>;
  postImportReview?: Record<string, unknown>;
  chromeCompanionExtension?: GrokChromeCompanionExtension;
  automationReplay?: Record<string, unknown>;
  backgroundAutomation?: Record<string, unknown>;
  nextAutomationSlice?: Record<string, unknown>;
  error?: string;
}

export interface GrokImportDownloadsResult {
  ok: boolean;
  projectId?: string;
  downloadDir?: string;
  downloadDirs?: string[];
  incomingDir?: string;
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
  imported?: Array<{
    sceneId: string;
    expectedFileName: string;
    fileName: string;
    sourcePath: string;
    originalPath: string;
    sizeBytes?: number;
  }>;
  skipped?: Array<{ sceneId?: string; fileName?: string; reason?: string }>;
  assets?: GrokHandoffAsset[];
  readyScenes?: number;
  totalScenes?: number;
  allReady?: boolean;
  qualityGate?: GrokAggregateQualityGate;
  mainSourceGate?: GrokMainSourceGate;
  error?: string;
}

export interface GrokWatchDownloadsResult extends GrokImportDownloadsResult {
  timeoutSeconds?: number;
  pollIntervalSeconds?: number;
  attempts?: number;
  elapsedSeconds?: number;
  timedOut?: boolean;
  renderPayload?: GrokHandoffRenderPayload | null;
}

export interface GrokManualDownloadWatchResult {
  ok: boolean;
  projectId?: string;
  sceneId?: string;
  expectedFileName?: string;
  downloadDir?: string;
  downloadDirs?: string[];
  incomingDir?: string;
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
  alreadyRunning?: boolean;
  replaceAvailable?: boolean;
  replacedExisting?: boolean;
  manualDownloadWatchJob?: GrokManualDownloadWatchJobStatus | null;
  error?: string;
}

export interface GrokOperatorRunResult extends GrokWatchDownloadsResult {
  automationMode?: string;
  opened?: boolean;
  openedTargets?: Array<{ target: string; url: string; opened: boolean }>;
  openErrors?: Array<{ target?: string; url?: string; error?: string }>;
}

export interface GrokBrowserAutomationResult {
  ok: boolean;
  alreadyRunning?: boolean;
  cancelPending?: boolean;
  supersededJob?: GrokSupersededJob;
  projectId?: string;
  sceneId?: string;
  expectedFileName?: string;
  incomingDir?: string;
  worksheetUrl?: string;
  automationPlanUrl?: string;
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
  browserAutomationMode?: string;
  remoteDebuggingPort?: number;
  filledSceneId?: string;
  preflightOnly?: boolean;
  preflight?: Record<string, unknown>;
  operatorReadyWait?: Record<string, unknown>;
  operatorReadyTimedOut?: boolean;
  promptInjected?: boolean;
  submitPromptRequested?: boolean;
  generatePromptRequested?: boolean;
  generateRequested?: boolean;
  generateAction?: string | null;
  generateClick?: Record<string, unknown>;
  downloadResultRequested?: boolean;
  downloadClick?: Record<string, unknown>;
  authRequired?: boolean;
  cookieChoiceRequired?: boolean;
  browserBlocker?: string | null;
  operatorAuthStage?: string;
  operatorAuthStageLabel?: string;
  requiresOperatorAction?: boolean;
  downloadClickTimeoutSeconds?: number;
  watchDownloadsRequested?: boolean;
  downloadDir?: string;
  imported?: Array<Record<string, unknown>>;
  skipped?: Array<Record<string, unknown>>;
  assets?: GrokHandoffAsset[];
  readyScenes?: number;
  totalScenes?: number;
  allReady?: boolean;
  missingSceneIds?: string[];
  rejectedSceneIds?: string[];
  nextMissingSceneId?: string | null;
  nextMissingExpectedFileName?: string | null;
  watchTimeoutSeconds?: number;
  watchPollIntervalSeconds?: number;
  attempts?: number;
  elapsedSeconds?: number;
  timedOut?: boolean;
  renderPayload?: GrokHandoffRenderPayload | null;
  launched?: boolean;
  automationStatus?: GrokAutomationStatus;
  automationReplay?: GrokAutomationReplay | null;
  automationJob?: GrokAutomationJobStatus | null;
  browserExecutable?: string;
  userDataDir?: string;
  useDefaultChromeProfile?: boolean;
  attachDefaultChromeApproved?: boolean;
  browserProfileMode?: string;
  browserProfileDirectory?: string;
  targetUrl?: string;
  targetTitle?: string;
  manualDownloadInstruction?: string;
  operatorNextAction?: string;
  error?: string;
}

export interface GrokHandoffRenderPayload {
  ok: boolean;
  projectId?: string;
  prompt?: string;
  budgetMode?: "free" | "standard" | "premium";
  plannerMode?: "auto" | "gemini" | "sample";
  reviewPacketUrl?: string;
  reviewDecisionUrl?: string;
  draftScenes?: DraftScenePayload[];
  sceneAssets?: SceneAssetPayload[];
  bgmAsset?: BgmAssetPayload | null;
  providerOverrides?: Record<string, string>;
  selectedPexelsVideos?: Record<string, PexelsVideoCandidate>;
  readyScenes?: number;
  totalScenes?: number;
  allReady?: boolean;
  missingSceneIds?: string[];
  rejectedSceneIds?: string[];
  reviewDecisions?: Record<string, GrokReviewDecision>;
  qualityGateRequired?: boolean;
  qualityGateReady?: boolean;
  mainSourceGate?: GrokMainSourceGate;
  qualityPendingSceneIds?: string[];
  assets?: GrokHandoffAsset[];
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
  bgmEnabled: boolean = true,
): Promise<DraftResult> {
  return _post<DraftResult>("/api/create-draft", {
    prompt, lang, tts_provider: ttsProvider, voice_gender: voiceGender,
    template_type: templateType, subtitle_style: subtitleStyle, tone,
    target_duration: targetDuration,
    bgm_enabled: bgmEnabled,
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

// ── Scene-level TTS regeneration ──

export interface RegenerateTtsResult {
  ok: boolean;
  _tts_url?: string;
  duration?: number;
  error?: string;
}

export function regenerateSceneTts(
  narration: string,
  sceneNum: number,
  lang = "ko",
  ttsProvider = "edge",
  voiceGender = "female",
): Promise<RegenerateTtsResult> {
  return _post<RegenerateTtsResult>("/api/regenerate-scene-tts", {
    narration, scene_num: sceneNum, lang, tts_provider: ttsProvider, voice_gender: voiceGender,
  }, 60_000);
}

// ── Image generation (server-side routing) ──

export interface GenerateImageResult {
  ok: boolean;
  image_url?: string;
  source?: string;
  error?: string;
}

export function generateImage(
  imagePrompt: string,
  imageSource = "",
  emotion = "neutral",
  fallbackPrompt = "",
): Promise<GenerateImageResult> {
  return _post<GenerateImageResult>("/api/generate-image", {
    image_prompt: imagePrompt,
    image_source: imageSource,
    emotion,
    fallback_prompt: fallbackPrompt,
  }, 60_000);
}

export function fetchLiveChannelTemplates(): Promise<LiveChannelTemplatesResult> {
  return _apiFetch<LiveChannelTemplatesResult>("/api/live-channel/templates", { timeout: 10_000 });
}

// ── Pexels video candidates ──

export function searchPexelsVideos(
  query: string,
  minDuration = 0,
  perPage = 8,
): Promise<SearchPexelsVideoResult> {
  return _post<SearchPexelsVideoResult>("/api/search-pexels-video", {
    query,
    min_duration: minDuration,
    per_page: perPage,
  }, 45_000);
}

export function createFreeAssetSourcingPacket(opts: {
  projectId?: string;
  templateType: TemplateType;
  draftScenes: DraftScenePayload[];
}): Promise<FreeAssetSourcingPacket> {
  return _post<FreeAssetSourcingPacket>("/api/free-assets/sourcing-packet", opts, 20_000);
}

export function fetchFreeAudioCandidates(opts: {
  templateType?: TemplateType;
  variantKey?: string;
  mood?: string;
  kind?: string;
  includeRisky?: boolean;
  limit?: number;
}): Promise<FreeAudioCandidatesResult> {
  return _post<FreeAudioCandidatesResult>("/api/free-assets/audio-candidates", opts, 20_000);
}

export function importFreeAudioAsset(opts: {
  operatorApproved: boolean;
  sourcePath?: string;
  fileBase64?: string;
  candidateId?: string;
  targetRole?: "bgm" | "sfx" | "voiceover";
  mood?: string;
  fileName?: string;
  provider?: string;
  title?: string;
  artist?: string;
  sourceUrl?: string;
  sourceLicense?: string;
  license?: string;
  licenseUrl?: string;
  attribution?: string;
  attributionRequired?: boolean;
  kind?: string;
  durationSec?: number | null;
  editNotes?: string;
  riskNote?: string;
  templateFamilies?: string[];
  operatorOwned?: boolean;
  sourceOrigin?: string;
  speaker?: string;
  recordedAt?: string;
}): Promise<FreeAudioImportResult> {
  return _post<FreeAudioImportResult>("/api/free-assets/import-audio", opts, 60_000);
}

// ── Local video command adapters (operator-approved, zero-paid) ──

export function generateLocalVideoScene(opts: {
  projectId?: string;
  sceneId: string;
  provider: LocalVideoProvider;
  prompt: string;
  title?: string;
  durationSec?: number;
  operatorApproved: boolean;
  commandOverrideApproved?: boolean;
  commandTemplate?: string[];
}): Promise<LocalVideoGenerateResult> {
  return _post<LocalVideoGenerateResult>("/api/local-video/generate-scene", opts, 920_000);
}

export function importLocalVideoFolder(opts: {
  projectId?: string;
  sourceDir: string;
  draftScenes: DraftScenePayload[];
  operatorApproved: boolean;
}): Promise<LocalVideoFolderImportResult> {
  return _post<LocalVideoFolderImportResult>("/api/local-video/import-folder", opts, 120_000);
}

// ── Grok web handoff (operator-approved browser automation, no API key) ──

export function createGrokHandoff(opts: {
  projectId?: string;
  prompt?: string;
  draftScenes: DraftScenePayload[];
  qualityGateRequired?: boolean;
  grokMainSourceRequired?: boolean;
  templateType?: TemplateType;
  tone?: TonePreset;
  lang?: string;
  targetDuration?: string;
  subtitleStyle?: string;
}): Promise<GrokHandoffResult> {
  return _post<GrokHandoffResult>("/api/grok-handoff", opts, 30_000);
}

export function getGrokHandoffStatus(projectId: string): Promise<GrokHandoffStatus> {
  return _apiFetch<GrokHandoffStatus>(`/api/grok-handoff/${encodeURIComponent(projectId)}/status`, { timeout: 10_000 });
}

export function openGrokHandoff(
  projectId: string,
  target: GrokOpenTarget = "worksheet",
  browserPreference?: "default" | "chrome" | "edge",
  sceneId?: string,
): Promise<GrokHandoffOpenResult> {
  const body = target === "both" ? { openTargets: ["worksheet", "grok"], browserPreference, sceneId } : { target, browserPreference, sceneId };
  return _post<GrokHandoffOpenResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/open-browser`, body, 15_000);
}

export function getGrokHandoffRenderPayload(projectId: string): Promise<GrokHandoffRenderPayload> {
  return _apiFetch<GrokHandoffRenderPayload>(`/api/grok-handoff/${encodeURIComponent(projectId)}/render-payload`, { timeout: 10_000 });
}

export function getGrokHandoffRenderPreviewPayload(projectId: string): Promise<GrokHandoffRenderPayload> {
  return _apiFetch<GrokHandoffRenderPayload>(`/api/grok-handoff/${encodeURIComponent(projectId)}/render-preview-payload`, { timeout: 10_000 });
}

export function getGrokAutomationPlan(projectId: string): Promise<GrokAutomationPlan> {
  return _apiFetch<GrokAutomationPlan>(`/api/grok-handoff/${encodeURIComponent(projectId)}/automation-plan`, { timeout: 10_000 });
}

export function buildGrokCompanionGuideUrl(projectId: string, sceneId?: string): string {
  const query = sceneId ? `?sceneId=${encodeURIComponent(sceneId)}` : "";
  return `${BRIDGE_URL}/api/grok-handoff/${encodeURIComponent(projectId)}/chrome-extension${query}`;
}

export function buildGrokCompanionCommandUrl(projectId: string, sceneId?: string): string {
  const params = new URLSearchParams({ operatorApproved: "true" });
  if (sceneId) params.set("sceneId", sceneId);
  return `${BRIDGE_URL}/api/grok-handoff/${encodeURIComponent(projectId)}/extension-command?${params.toString()}`;
}

export function buildGrokBookmarkletScriptUrl(projectId: string, sceneId?: string, autoGenerate = false): string {
  const params = new URLSearchParams({ operatorApproved: "true" });
  if (sceneId) params.set("sceneId", sceneId);
  if (autoGenerate) params.set("autoGenerate", "true");
  return `${BRIDGE_URL}/api/grok-handoff/${encodeURIComponent(projectId)}/bookmarklet.js?${params.toString()}`;
}

export function buildGrokBookmarkletUrl(projectId: string, sceneId?: string, autoGenerate = false): string {
  const scriptUrl = buildGrokBookmarkletScriptUrl(projectId, sceneId, autoGenerate);
  return `javascript:(()=>{const s=document.createElement('script');s.src=${JSON.stringify(scriptUrl)};s.async=true;document.documentElement.appendChild(s);})()`;
}

export function buildGrokBookmarkletConsoleSnippet(projectId: string, sceneId?: string, autoGenerate = false): string {
  const scriptUrl = buildGrokBookmarkletScriptUrl(projectId, sceneId, autoGenerate);
  return `fetch(${JSON.stringify(scriptUrl)}).then((r)=>r.text()).then((code)=>eval(code))`;
}

export function getGrokCompanionCommand(projectId: string, sceneId?: string): Promise<GrokCompanionCommand> {
  const params = new URLSearchParams({ operatorApproved: "true" });
  if (sceneId) params.set("sceneId", sceneId);
  return _apiFetch<GrokCompanionCommand>(
    `/api/grok-handoff/${encodeURIComponent(projectId)}/extension-command?${params.toString()}`,
    { timeout: 10_000 },
  );
}

export function importGrokDownloads(projectId: string, opts: {
  downloadDir: string;
  operatorApproved: boolean;
  allowNewestFallback?: boolean;
  overwrite?: boolean;
  sinceHandoff?: boolean;
}): Promise<GrokImportDownloadsResult> {
  return _post<GrokImportDownloadsResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/import-downloads`, opts, 20_000);
}

export function uploadGrokSceneMp4(projectId: string, opts: {
  sceneId: string;
  fileName: string;
  fileBase64: string;
  operatorApproved: boolean;
  overwrite?: boolean;
  preserveCandidates?: boolean;
}): Promise<GrokImportDownloadsResult> {
  return _post<GrokImportDownloadsResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/upload-mp4`, opts, 120_000);
}

export function uploadGrokSceneMp4Batch(projectId: string, opts: {
  files: Array<{
    sceneId?: string;
    fileName: string;
    fileBase64: string;
  }>;
  operatorApproved: boolean;
  overwrite?: boolean;
  preserveCandidates?: boolean;
  sceneMappingMode?: "filename-or-requested-scene" | "scene-order-full-batch" | "scene-grouped-takes";
}): Promise<GrokImportDownloadsResult> {
  return _post<GrokImportDownloadsResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/upload-mp4-batch`, opts, 300_000);
}

export function watchGrokDownloads(projectId: string, opts: {
  downloadDir: string;
  downloadDirs?: string[];
  operatorApproved: boolean;
  allowNewestFallback?: boolean;
  overwrite?: boolean;
  sinceHandoff?: boolean;
  timeoutSeconds?: number;
  pollIntervalSeconds?: number;
  stopOnImport?: boolean;
}): Promise<GrokWatchDownloadsResult> {
  const timeout = Math.max(20_000, Math.min(130_000, ((opts.timeoutSeconds ?? 45) + 10) * 1000));
  return _post<GrokWatchDownloadsResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/watch-downloads`, opts, timeout);
}

export function startGrokManualDownloadWatch(projectId: string, opts: {
  downloadDir: string;
  downloadDirs?: string[];
  operatorApproved: boolean;
  sceneId?: string;
  watchAllScenes?: boolean;
  allowNewestFallback?: boolean;
  sinceHandoff?: boolean;
  preserveCandidates?: boolean;
  stopOnImport?: boolean;
  replaceExisting?: boolean;
  sceneMappingMode?: "scene-grouped-takes" | "grouped-scene-takes" | "scene-take-groups";
  sceneGroupedTakeSize?: number;
  timeoutSeconds?: number;
  pollIntervalSeconds?: number;
}): Promise<GrokManualDownloadWatchResult> {
  return _post<GrokManualDownloadWatchResult>(
    `/api/grok-handoff/${encodeURIComponent(projectId)}/manual-download-watch`,
    opts,
    30_000,
  );
}

export function runGrokOperatorLoop(projectId: string, opts: {
  downloadDir: string;
  downloadDirs?: string[];
  operatorApproved: boolean;
  allowNewestFallback?: boolean;
  overwrite?: boolean;
  sinceHandoff?: boolean;
  timeoutSeconds?: number;
  pollIntervalSeconds?: number;
  openTargets?: Array<"worksheet" | "grok">;
  browserPreference?: "default" | "chrome" | "edge";
}): Promise<GrokOperatorRunResult> {
  const timeout = Math.max(60_000, Math.min(620_000, ((opts.timeoutSeconds ?? 240) + 20) * 1000));
  return _post<GrokOperatorRunResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/operator-run`, opts, timeout);
}

export function runGrokBrowserAutomation(projectId: string, opts: {
  sceneId: string;
  operatorApproved: boolean;
  browserAutomationApproved: boolean;
  launchBrowserApproved?: boolean;
  profileApproved?: boolean;
  submitPromptApproved?: boolean;
  preflightOnly?: boolean;
  waitForOperatorReadyApproved?: boolean;
  authKickoffApproved?: boolean;
  authProviderKickoffApproved?: boolean;
  authProviderPreference?: GrokAuthProvider;
  useDefaultChromeProfile?: boolean;
  attachDefaultChromeApproved?: boolean;
  browserProfileMode?: string;
  browserProfileDirectory?: string;
  cookieRejectApproved?: boolean;
  operatorReadyTimeoutSeconds?: number;
  operatorReadyPollIntervalSeconds?: number;
  generatePromptApproved?: boolean;
  downloadResultApproved?: boolean;
  watchDownloadsApproved?: boolean;
  allowNewestFallback?: boolean;
  overwrite?: boolean;
  sinceHandoff?: boolean;
  downloadClickTimeoutSeconds?: number;
  watchTimeoutSeconds?: number;
  watchPollIntervalSeconds?: number;
  downloadDir?: string;
  remoteDebuggingPort?: number;
  browserExecutable?: string;
  userDataDir?: string;
}): Promise<GrokBrowserAutomationResult> {
  const browserWait = Math.max(
    opts.downloadClickTimeoutSeconds ?? 0,
    opts.watchTimeoutSeconds ?? 0,
    opts.operatorReadyTimeoutSeconds ?? 0,
  );
  const timeout = Math.max(30_000, Math.min(1_850_000, (browserWait + 30) * 1000));
  return _post<GrokBrowserAutomationResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/browser-automation`, opts, timeout);
}

export function resumeGrokBrowserAutomation(projectId: string, opts: {
  operatorApproved: boolean;
  browserAutomationApproved: boolean;
  launchBrowserApproved?: boolean;
  profileApproved?: boolean;
  sceneId?: string;
  waitForOperatorReadyApproved?: boolean;
  authKickoffApproved?: boolean;
  authProviderKickoffApproved?: boolean;
  authProviderPreference?: GrokAuthProvider;
  useDefaultChromeProfile?: boolean;
  attachDefaultChromeApproved?: boolean;
  browserProfileMode?: string;
  browserProfileDirectory?: string;
  cookieRejectApproved?: boolean;
  operatorReadyTimeoutSeconds?: number;
  operatorReadyPollIntervalSeconds?: number;
  downloadClickTimeoutSeconds?: number;
  watchTimeoutSeconds?: number;
  watchPollIntervalSeconds?: number;
  downloadDir?: string;
  remoteDebuggingPort?: number;
}): Promise<GrokBrowserAutomationResult> {
  const browserWait = Math.max(
    opts.downloadClickTimeoutSeconds ?? 0,
    opts.watchTimeoutSeconds ?? 0,
    opts.operatorReadyTimeoutSeconds ?? 0,
  );
  const timeout = Math.max(30_000, Math.min(1_850_000, (browserWait + 30) * 1000));
  return _post<GrokBrowserAutomationResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/resume-automation`, opts, timeout);
}

export function focusGrokOperatorBrowser(projectId: string, opts: {
  operatorApproved: boolean;
  browserAutomationApproved: boolean;
  focusApproved: boolean;
  openGrokIfMissing?: boolean;
  remoteDebuggingPort?: number;
}): Promise<GrokOperatorFocusResult> {
  return _post<GrokOperatorFocusResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/operator-focus`, opts, 12_000);
}

export function cleanupGrokOperatorTabs(projectId: string, opts: {
  operatorApproved: boolean;
  browserAutomationApproved: boolean;
  closeDuplicatesApproved: boolean;
  preferAuthTarget?: boolean;
  keepCount?: number;
  remoteDebuggingPort?: number;
}): Promise<GrokOperatorTabCleanupResult> {
  return _post<GrokOperatorTabCleanupResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/operator-tabs/cleanup`, opts, 20_000);
}

export function startGrokBackgroundAutomation(projectId: string, opts: {
  operatorApproved: boolean;
  browserAutomationApproved: boolean;
  launchBrowserApproved?: boolean;
  profileApproved?: boolean;
  sceneId?: string;
  waitForOperatorReadyApproved?: boolean;
  authKickoffApproved?: boolean;
  authProviderKickoffApproved?: boolean;
  authProviderPreference?: GrokAuthProvider;
  useDefaultChromeProfile?: boolean;
  attachDefaultChromeApproved?: boolean;
  browserProfileMode?: string;
  browserProfileDirectory?: string;
  cookieRejectApproved?: boolean;
  generatePromptApproved?: boolean;
  downloadResultApproved?: boolean;
  watchDownloadsApproved?: boolean;
  allowNewestFallback?: boolean;
  sinceHandoff?: boolean;
  operatorReadyTimeoutSeconds?: number;
  operatorReadyPollIntervalSeconds?: number;
  downloadClickTimeoutSeconds?: number;
  watchTimeoutSeconds?: number;
  watchPollIntervalSeconds?: number;
  downloadDir?: string;
  remoteDebuggingPort?: number;
  supersedeActiveJobApproved?: boolean;
}): Promise<GrokBrowserAutomationResult> {
  return _post<GrokBrowserAutomationResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/background-automation`, opts, 30_000);
}

export function saveGrokReviewDecision(projectId: string, opts: {
  sceneId: string;
  accepted: boolean;
  selectedFileName?: string;
  firstTwoSecondHook?: boolean;
  artifactFree?: boolean;
  continuityOk?: boolean;
  captionSafe?: boolean;
  shotLockMatch?: boolean;
  sceneAssemblyOk?: boolean;
  sourceRationale?: string;
  qualityReviewNote?: string;
  captionLayoutReviewNote?: string;
  visualQualityVerdict?: string;
  shotLockEvidenceNote?: string;
  sceneAssemblyRoleNote?: string;
  continuityNote?: string;
  hookNote?: string;
  layoutVariantKey?: string;
  layoutVariantLabel?: string;
  layoutVariantNote?: string;
  thumbnailReviewNote?: string;
  audioMixReviewNote?: string;
  platformComparisonNote?: string;
  sourceProvenanceConfirmed?: boolean;
  sourceProvenanceNote?: string;
  selectedCandidateSummary?: string;
  singleCandidateJustification?: string;
  operatorNote?: string;
}): Promise<GrokReviewDecisionResult> {
  return _post<GrokReviewDecisionResult>(`/api/grok-handoff/${encodeURIComponent(projectId)}/review-decision`, opts, 15_000);
}

// ── Zero-paid render smoke path ──

export function renderSmoke(opts: {
  prompt: string;
  budgetMode?: "free" | "standard" | "premium";
  plannerMode?: "auto" | "gemini" | "sample";
  projectId?: string;
  sceneAssets?: SceneAssetPayload[];
  bgmAsset?: BgmAssetPayload | null;
  providerOverrides?: Record<string, string>;
  draftScenes?: DraftScenePayload[];
  selectedPexelsVideos?: Record<string, PexelsVideoCandidate>;
  subtitleStyle?: string;
  bgmEnabled?: boolean;
  templateType?: TemplateType;
}): Promise<RenderSmokeResult> {
  return _post<RenderSmokeResult>("/api/render-smoke", {
    budgetMode: "free",
    plannerMode: "sample",
    ...opts,
  }, 900_000);
}

export function finalizeRender(opts: {
  outputPath: string;
  qualityReportPath?: string;
  projectId?: string;
  requireChannelReady?: boolean;
  requireTopTier?: boolean;
}): Promise<PublishPacketResult> {
  return _post<PublishPacketResult>("/api/finalize-render", opts, 60_000);
}

export function auditFinalVideoLibrary(limit = 20): Promise<FinalVideoLibraryAuditResult> {
  return _apiFetch<FinalVideoLibraryAuditResult>(
    `/api/final-video-library/audit?limit=${encodeURIComponent(String(limit))}`,
    { timeout: 60_000 },
  );
}

export interface GateCheckResult {
  status?: string;
  detail?: string;
}

export interface GateEvaluationReport {
  schema?: string;
  status?: string;
  topicReady?: boolean;
  dryrunAllowed?: boolean;
  finalAllowed?: boolean;
  selectedTopicId?: string;
  selectedScore?: number;
  minimumScore?: number;
  failedChecks?: string[];
  checks?: Record<string, GateCheckResult>;
  computedScores?: Record<string, number>;
  [key: string]: unknown;
}

export interface GateUxCheckSummary {
  key: string;
  label: string;
  status?: string;
  detail?: string;
  rawDetail?: string;
}

export interface GateUxSummary {
  title?: string;
  statusLabel?: string;
  primaryMessage?: string;
  nextAction?: string;
  failedChecks?: Array<{ key: string; label: string }>;
  checkSummaries?: GateUxCheckSummary[];
}

export interface GateEvaluationResult {
  ok: boolean;
  gate?: string;
  status?: string;
  ready?: boolean;
  finalReady?: boolean;
  failedChecks?: string[];
  ux?: GateUxSummary;
  report?: GateEvaluationReport;
  error?: string;
}

export interface HotTopicCandidate {
  id: string;
  label: string;
  title: string;
  centralQuestion: string;
  whyHot: string;
  viewerPromise: string;
  searchSeed: string;
  first30SecPromise: string;
  score: number;
  evidencePlan: string[];
  sourceRefs?: string[];
  sourceStatus?: string;
  sourceUrl?: string;
  publishedAt?: string;
}

export interface HotTopicSourceLedgerEntry {
  sourceId: string;
  sourceType: string;
  title: string;
  url: string;
  capturedAt: string;
  observation: string;
}

export interface HotTopicQueryPlanEntry {
  provider: string;
  surface: string;
  query: string;
  intent: string;
  capturedAt: string;
}

export interface HotTopicCandidatesResult {
  ok: boolean;
  mode?: "auto-hot-topic" | "keyword-filtered" | string;
  source?: string;
  live?: boolean;
  warning?: string;
  seed?: string;
  fetchedAt?: string;
  candidates?: HotTopicCandidate[];
  sourceLedger?: HotTopicSourceLedgerEntry[];
  researchQueryPlan?: HotTopicQueryPlanEntry[];
  operatorWarning?: string;
  error?: string;
}

export function fetchHotTopicCandidates(seed = "", limit = 3): Promise<HotTopicCandidatesResult> {
  return _apiFetch<HotTopicCandidatesResult>(
    `/api/topic-discovery/hot-candidates${_buildQuery({ seed, limit })}`,
    { timeout: 20_000 },
  );
}

export function evaluateTopicDiscoveryGate(packet: Record<string, unknown>): Promise<GateEvaluationResult> {
  return _post<GateEvaluationResult>("/api/gates/topic-discovery/evaluate", { packet }, 60_000);
}

export function evaluateLongformDryrunGate(packet: Record<string, unknown>): Promise<GateEvaluationResult> {
  return _post<GateEvaluationResult>("/api/gates/longform-dryrun/evaluate", { packet }, 60_000);
}

export interface EpisodeSourceLibraryAsset {
  assetId: string;
  provider: string;
  assetKind: string;
  sceneId: string;
  cutId?: string;
  batchId?: string;
  fileName: string;
  path: string;
  sourceUrl?: string;
  currentUrl?: string;
  prompt?: string;
  model?: string;
  createdAt?: string;
  proofMode?: string;
  provenancePath?: string;
  thumbnailPath?: string;
  thumbnailUrl?: string;
  thumbnailVisible?: boolean;
  review?: {
    status?: string;
    accepted?: boolean;
    sourceGateStatus?: string;
    sourceGateReady?: boolean;
    acceptedSourceMapPath?: string;
  };
  provenance?: {
    provider?: string;
    timestamp?: string;
    proofMode?: string;
    browserSurface?: string;
    eventType?: string;
    eventStatus?: string;
    usesApi?: boolean;
    usesPaidApi?: boolean;
    downloadAuthority?: string;
  };
}

export interface EpisodeSourceLibrary {
  schema: string;
  episodeId: string;
  updatedAt?: string;
  assetCount: number;
  assets: EpisodeSourceLibraryAsset[];
}

export interface EpisodeSourceLibraryResult {
  ok: boolean;
  episodeId: string;
  sourceLibrary: EpisodeSourceLibrary;
  sourceLibraryPath?: string;
  error?: string;
}

export interface EpisodeSourceLibraryReviewResult {
  ok: boolean;
  episodeId?: string;
  status?: string;
  sourceGateReady?: boolean;
  validation?: {
    acceptedMotionCount?: number;
    acceptedReferenceCount?: number;
    totalBeatCount?: number;
    errors?: Array<{ field?: string; message?: string }>;
  };
  asset?: EpisodeSourceLibraryAsset;
  acceptedSourceMapPath?: string;
  error?: string;
}

export function fetchEpisodeSourceLibrary(episodeId: string): Promise<EpisodeSourceLibraryResult> {
  return _apiFetch<EpisodeSourceLibraryResult>(
    `/api/episodes/${encodeURIComponent(episodeId)}/source-library`,
    { timeout: 20_000 },
  );
}

export function reviewEpisodeSourceAsset(episodeId: string, opts: {
  operatorApproved: boolean;
  assetId: string;
  accepted: boolean;
  storyboardMatch?: boolean;
  firstSecondAction?: boolean;
  artifactFree?: boolean;
  captionSafe?: boolean;
  phoneSizeWatch?: boolean;
  sourceProvenanceOk?: boolean;
  noGenericBroll?: boolean;
  sourceRationale?: string;
  qualityReviewNote?: string;
  rejectionReason?: string;
}): Promise<EpisodeSourceLibraryReviewResult> {
  return _post<EpisodeSourceLibraryReviewResult>(
    `/api/episodes/${encodeURIComponent(episodeId)}/source-library/review`,
    opts,
    20_000,
  );
}

export function materializeFinalLibraryEvidenceTemplates(opts: {
  projectId?: string;
  limit?: number;
} = {}): Promise<EvidenceTemplateMaterializeResult> {
  return _post<EvidenceTemplateMaterializeResult>(
    "/api/final-video-library/evidence-templates",
    opts,
    60_000,
  );
}

export function captureFinalLibraryDashboardSmoke(opts: {
  projectId?: string;
  limit?: number;
  surface?: string;
  browserRendered?: boolean;
  bridgeConnected?: boolean;
  finalLibraryPanelVisible?: boolean;
  preUploadReady?: boolean;
  visibleTexts?: string[];
  url?: string;
  userAgent?: string;
} = {}): Promise<FinalLibraryDashboardSmokeResult> {
  return _post<FinalLibraryDashboardSmokeResult>(
    "/api/final-video-library/dashboard-smoke",
    opts,
    60_000,
  );
}

export function prepareFinalLibraryPhoneReviewEvidence(opts: {
  projectId?: string;
  limit?: number;
  audioDevice?: string;
  headphonesUsed?: boolean;
  bgmVoiceBalancePass?: boolean;
  voiceoverPolicyPass?: boolean;
  bgmNonPlaceholderPass?: boolean;
  audioMixReviewPass?: boolean;
} = {}): Promise<FinalLibraryPhoneReviewEvidenceResult> {
  return _post<FinalLibraryPhoneReviewEvidenceResult>(
    "/api/final-video-library/phone-review-evidence",
    opts,
    120_000,
  );
}

export function prepareFinalLibraryFreshSourceEvidence(opts: {
  projectId?: string;
  limit?: number;
} = {}): Promise<FinalLibraryFreshSourceEvidenceResult> {
  return _post<FinalLibraryFreshSourceEvidenceResult>(
    "/api/final-video-library/fresh-source-evidence",
    opts,
    60_000,
  );
}

export function materializeFreshSourceIntakePacket(opts: {
  projectId?: string;
  sceneId?: string;
} = {}): Promise<FreshSourceIntakeMaterializeResult> {
  return _post<FreshSourceIntakeMaterializeResult>(
    "/api/final-video-library/fresh-source-intake",
    opts,
    60_000,
  );
}

export function materializeSourceRecoveryAcceptancePacket(opts: {
  projectId?: string;
  sceneId?: string;
} = {}): Promise<SourceRecoveryAcceptanceMaterializeResult> {
  return _post<SourceRecoveryAcceptanceMaterializeResult>(
    "/api/final-video-library/source-recovery-acceptance",
    opts,
    60_000,
  );
}

export function materializeSourceRecoveryRerenderPlan(opts: {
  projectId?: string;
  sceneId?: string;
} = {}): Promise<SourceRecoveryRerenderPlanResult> {
  return _post<SourceRecoveryRerenderPlanResult>(
    "/api/final-video-library/source-recovery-rerender-plan",
    opts,
    60_000,
  );
}

// ── Storage management ──

export interface StorageCategoryInfo {
  path: string;
  items: number;
  size_bytes: number;
  size_display: string;
}

export interface StorageStatusResult {
  ok: boolean;
  tts?: StorageCategoryInfo;
  cache?: StorageCategoryInfo;
  renders?: StorageCategoryInfo;
  thumbnails?: StorageCategoryInfo;
  capcut_drafts?: StorageCategoryInfo;
  error?: string;
}

export function getStorageStatus(): Promise<StorageStatusResult> {
  return _apiFetch<StorageStatusResult>("/api/storage/status", { timeout: 10_000 });
}

export interface CleanupCategoryResult {
  removed: number;
  freed_bytes: number;
  freed_display: string;
}

export interface CleanupResult {
  ok: boolean;
  dry_run?: boolean;
  max_age_days?: number;
  tts?: CleanupCategoryResult;
  cache?: CleanupCategoryResult;
  renders?: CleanupCategoryResult;
  thumbnails?: CleanupCategoryResult;
  capcut_drafts?: CleanupCategoryResult;
  error?: string;
}

export function cleanupStorage(maxAgeDays = 7, dryRun = false): Promise<CleanupResult> {
  return _post<CleanupResult>("/api/storage/cleanup", { max_age_days: maxAgeDays, dry_run: dryRun }, 30_000);
}

// ── URL helpers ──

export function getTtsUrl(filename: string): string {
  return `${BRIDGE_URL}/api/tts/${encodeURIComponent(filename)}`;
}

export function getBgmUrl(filename: string): string {
  return `${BRIDGE_URL}/api/bgm/${encodeURIComponent(filename)}`;
}

// ── Usage stats ──

export interface UsageStatSession {
  calls: number;
  cost_usd: number;
}

export interface UsageLimitDaily {
  cycle: "daily";
  used: number;
  limit: number;
  remaining: number;
  reset_at: string;
}

export interface UsageLimitHourlyMonthly {
  cycle: "hourly+monthly";
  used_hour: number;
  limit_hour: number;
  used_month: number;
  limit_month: number;
  reset_at_hour?: string;
}

export interface UsageLimitMonthly {
  cycle: "monthly";
  used_chars: number;
  limit_chars: number;
}

export interface UsageLimitNone {
  cycle: "none";
  total_calls: number;
  total_cost_usd: number;
}

export type UsageLimitEntry =
  | UsageLimitDaily
  | UsageLimitHourlyMonthly
  | UsageLimitMonthly
  | UsageLimitNone;

export interface UsageStats {
  ok: boolean;
  session_id: string;
  session: Record<string, UsageStatSession>;
  limits: Record<string, UsageLimitEntry>;
  monthly_total_cost_usd: number;
  error?: string;
}

export function fetchUsageStats(): Promise<UsageStats> {
  return _apiFetch<UsageStats>("/api/usage-stats", { timeout: 10_000 });
}

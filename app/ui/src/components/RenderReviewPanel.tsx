import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Clipboard, ExternalLink, FileVideo, Gauge, Layers3, Music2, RefreshCw, Sparkles, Subtitles, XCircle } from "lucide-react";
import { useStudioState } from "../context/StudioContext";
import { auditFinalVideoLibrary, captureFinalLibraryDashboardSmoke, finalizeRender, materializeFinalLibraryEvidenceTemplates, materializeFreshSourceIntakePacket, materializeSourceRecoveryAcceptancePacket, materializeSourceRecoveryRerenderPlan, prepareFinalLibraryFreshSourceEvidence, prepareFinalLibraryPhoneReviewEvidence } from "../lib/bridge";
import type {
  EvidenceTemplateMaterializeResult,
  FinalVideoLibraryAuditResult,
  FinalLibraryDashboardSmokeResult,
  FinalLibraryFreshSourceEvidenceResult,
  FinalLibraryPhoneReviewEvidenceResult,
  FreshSourceIntakeMaterializeResult,
  PexelsReplacementResearch,
  ProductionReviewScene,
  PublishPacketResult,
  QualityGateSystem,
  RenderQualityCheck,
  SourceRecoveryAcceptanceMaterializeResult,
  SourceRecoveryRerenderPlanResult,
  SourceRecoveryAcceptanceStatus,
  SourceRecoveryPlan,
  StockCandidateCurationEvidence,
} from "../lib/bridge";

const CHECK_LABELS: Record<string, string> = {
  outputSpec: "1080x1920 / 30fps / audio",
  noPlaceholders: "placeholder 없음",
  movingClipPriority: "영상 클립 우선",
  sourceMotionEvidence: "소스 MP4 motion 증거",
  zeroPaidProviders: "유료 provider 없음",
  captionSafePresets: "자막 safe preset",
  subtitleArtifact: "자막 파일",
  manualSelectionEvidence: "수동 선택 근거",
  continuityEvidence: "씬 연속성 메모",
  firstTwoSecondHook: "첫 2초 hook",
  cutDensityPacing: "컷 밀도/페이싱",
  aiSlopVisualFit: "AI slop/아티팩트",
  stockAiClipFit: "stock/AI 컷 적합도",
  thumbnailFirstFrameStrength: "썸네일/첫 프레임",
  stockOnlyCaveat: "stock-only caveat",
  ttsNarrationEvidence: "TTS 내레이션",
  voicePolicyCompliance: "템플릿 voice policy",
  captionLayoutReview: "자막 레이아웃 검수",
  assetReuseDiversity: "에셋 반복 방지",
  freeAssetProvenance: "무료 에셋 출처",
  bgmAssetRotation: "BGM 회전 근거",
  bgmSoundQuality: "BGM 음질/placeholder",
  templateSourcePlan: "템플릿 소스 계획",
  publishReadinessGate: "게시 가능성 게이트",
  channelReadinessGate: "채널 원본성 게이트",
  uploadReviewGate: "업로드 전 검수",
  topTierReadinessGate: "상위권 품질 게이트",
  stockCandidateCuration: "Pexels 후보 큐레이션",
};

const LIVE_PHONE_REVIEW_FIELDS = [
  "voiceoverPolicyPass",
  "bgmNonPlaceholderPass",
  "captionSafeZonePass",
  "mobileReadabilityPass",
  "firstTwoSecondHookPass",
  "cutDensityPass",
  "aiSlopVisualFitPass",
  "stockAiClipFitPass",
  "thumbnailFirstFramePass",
];

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function statusClass(status: string | undefined): string {
  if (status === "pass") return "pass";
  if (status === "fail") return "fail";
  return "warn";
}

function StatusIcon({ status }: { status?: string }) {
  if (status === "pass") return <CheckCircle2 size={14} />;
  if (status === "fail") return <XCircle size={14} />;
  return <AlertTriangle size={14} />;
}

function qualityScore(checks: Record<string, RenderQualityCheck>): { passed: number; total: number } {
  const entries = Object.values(checks);
  return {
    passed: entries.filter((check) => check.status === "pass").length,
    total: entries.length,
  };
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function checkPassed(check: RenderQualityCheck | undefined): boolean {
  return check?.status === "pass";
}

function checkFailed(check: RenderQualityCheck | undefined): boolean {
  return check?.status === "fail";
}

function compactListLabel(items: string[], emptyLabel: string): string {
  if (items.length === 0) return emptyLabel;
  if (items.length <= 2) return items.join(", ");
  return `${items.slice(0, 2).join(", ")} +${items.length - 2}`;
}

function visibleTextLines(element: HTMLElement | null): string[] {
  if (!element) return [];
  return element.innerText
    .split(/\n+/)
    .map((item) => item.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .slice(0, 200);
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function scalarLabel(value: unknown): string | null {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length ? trimmed : null;
  }
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  return null;
}

function issueLabels(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => scalarLabel(item))
    .filter((item): item is string => Boolean(item));
}

function shortProofValue(value: unknown): string | null {
  const label = scalarLabel(value);
  if (!label) return null;
  if (label.length <= 34) return label;
  return `${label.slice(0, 16)}...${label.slice(-8)}`;
}

function proofCheckIssueRows(checks: Record<string, unknown> | null | undefined, groupLabel = ""): string[] {
  if (!checks) return [];
  return Object.entries(checks).flatMap(([key, rawCheck]) => {
    const check = recordValue(rawCheck);
    if (!check) return [];
    const issues = issueLabels(check.issues);
    const failed = check.ok === false || check.status === "fail" || check.status === "missing" || issues.length > 0;
    if (!failed) return [];

    const detail = scalarLabel(check.detail) ?? scalarLabel(check.reason) ?? scalarLabel(check.message) ?? scalarLabel(check.status);
    const parts = [issues.length ? issues.join("; ") : detail ?? "check failed"];
    const actual = shortProofValue(check.actualSha256 ?? check.actualDigest ?? check.actual);
    const expected = shortProofValue(check.expectedSha256 ?? check.expectedDigest ?? check.expected);
    const path = shortProofValue(check.path ?? check.artifactPath ?? check.filePath);
    if (actual || expected) parts.push(`actual ${actual ?? "missing"} / expected ${expected ?? "missing"}`);
    if (path) parts.push(`path ${path}`);
    return [`${groupLabel ? `${groupLabel} ` : ""}${key}: ${parts.join(" / ")}`];
  });
}

function combinedProofCheckIssueRows(...groups: Array<[string, Record<string, unknown> | null | undefined]>): string[] {
  return groups.flatMap(([label, checks]) => proofCheckIssueRows(checks, label));
}

function ProofCheckIssues({ label, rows }: { label: string; rows: string[] }) {
  if (!rows.length) return null;
  const visibleRows = rows.slice(0, 4);
  return (
    <>
      {visibleRows.map((row, index) => (
        <p key={`${label}-${index}`} className="fail">
          {label}: {row}
        </p>
      ))}
      {rows.length > visibleRows.length ? (
        <p className="fail">
          {label}: +{rows.length - visibleRows.length} more failed proof checks
        </p>
      ) : null}
    </>
  );
}

function SourceRecoveryAcceptanceResultDetails({ result }: { result: SourceRecoveryAcceptanceMaterializeResult | null }) {
  if (!result) return null;
  return (
    <>
      <p className={result.ok ? "warn" : "fail"}>
        source recovery acceptance: {result.ok ? "written, not proof" : result.error || "failed"}
      </p>
      {result.path ? <p>acceptance file: {result.path}</p> : null}
      {typeof result.sourceRecoveryScenes === "number" ? (
        <p>
          acceptance scenes: {result.sourceRecoveryScenes} / blockers {result.renderBlockerCount ?? 0}
        </p>
      ) : null}
      {result.acceptanceScenes?.length ? (
        <p>
          first acceptance lane: {result.acceptanceScenes[0]?.sceneId || "scene"} /{" "}
          {result.acceptanceScenes[0]?.recommendedLane || "source-recovery"}
        </p>
      ) : null}
      {result.sourceRecoveryBoundary ? <p>{result.sourceRecoveryBoundary}</p> : null}
      {result.goalBoundary ? <p>{result.goalBoundary}</p> : null}
    </>
  );
}

function SourceRecoveryRerenderPlanResultDetails({ result }: { result: SourceRecoveryRerenderPlanResult | null }) {
  if (!result) return null;
  return (
    <>
      <p className={result.ok ? "warn" : "fail"}>
        source recovery rerender plan: {result.ok ? "written, not proof" : result.error || result.status || "failed"}
      </p>
      {result.path ? <p>rerender plan file: {result.path}</p> : null}
      {result.sourceRecoveryAcceptanceStatus?.status ? (
        <p>
          acceptance gate: {result.sourceRecoveryAcceptanceStatus.status}
          {typeof result.sourceRecoveryAcceptanceBlockerCount === "number"
            ? ` / blockers ${result.sourceRecoveryAcceptanceBlockerCount}`
            : ""}
        </p>
      ) : null}
      {result.requiredArtifactPath ? <p>required acceptance file: {result.requiredArtifactPath}</p> : null}
      {typeof result.acceptedReplacementCount === "number" ? (
        <p>
          accepted replacements: {result.acceptedReplacementCount}/{result.totalScenes ?? result.acceptedSceneCount ?? 0}
        </p>
      ) : null}
      {result.sceneReplacements?.length ? (
        <p>
          first replacement: {result.sceneReplacements[0]?.sceneId || "scene"} /{" "}
          {result.sceneReplacements[0]?.acceptedReplacementFileName || "accepted source"}
        </p>
      ) : null}
      {result.goalBoundary ? <p>{result.goalBoundary}</p> : null}
    </>
  );
}

async function writeClipboardText(value: string): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
  } catch {
    // Fall back to a temporary textarea for browsers that deny Clipboard API.
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
}

function copyText(value: string | undefined) {
  if (!value) return;
  void writeClipboardText(value);
}

function GrokObservedPostDirectImportActions({
  observedPostUrl,
  scriptUrl,
  proofMonitorUrl,
}: {
  observedPostUrl?: string | null;
  scriptUrl?: string | null;
  proofMonitorUrl?: string | null;
}) {
  const [copyStatus, setCopyStatus] = useState<"idle" | "copying" | "copied" | "failed">("idle");
  const canCopy = Boolean(scriptUrl);

  const handleCopyAndOpen = useCallback(async () => {
    if (observedPostUrl) {
      window.open(observedPostUrl, "_blank", "noopener,noreferrer");
    }
    if (!scriptUrl) {
      setCopyStatus("failed");
      return;
    }
    setCopyStatus("copying");
    try {
      const response = await fetch(scriptUrl, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const script = await response.text();
      await writeClipboardText(script);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
  }, [observedPostUrl, scriptUrl]);

  if (!observedPostUrl && !proofMonitorUrl && !scriptUrl) return null;

  return (
    <div className="grok-direct-import-actions">
      <button className="render-publish-btn" type="button" onClick={handleCopyAndOpen} disabled={!canCopy || copyStatus === "copying"}>
        {copyStatus === "copying" ? <RefreshCw size={14} className="spin" /> : <Clipboard size={14} />}
        {copyStatus === "copied" ? "Console copied" : "Copy console + open Grok post"}
      </button>
      {observedPostUrl ? (
        <a className="render-publish-btn" href={observedPostUrl} target="_blank" rel="noreferrer">
          <ExternalLink size={14} />
          Open Grok post
        </a>
      ) : null}
      {proofMonitorUrl ? (
        <a className="render-publish-btn" href={proofMonitorUrl} target="_blank" rel="noreferrer">
          <Gauge size={14} />
          Proof monitor
        </a>
      ) : null}
      {copyStatus === "failed" ? <small>Copy failed. Open the proof monitor and copy the console snippet there.</small> : null}
    </div>
  );
}

function sourceLabel(item: ProductionReviewScene): string {
  return String(item.sourceIntent || item.visualProvider || item.visualKind || "media");
}

function readinessLabel(status: string | undefined): string {
  if (status === "ready") return "ready";
  if (status === "blocked") return "blocked";
  return "needs rework";
}

function readinessClass(status: string | undefined): string {
  if (status === "ready") return "pass";
  if (status === "blocked") return "fail";
  return "warn";
}

function channelReadinessLabel(status: string | undefined): string {
  if (status === "channel-ready") return "channel ready";
  if (status === "needs-original-footage") return "needs original footage";
  if (status === "needs-hero-original-footage") return "needs hero original footage";
  if (status === "needs-publish-rework") return "publish rework first";
  if (status === "blocked") return "blocked";
  return "needs review";
}

function channelReadinessClass(status: string | undefined): string {
  if (status === "channel-ready") return "pass";
  if (status === "blocked") return "fail";
  return "warn";
}

function uploadReviewLabel(status: string | undefined): string {
  if (status === "ready") return "upload ready";
  if (status === "needs-manual-review") return "manual review";
  if (status === "blocked") return "blocked";
  return "needs review";
}

function uploadReviewClass(status: string | undefined): string {
  if (status === "ready") return "pass";
  if (status === "blocked") return "fail";
  return "warn";
}

function topTierLabel(status: string | undefined): string {
  if (status === "top-tier-ready") return "top-tier ready";
  if (status === "needs-publish-rework") return "publish rework first";
  if (status === "needs-channel-evidence") return "channel evidence first";
  if (status === "needs-original-source-mix") return "needs original source mix";
  if (status === "needs-upload-review") return "upload review first";
  if (status === "needs-quality-review") return "review Grok/local hero";
  if (status === "needs-top-tier-evidence") return "needs top-tier evidence";
  if (status === "needs-top-tier-review") return "needs final review";
  return "needs Grok/local hero";
}

function topTierClass(status: string | undefined): string {
  if (status === "top-tier-ready") return "pass";
  if (status === "needs-original-source-mix" || status === "needs-publish-rework" || status === "needs-upload-review") return "fail";
  return "warn";
}

function libraryAuditClass(audit: FinalVideoLibraryAuditResult): string {
  if (!audit.ok) return "fail";
  if ((audit.counts?.topTierReady ?? 0) > 0) return "pass";
  return "warn";
}

function libraryPacketDecision(packet: FinalVideoLibraryAuditResult["bestPacket"] | null | undefined): {
  status: "packet" | "edit" | "rerender";
  label: string;
  detail: string;
} {
  const summary = packet?.summary ?? {};
  const packetContentReady = packet?.publishPacketAudit?.ready === true || summary.publishPacketContentReady === true;
  if (packet?.hasFinalMp4 && packet?.hasQualityAudit && packetContentReady && summary.uploadReady && summary.channelReady) {
    return {
      status: "packet",
      label: "패킷 준비",
      detail: "artifact packet is ready; same-day upload still follows the today upload/pre-upload decision",
    };
  }
  if (!packet?.hasFinalMp4 || !packet?.ffprobe?.specReady) {
    return { status: "rerender", label: "재렌더 필요", detail: "final MP4 or 1080x1920/30fps/audio proof missing" };
  }
  if (!packetContentReady) {
    return {
      status: "edit",
      label: "수정 필요",
      detail: `publish packet incomplete: ${(packet?.publishPacketAudit?.missingFields || summary.missingPublishPacketFields || []).join(", ") || "required fields missing"}`,
    };
  }
  return { status: "edit", label: "수정 필요", detail: summary.benchmarkGap || "packet exists but readiness or manual review is incomplete" };
}

function operatorDecisionClass(status: string | undefined): string {
  if (status === "upload") return "pass";
  if (status === "rerender") return "fail";
  return "warn";
}

function goalReadinessClass(status: string | undefined): string {
  if (status === "pass" || status === "complete") return "pass";
  if (status === "missing" || status === "blocked" || status === "fail" || status === "rerender") return "fail";
  return "warn";
}

function goalReadinessLabel(goalComplete: boolean | undefined, overallStatus: string | undefined): string {
  if (goalComplete) return "operating Goal complete";
  if (!overallStatus) return "strict gate unchecked";
  if (overallStatus === "complete") return "operating Goal complete";
  if (overallStatus === "artifact-gate-ready") return "artifact gate ready / Goal active";
  return `strict gate ${overallStatus}`;
}

function gateSystemClass(status: string | undefined): string {
  if (status === "pass" || status === "ready" || status === "complete" || status === "upload") return "pass";
  if (status === "blocked" || status === "fail" || status === "missing" || status === "rerender") return "fail";
  return "warn";
}

function QualityGateSystemPanel({
  title,
  gateSystem,
}: {
  title: string;
  gateSystem?: QualityGateSystem | null;
}) {
  if (!gateSystem) return null;
  const phaseStates = gateSystem.phaseStates ?? [];
  const blockingKey = gateSystem.blockingPhaseKey || "none";
  const renderSummary = gateSystem.renderQualitySummary;
  const finalSummary = gateSystem.finalReadinessSummary;
  const contractSummary = gateSystem.contractSummary;
  const iterationSummary = gateSystem.qualityIterationSummary;
  const failedRenderKeys = renderSummary?.failedOrMissingKeys ?? [];
  const warnRenderKeys = renderSummary?.warnKeys ?? [];
  const blockingFinalKeys = finalSummary?.blockingGateKeys ?? [];
  const contractKeys = contractSummary?.requiredContractKeys ?? [];

  return (
    <div>
      <span>{title}</span>
      <div className="render-library-inline-panel">
        <p className={gateSystemClass(gateSystem.status)}>
          {gateSystem.surface || "gate-system"}: {gateSystem.status || "unchecked"} / blocking phase {blockingKey}
        </p>
        {gateSystem.systemVersion ? <p>system: {gateSystem.systemVersion}</p> : null}
        {phaseStates.slice(0, 6).map((phase) => (
          <p key={phase.phaseKey || phase.source || phase.status} className={gateSystemClass(phase.status)}>
            {phase.phaseKey || "phase"}: {phase.status || "unchecked"}
            {phase.blocking ? " / blocks" : ""}
            {phase.detail ? ` - ${phase.detail}` : ""}
          </p>
        ))}
        {contractSummary ? (
          <p>
            contracts {contractSummary.requiredContractCount ?? contractKeys.length}: {compactListLabel(contractKeys, "0")}
          </p>
        ) : null}
        {renderSummary ? (
          <p className={failedRenderKeys.length ? "fail" : warnRenderKeys.length ? "warn" : "pass"}>
            render QA {renderSummary.checkCount ?? 0}: fail/missing {compactListLabel(failedRenderKeys, "0")} / warn{" "}
            {compactListLabel(warnRenderKeys, "0")}
          </p>
        ) : null}
        {finalSummary ? (
          <p className={blockingFinalKeys.length ? "fail" : "pass"}>
            final readiness {finalSummary.gateCount ?? 0}: blocking {compactListLabel(blockingFinalKeys, "0")} / pre-upload{" "}
            {finalSummary.preUploadReady ? "ready" : "blocked"}
          </p>
        ) : null}
        {iterationSummary ? (
          <>
            <p className={iterationSummary.requiresMutationResolution ? "fail" : "warn"}>
              iteration {iterationSummary.iterationCount ?? 0}: {iterationSummary.nextRequiredActionStatus || "unchecked"}
              {iterationSummary.latestStage ? ` / ${iterationSummary.latestStage}` : ""}
            </p>
            {iterationSummary.observedFailure ? <p>failure: {iterationSummary.observedFailure}</p> : null}
            {iterationSummary.nextRequiredActionSummary ? <p>next mutation: {iterationSummary.nextRequiredActionSummary}</p> : null}
            {iterationSummary.evidencePaths?.length ? <p>evidence: {compactListLabel(iterationSummary.evidencePaths, "0")}</p> : null}
          </>
        ) : null}
      </div>
    </div>
  );
}

function stockCurationClass(curation: StockCandidateCurationEvidence | null | undefined): string {
  if (curation?.ready === true) return "pass";
  return "warn";
}

function stockCurationLabel(curation: StockCandidateCurationEvidence | null | undefined): string {
  if (!curation) return "unchecked";
  if (curation.ready === true) return "ready";
  if (curation.ready === false) return "needs proof";
  return curation.status || "not recorded";
}

function pexelsReplacementClass(research: PexelsReplacementResearch | null | undefined): string {
  if (!research?.available) return "warn";
  if (research.uploadReady === true && (research.uploadReadyCandidates ?? 0) > 0) return "pass";
  if ((research.failedDirectUseCandidates ?? 0) > 0 || (research.uploadReadyCandidates ?? 0) === 0) return "fail";
  return "warn";
}

function pexelsReplacementLabel(research: PexelsReplacementResearch | null | undefined): string {
  if (!research?.available) return "missing";
  if (research.uploadReady === true && (research.uploadReadyCandidates ?? 0) > 0) return "reviewed";
  if ((research.uploadReadyCandidates ?? 0) === 0) return "not upload-ready";
  return research.status || "source triage";
}

function SourceRecoveryPlanDetails({
  plan,
  acceptance,
}: {
  plan: SourceRecoveryPlan | null | undefined;
  acceptance?: SourceRecoveryAcceptanceStatus | null;
}) {
  if (!plan?.available) {
    return <p>Run final-library audit after source review to build the recovery plan.</p>;
  }

  return (
    <>
      <p className={plan.totalScenes ? "fail" : "pass"}>
        {plan.status || "unchecked"} / render {plan.directRenderAllowed ? "allowed" : "blocked"}
      </p>
      <p>
        local review {plan.localReviewScenes ?? 0} / selected-stock rewrite{" "}
        {plan.selectedStockRewriteAvailableScenes ?? 0} / direct-import regenerate {plan.regenerateDirectImportScenes ?? 0}
        {typeof plan.expandedPexelsSearchScenes === "number" ? ` / expanded Pexels ${plan.expandedPexelsSearchScenes}` : ""}
        {typeof plan.directImportRunwayScenes === "number" ? ` / import runway ${plan.directImportRunwayScenes}` : ""}
      </p>
      {typeof plan.renderBlockerCount === "number" ? (
        <p className={plan.renderBlockerCount ? "fail" : "pass"}>
          source recovery render blockers: {plan.renderBlockerCount} / scenes{" "}
          {compactListLabel(plan.scenesBlockingRender ?? [], "0")}
        </p>
      ) : null}
      {acceptance ? (
        <>
          <p className={acceptance.blocksRender ? "fail" : "warn"}>
            source recovery acceptance gate: {acceptance.status || "unchecked"} / accepted{" "}
            {acceptance.acceptedSceneCount ?? 0}/{acceptance.totalScenes ?? 0}
          </p>
          {acceptance.requiredArtifactPath ? <p>acceptance artifact: {acceptance.requiredArtifactPath}</p> : null}
          {acceptance.scenes?.length ? (
            <p className={acceptance.incompleteSceneCount ? "fail" : "warn"}>
              acceptance fields:{" "}
              {acceptance.scenes[0]?.sceneId || "scene"}{" "}
              {compactListLabel(acceptance.scenes[0]?.missingFields ?? [], "complete")}
            </p>
          ) : null}
          {acceptance.operatorAction ? <p>{acceptance.operatorAction}</p> : null}
        </>
      ) : null}
      {plan.latestLocalReview?.available ? (
        <p className={plan.latestLocalReview.uploadReady ? "pass" : "fail"}>
          local evidence {plan.latestLocalReview.status || "reviewed"} / reviewed{" "}
          {plan.reviewedLocalCandidateScenes ?? plan.latestLocalReview.reviewedScenes ?? 0} / failed{" "}
          {plan.failedLocalCandidateScenes ?? plan.latestLocalReview.failedScenes ?? 0}
        </p>
      ) : null}
      {plan.scenes?.slice(0, 4).map((scene) => {
        const runway = scene.directImportRunway;
        return (
          <div key={scene.sceneId || scene.selectedFileName} className="source-recovery-scene">
            <p className="warn">
              {scene.sceneId || "scene"}: {scene.recommendedLane || scene.status || "review"}
              {typeof scene.unreviewedLocalCandidateCount === "number"
                ? ` / local ${scene.unreviewedLocalCandidateCount}/${scene.localCandidateCount ?? 0}`
                : ""}
              {scene.localReview?.verdict ? ` / review ${scene.localReview.verdict}` : ""}
              {scene.selectedStockRewriteAvailable ? " / selected-stock rewrite option" : ""}
              {scene.pexelsReframeSmokeVerdict ? ` / reframe ${scene.pexelsReframeSmokeVerdict}` : ""}
            </p>
            {scene.renderBlockers?.length ? (
              <p className="fail">blocks render/proof: {compactListLabel(scene.renderBlockers, "0")}</p>
            ) : null}
            {scene.expandedPexelsSearch?.available ? (
              <div className="source-recovery-candidates">
                <p className={scene.expandedPexelsSearch.uploadReadyCandidates ? "warn" : "fail"}>
                  expanded Pexels: {scene.expandedPexelsSearch.status || "source triage"} / rewrite{" "}
                  {scene.expandedPexelsSearch.rewriteCandidateCount ?? 0}/{scene.expandedPexelsSearch.candidateCount ?? 0} / upload-ready{" "}
                  {scene.expandedPexelsSearch.uploadReadyCandidates ?? 0}
                </p>
                {scene.expandedPexelsSearch.candidates?.slice(0, 3).map((candidate) => (
                  <p key={`${candidate.pexelsId || candidate.sourcePageUrl}-${candidate.verdict || "candidate"}`}>
                    {candidate.pexelsId || "candidate"}: {candidate.verdict || "needs review"}
                    {candidate.creator ? ` / ${candidate.creator}` : ""}
                    {candidate.contactSheetPath ? ` / contact ${candidate.contactSheetPath}` : ""}
                  </p>
                ))}
                {scene.expandedPexelsSearch.reviewPath ? <p>expanded search: {scene.expandedPexelsSearch.reviewPath}</p> : null}
              </div>
            ) : null}
            {runway?.available ? (
              <>
                <p className={runway.status === "post-direct-import-ready" ? "warn" : "fail"}>
                  direct-import runway: {runway.status || "unchecked"}
                  {runway.expectedFileName ? ` / ${runway.expectedFileName}` : ""}
                </p>
                {runway.prompt?.promptPreview ? <p>prompt: {runway.prompt.promptPreview}</p> : null}
                <div className="grok-direct-import-actions">
                  {runway.prompt?.promptText ? (
                    <button className="render-publish-btn" type="button" onClick={() => copyText(runway.prompt?.promptText)}>
                      <Clipboard size={14} />
                      {runway.prompt.copyLabel || "Copy prompt"}
                    </button>
                  ) : null}
                  <GrokObservedPostDirectImportActions
                    observedPostUrl={runway.observedPostUrl}
                    scriptUrl={runway.observedPostDownloadScriptUrl}
                    proofMonitorUrl={runway.proofMonitorUrl}
                  />
                </div>
                {runway.operatorAction ? <p>{runway.operatorAction}</p> : null}
              </>
            ) : null}
          </div>
        );
      })}
      {plan.latestLocalReview?.reviewPath ? <p>local review: {plan.latestLocalReview.reviewPath}</p> : null}
      {plan.operatorAction ? <p>{plan.operatorAction}</p> : null}
    </>
  );
}

function sourceRailLabel(item: ProductionReviewScene): string {
  if (item.sourceIntent === "grok") return "Grok";
  if (["wan", "ltx-video", "hunyuan-video"].includes(String(item.sourceIntent))) return "local";
  if (item.visualProvider === "upload") return "direct";
  if (item.visualProvider === "pexels-video") return "stock";
  return sourceLabel(item);
}

function sceneReadyStatus(item: ProductionReviewScene, firstSceneId: string): "pass" | "warn" | "fail" {
  if (item.visualQualityVerdictStatus === "fail" || (item.caveats?.length ?? 0) >= 3) return "fail";
  if (
    item.visualQualityVerdictStatus === "pass" &&
    item.qualityReviewNote &&
    item.sourceRationale &&
    (item.sceneId !== firstSceneId || item.hookNote || item.captionPreset === "top-hook")
  ) {
    return "pass";
  }
  return "warn";
}

export function FinalVideoLibraryPanel({ autoLoad = false }: { autoLoad?: boolean }) {
  const [libraryAudit, setLibraryAudit] = useState<FinalVideoLibraryAuditResult | null>(null);
  const [loadingLibraryAudit, setLoadingLibraryAudit] = useState(false);
  const [evidenceTemplateResult, setEvidenceTemplateResult] = useState<EvidenceTemplateMaterializeResult | null>(null);
  const [materializingEvidenceTemplates, setMaterializingEvidenceTemplates] = useState(false);
  const [dashboardSmokeResult, setDashboardSmokeResult] = useState<FinalLibraryDashboardSmokeResult | null>(null);
  const [capturingDashboardSmoke, setCapturingDashboardSmoke] = useState(false);
  const [phoneEvidenceResult, setPhoneEvidenceResult] = useState<FinalLibraryPhoneReviewEvidenceResult | null>(null);
  const [preparingPhoneEvidence, setPreparingPhoneEvidence] = useState(false);
  const [freshSourceEvidenceResult, setFreshSourceEvidenceResult] = useState<FinalLibraryFreshSourceEvidenceResult | null>(null);
  const [preparingFreshSourceEvidence, setPreparingFreshSourceEvidence] = useState(false);
  const [freshSourceIntakeResult, setFreshSourceIntakeResult] = useState<FreshSourceIntakeMaterializeResult | null>(null);
  const [materializingFreshSourceIntake, setMaterializingFreshSourceIntake] = useState(false);
  const [sourceRecoveryAcceptanceResult, setSourceRecoveryAcceptanceResult] = useState<SourceRecoveryAcceptanceMaterializeResult | null>(null);
  const [materializingSourceRecoveryAcceptance, setMaterializingSourceRecoveryAcceptance] = useState(false);
  const [sourceRecoveryRerenderPlanResult, setSourceRecoveryRerenderPlanResult] = useState<SourceRecoveryRerenderPlanResult | null>(null);
  const [materializingSourceRecoveryRerenderPlan, setMaterializingSourceRecoveryRerenderPlan] = useState(false);
  const dashboardRef = useRef<HTMLDivElement | null>(null);

  const handleLibraryAudit = useCallback(async () => {
    setLoadingLibraryAudit(true);
    try {
      const audit = await auditFinalVideoLibrary(20);
      setLibraryAudit(audit);
    } catch (error) {
      setLibraryAudit({
        ok: false,
        error: error instanceof Error ? error.message : "library audit request failed",
      });
    } finally {
      setLoadingLibraryAudit(false);
    }
  }, []);

  useEffect(() => {
    if (!autoLoad || libraryAudit || loadingLibraryAudit) return;
    void handleLibraryAudit();
  }, [autoLoad, handleLibraryAudit, libraryAudit, loadingLibraryAudit]);

  const libraryCounts = libraryAudit?.counts ?? {};
  const libraryBest = libraryAudit?.bestPacket ?? null;
  const libraryDecision = libraryPacketDecision(libraryBest);
  const libraryNextActions = (libraryBest?.nextActions ?? []).slice(0, 4);
  const goalReadiness = libraryAudit?.goalReadiness ?? null;
  const goalRequirements = goalReadiness?.requirements ?? [];
  const operatingGoalRequirements = goalReadiness?.operatingSystemRequirements ?? [];
  const goalGaps = goalReadiness?.remainingGaps ?? [];
  const operatingDecision = goalReadiness?.operatorDecision ?? null;
  const preUploadDecision = goalReadiness?.preUploadDecision ?? null;
  const runwayChecklist = goalReadiness?.operatingRunwayChecklist ?? [];
  const runwaySummary = goalReadiness?.runwayChecklistSummary ?? null;
  const freshSourceRepeatability = goalReadiness?.freshSourceRepeatability ?? null;
  const phoneSizedHumanReview = goalReadiness?.phoneSizedHumanReview ?? null;
  const phoneReviewLiveFailureFields = (phoneSizedHumanReview?.missingFields ?? [])
    .filter((field) => LIVE_PHONE_REVIEW_FIELDS.includes(field));
  const platformAnalytics = goalReadiness?.platformAnalytics ?? null;
  const freshSourceProofIssueRows = combinedProofCheckIssueRows(
    ["artifact", freshSourceRepeatability?.evidenceArtifactChecks],
    ["digest", freshSourceRepeatability?.evidenceDigestChecks],
    [
      "required",
      {
        finalVideoDigest: freshSourceRepeatability?.finalVideoDigestCheck,
        recordedAt: freshSourceRepeatability?.recordedAtCheck,
      },
    ],
  );
  const phoneReviewProofIssueRows = combinedProofCheckIssueRows(
    ["artifact", phoneSizedHumanReview?.evidenceArtifactChecks],
    ["digest", phoneSizedHumanReview?.evidenceDigestChecks],
    [
      "required",
      {
        finalVideoDigest: phoneSizedHumanReview?.finalVideoDigestCheck,
        reviewedAt: phoneSizedHumanReview?.reviewedAtCheck,
        deviceViewport: phoneSizedHumanReview?.deviceViewportCheck,
      },
    ],
  );
  const platformAnalyticsProofIssueRows = combinedProofCheckIssueRows(
    ["artifact", platformAnalytics?.evidenceArtifactChecks],
    [
      "required",
      {
        finalVideoDigest: platformAnalytics?.finalVideoDigestCheck,
        snapshotDigest: platformAnalytics?.snapshotDigestCheck,
        sampleWindow: platformAnalytics?.sampleWindowCheck,
        nextImprovementAction: platformAnalytics?.nextImprovementActionCheck,
      },
    ],
  );
  const grokProofMonitorUrl =
    libraryAudit?.sourcePipelineStatus?.grok?.proofMonitorUrl ?? goalReadiness?.proofMonitorUrl ?? null;
  const grokObservedPostUrl =
    libraryAudit?.sourcePipelineStatus?.grok?.observedPostUrl ?? goalReadiness?.observedPostUrl ?? null;
  const grokObservedPostScriptUrl =
    libraryAudit?.sourcePipelineStatus?.grok?.observedPostDownloadScriptUrl ??
    libraryAudit?.sourcePipelineStatus?.grok?.bookmarkletDirectImport?.observedPostDownloadScriptUrl ??
    null;
  const latestGrokHandoff = libraryAudit?.sourcePipelineStatus?.grok?.latestHandoff ?? null;
  const latestHandoffMissingScenes = latestGrokHandoff?.missingScenes ?? [];
  const latestHandoffFreshness = latestGrokHandoff?.downloadFreshness ?? null;
  const latestHandoffDecision = latestGrokHandoff?.operatorDecision ?? null;
  const latestHandoffImportPreflight = latestGrokHandoff?.importPreflight ?? null;
  const latestHandoffBrowserGeneration = latestGrokHandoff?.browserGenerationProof ?? null;
  const latestHandoffReplacementBacklog = latestGrokHandoff?.replacementBacklog ?? [];
  const latestHandoffLiveFailCategories = latestGrokHandoff?.liveFailCategories ?? [];
  const grokHandoffSelection = libraryAudit?.sourcePipelineStatus?.grok?.handoffSelection ?? null;
  const grokNativeDownloadPromptPolicy = libraryAudit?.sourcePipelineStatus?.grok?.nativeDownloadPromptPolicy ?? null;
  const grokBrowserHandoffReady = Boolean(
    libraryAudit?.sourcePipelineStatus?.grok?.nextAction ||
    grokProofMonitorUrl ||
    grokObservedPostUrl ||
    latestGrokHandoff?.available,
  );
  const stockCuration = libraryAudit?.sourcePipelineStatus?.pexels?.candidateCuration ?? null;
  const stockCurationMissing = stockCuration?.missingScenes ?? [];
  const pexelsReplacementResearch = libraryAudit?.sourcePipelineStatus?.pexels?.replacementResearch ?? null;
  const sourceRecoveryPlan = libraryAudit?.sourcePipelineStatus?.sourceRecoveryPlan ?? null;
  const sourceRecoveryAcceptance = libraryAudit?.sourcePipelineStatus?.sourceRecoveryAcceptance ?? null;
  const libraryPipelineHints = [
    libraryAudit?.sourcePipelineStatus?.grok?.nextAction,
    libraryAudit?.sourcePipelineStatus?.localVideo?.nextAction,
    libraryAudit?.sourcePipelineStatus?.pexels?.nextAction,
  ].filter(Boolean) as string[];
  const preUploadNextActions =
    preUploadDecision && preUploadDecision.status !== "upload"
      ? [preUploadDecision.nextAction, preUploadDecision.detail].filter((item): item is string => Boolean(item))
      : [];
  const displayedLibraryNextActions = preUploadNextActions.length
    ? preUploadNextActions
    : (libraryNextActions.length
        ? libraryNextActions.map((item) => item.operatorAction || item.label || item.key)
        : libraryPipelineHints
      ).filter((item): item is string => Boolean(item));

  const handleEvidenceTemplates = useCallback(async () => {
    setMaterializingEvidenceTemplates(true);
    setEvidenceTemplateResult(null);
    try {
      const result = await materializeFinalLibraryEvidenceTemplates({
        projectId: libraryBest?.projectId,
        limit: 20,
      });
      setEvidenceTemplateResult(result);
      await handleLibraryAudit();
    } catch (error) {
      setEvidenceTemplateResult({
        ok: false,
        error: error instanceof Error ? error.message : "evidence template request failed",
        proofArtifactsCreated: false,
        goalComplete: false,
      });
    } finally {
      setMaterializingEvidenceTemplates(false);
    }
  }, [handleLibraryAudit, libraryBest?.projectId]);

  const handleDashboardSmoke = useCallback(async () => {
    setCapturingDashboardSmoke(true);
    setDashboardSmokeResult(null);
    try {
      const result = await captureFinalLibraryDashboardSmoke({
        projectId: libraryBest?.projectId,
        limit: 20,
        surface: "final-library-dashboard",
        browserRendered: true,
        bridgeConnected: libraryAudit?.ok === true,
        finalLibraryPanelVisible: Boolean(dashboardRef.current),
        preUploadReady: goalReadiness?.preUploadReady === true,
        visibleTexts: visibleTextLines(dashboardRef.current),
        url: window.location.href,
        userAgent: navigator.userAgent,
      });
      setDashboardSmokeResult(result);
      await handleLibraryAudit();
    } catch (error) {
      setDashboardSmokeResult({
        ok: false,
        error: error instanceof Error ? error.message : "dashboard smoke capture failed",
        proofArtifactsCreated: false,
        freshSourceProofCreated: false,
        goalComplete: false,
      });
    } finally {
      setCapturingDashboardSmoke(false);
    }
  }, [goalReadiness?.preUploadReady, handleLibraryAudit, libraryAudit?.ok, libraryBest?.projectId]);

  const handlePhoneEvidence = useCallback(async () => {
    setPreparingPhoneEvidence(true);
    setPhoneEvidenceResult(null);
    try {
      const result = await prepareFinalLibraryPhoneReviewEvidence({
        projectId: libraryBest?.projectId,
        limit: 20,
      });
      setPhoneEvidenceResult(result);
      await handleLibraryAudit();
    } catch (error) {
      setPhoneEvidenceResult({
        ok: false,
        error: error instanceof Error ? error.message : "phone evidence prep failed",
        proofArtifactsCreated: false,
        phoneReviewProofCreated: false,
        goalComplete: false,
      });
    } finally {
      setPreparingPhoneEvidence(false);
    }
  }, [handleLibraryAudit, libraryBest?.projectId]);

  const handleFreshSourceEvidence = useCallback(async () => {
    setPreparingFreshSourceEvidence(true);
    setFreshSourceEvidenceResult(null);
    try {
      const result = await prepareFinalLibraryFreshSourceEvidence({
        projectId: libraryBest?.projectId,
        limit: 20,
      });
      setFreshSourceEvidenceResult(result);
      await handleLibraryAudit();
    } catch (error) {
      setFreshSourceEvidenceResult({
        ok: false,
        error: error instanceof Error ? error.message : "fresh-source evidence prep failed",
        proofArtifactsCreated: false,
        freshSourceProofCreated: false,
        goalComplete: false,
      });
    } finally {
      setPreparingFreshSourceEvidence(false);
    }
  }, [handleLibraryAudit, libraryBest?.projectId]);

  const handleFreshSourceIntake = useCallback(async () => {
    setMaterializingFreshSourceIntake(true);
    setFreshSourceIntakeResult(null);
    try {
      const result = await materializeFreshSourceIntakePacket({
        projectId: latestGrokHandoff?.projectId,
        sceneId: latestGrokHandoff?.nextMissingSceneId,
      });
      setFreshSourceIntakeResult(result);
      await handleLibraryAudit();
    } catch (error) {
      setFreshSourceIntakeResult({
        ok: false,
        error: error instanceof Error ? error.message : "fresh-source intake request failed",
        proofArtifactCreated: false,
        freshSourceProofCreated: false,
        goalComplete: false,
      });
    } finally {
      setMaterializingFreshSourceIntake(false);
    }
  }, [handleLibraryAudit, latestGrokHandoff?.nextMissingSceneId, latestGrokHandoff?.projectId]);

  const handleSourceRecoveryAcceptance = useCallback(async () => {
    setMaterializingSourceRecoveryAcceptance(true);
    setSourceRecoveryAcceptanceResult(null);
    try {
      const result = await materializeSourceRecoveryAcceptancePacket({
        projectId: latestGrokHandoff?.projectId,
        sceneId: latestGrokHandoff?.nextMissingSceneId,
      });
      setSourceRecoveryAcceptanceResult(result);
      await handleLibraryAudit();
    } catch (error) {
      setSourceRecoveryAcceptanceResult({
        ok: false,
        error: error instanceof Error ? error.message : "source recovery acceptance request failed",
        proofArtifactCreated: false,
        freshSourceProofCreated: false,
        goalComplete: false,
        directRenderAllowed: false,
        uploadReady: false,
      });
    } finally {
      setMaterializingSourceRecoveryAcceptance(false);
    }
  }, [handleLibraryAudit, latestGrokHandoff?.nextMissingSceneId, latestGrokHandoff?.projectId]);

  const handleSourceRecoveryRerenderPlan = useCallback(async () => {
    setMaterializingSourceRecoveryRerenderPlan(true);
    setSourceRecoveryRerenderPlanResult(null);
    try {
      const result = await materializeSourceRecoveryRerenderPlan({
        projectId: latestGrokHandoff?.projectId,
        sceneId: latestGrokHandoff?.nextMissingSceneId,
      });
      setSourceRecoveryRerenderPlanResult(result);
      await handleLibraryAudit();
    } catch (error) {
      setSourceRecoveryRerenderPlanResult({
        ok: false,
        status: "request-failed",
        error: error instanceof Error ? error.message : "source recovery rerender plan request failed",
        blockedBySourceRecoveryAcceptance: true,
        rerenderInputReady: false,
        renderExecuted: false,
        freshSourceProofCreated: false,
        goalComplete: false,
      });
    } finally {
      setMaterializingSourceRecoveryRerenderPlan(false);
    }
  }, [handleLibraryAudit, latestGrokHandoff?.nextMissingSceneId, latestGrokHandoff?.projectId]);

  return (
    <div ref={dashboardRef} className={`render-publish-gate render-library-audit final-library-dashboard ${libraryAudit ? libraryAuditClass(libraryAudit) : "warn"}`}>
      <div className="render-publish-gate-head final-library-dashboard-head">
        <div>
          <span>Final video library</span>
          <strong>
            {libraryAudit
              ? libraryAudit.ok
                ? `top-tier ${libraryCounts.topTierReady ?? 0} / channel ${libraryCounts.channelReady ?? 0}`
                : libraryAudit.error || "library audit failed"
              : "기존 final MP4 패킷 점검"}
          </strong>
        </div>
        <button className="render-publish-btn" onClick={handleLibraryAudit} disabled={loadingLibraryAudit}>
          <RefreshCw size={14} className={loadingLibraryAudit ? "spin" : undefined} />
          {loadingLibraryAudit ? "점검 중" : "점검"}
        </button>
        <button
          className="render-publish-btn"
          onClick={handleEvidenceTemplates}
          disabled={materializingEvidenceTemplates || !libraryAudit?.ok}
        >
          <Clipboard size={14} />
          {materializingEvidenceTemplates ? "템플릿 저장 중" : "증거 템플릿 저장"}
        </button>
        <button
          className="render-publish-btn"
          onClick={handleDashboardSmoke}
          disabled={capturingDashboardSmoke || !libraryAudit?.ok}
        >
          <Gauge size={14} />
          {capturingDashboardSmoke ? "Smoke 저장 중" : "Dashboard smoke 저장"}
        </button>
        <button
          className="render-publish-btn"
          onClick={handlePhoneEvidence}
          disabled={preparingPhoneEvidence || !libraryAudit?.ok}
        >
          <FileVideo size={14} />
          {preparingPhoneEvidence ? "Phone evidence 준비 중" : "Phone evidence 준비"}
        </button>
        <button
          className="render-publish-btn"
          onClick={handleFreshSourceEvidence}
          disabled={preparingFreshSourceEvidence || !libraryAudit?.ok}
        >
          <Clipboard size={14} />
          {preparingFreshSourceEvidence ? "Fresh evidence 준비 중" : "Fresh proof evidence 준비"}
        </button>
      </div>
      {libraryAudit ? (
        libraryAudit.ok ? (
          <>
            <div className="render-top-tier-summary">
              <span className={(libraryCounts.withMp4 ?? 0) > 0 ? "pass" : "warn"}>mp4 {libraryCounts.withMp4 ?? 0}</span>
              <span className={(libraryCounts.withQualityAudit ?? 0) > 0 ? "pass" : "warn"}>audit {libraryCounts.withQualityAudit ?? 0}</span>
              <span className={(libraryCounts.withPublishPacket ?? 0) > 0 ? "pass" : "warn"}>packet {libraryCounts.withPublishPacket ?? 0}</span>
              <span className={(libraryCounts.withPublishPacketContentReady ?? 0) > 0 ? "pass" : "warn"}>
                packet-ready {libraryCounts.withPublishPacketContentReady ?? 0}
              </span>
              <span className={(libraryCounts.uploadReady ?? 0) > 0 ? "pass" : "warn"}>upload {libraryCounts.uploadReady ?? 0}</span>
              <span className={(libraryCounts.topTierReady ?? 0) > 0 ? "pass" : "warn"}>top-tier {libraryCounts.topTierReady ?? 0}</span>
              <span className={grokBrowserHandoffReady ? "pass" : "warn"}>Grok browser-control</span>
              {grokNativeDownloadPromptPolicy ? (
                <span className={grokNativeDownloadPromptPolicy.blocksIfPromptAppears ? "fail" : "warn"}>
                  native download prompt {grokNativeDownloadPromptPolicy.status || "policy"}
                </span>
              ) : null}
              <span className={stockCurationClass(stockCuration)}>Pexels curation {stockCurationLabel(stockCuration)}</span>
              <span className={pexelsReplacementClass(pexelsReplacementResearch)}>
                Pexels fallback {pexelsReplacementLabel(pexelsReplacementResearch)}
              </span>
              <span className={goalReadiness?.goalComplete ? "pass" : "warn"}>
                {goalReadinessLabel(goalReadiness?.goalComplete, goalReadiness?.overallStatus)}
              </span>
              {preUploadDecision ? (
                <span className={operatorDecisionClass(preUploadDecision.status)}>
                  today upload {preUploadDecision.label || "수정 필요"}
                </span>
              ) : null}
              <span>{libraryAudit.scanned ?? 0} scanned</span>
            </div>
            <div className="render-publish-gate-lists">
              <div>
                <span>best packet</span>
                {libraryBest ? (
                  <>
                    <p>{libraryBest.projectId}</p>
                    {preUploadDecision ? (
                      <>
                        <p className={operatorDecisionClass(preUploadDecision.status)}>
                          today upload decision: {preUploadDecision.label || "수정 필요"}
                        </p>
                        {preUploadDecision.detail ? <p>{preUploadDecision.detail}</p> : null}
                      </>
                    ) : null}
                    <p className={libraryDecision.status === "packet" ? "pass" : libraryDecision.status === "rerender" ? "fail" : "warn"}>
                      artifact packet decision: {libraryDecision.label}
                    </p>
                    <p>{libraryDecision.detail}</p>
                    <p>
                      upload {libraryBest.summary?.uploadReady ? "ready" : "not ready"} / channel{" "}
                      {libraryBest.summary?.channelReady ? "ready" : "not ready"}
                    </p>
                    <p className={libraryBest.publishPacketAudit?.ready ? "pass" : "warn"}>
                      publish packet content: {libraryBest.publishPacketAudit?.status || libraryBest.summary?.publishPacketStatus || "unchecked"}
                    </p>
                    {libraryBest.publishPacketAudit?.missingFields?.length ? (
                      <p>missing packet fields: {compactListLabel(libraryBest.publishPacketAudit.missingFields, "0")}</p>
                    ) : null}
                    {libraryBest.publishPacketAudit?.operatorAction ? <p>{libraryBest.publishPacketAudit.operatorAction}</p> : null}
                    {libraryBest.summary?.benchmarkGap ? <p>{libraryBest.summary.benchmarkGap}</p> : null}
                    {libraryBest.finalVideoPath ? <p>{libraryBest.finalVideoPath}</p> : null}
                  </>
                ) : (
                  <p>No final MP4 packet found yet.</p>
                )}
              </div>
              <div>
                <span>next automation action</span>
                {displayedLibraryNextActions.slice(0, 4).map((item, index) => <p key={`${item}-${index}`}>{item}</p>)}
                {displayedLibraryNextActions.length === 0 ? (
                  <p>No pipeline hint returned. Re-run after bridge restart if the route was just added.</p>
                ) : null}
              </div>
              <div>
                <span>Grok browser-control import path</span>
                  <>
                    <p>
                      {grokBrowserHandoffReady
                        ? "browser-control handoff is available; production success still requires operator-owned local MP4 import/review"
                        : "browser-control handoff status unavailable"}
                    </p>
                    {grokNativeDownloadPromptPolicy ? (
                      <p className={grokNativeDownloadPromptPolicy.blocksIfPromptAppears ? "fail" : "warn"}>
                        native download prompt: {grokNativeDownloadPromptPolicy.status || "policy"}
                        {grokNativeDownloadPromptPolicy.reason ? ` - ${grokNativeDownloadPromptPolicy.reason}` : ""}
                      </p>
                    ) : null}
                    {libraryAudit?.sourcePipelineStatus?.grok?.nextAction ? <p>{libraryAudit.sourcePipelineStatus.grok.nextAction}</p> : null}
                    {grokProofMonitorUrl ? (
                      <p>
                        <a href={grokProofMonitorUrl} target="_blank" rel="noreferrer">
                          Open Grok proof monitor
                        </a>
                      </p>
                    ) : null}
                    {grokObservedPostUrl ? (
                      <p>
                        <a href={grokObservedPostUrl} target="_blank" rel="noreferrer">
                          Open observed Grok post
                        </a>
                      </p>
                    ) : null}
                    <GrokObservedPostDirectImportActions
                      observedPostUrl={grokObservedPostUrl}
                      scriptUrl={grokObservedPostScriptUrl}
                      proofMonitorUrl={grokProofMonitorUrl}
                    />
                    {latestGrokHandoff?.available ? (
                      <div className="render-library-inline-panel">
                        <p className={latestGrokHandoff.blocksOperatingGoal ? "warn" : "pass"}>
                          fresh handoff: {latestGrokHandoff.projectId} / {latestGrokHandoff.status || "unknown"}
                        </p>
                        {grokHandoffSelection?.preferredProductionHandoff ? (
                          <p className="warn">
                            handoff selection: using {grokHandoffSelection.selectedProjectId || latestGrokHandoff.projectId}; newer{" "}
                            {grokHandoffSelection.latestByMtimeProjectId || "unknown"} ignored
                          </p>
                        ) : null}
                        {latestHandoffDecision ? (
                          <>
                            <p className={operatorDecisionClass(latestHandoffDecision.status)}>
                              fresh handoff decision: {latestHandoffDecision.label || "수정 필요"}
                            </p>
                            {latestHandoffDecision.detail ? <p>{latestHandoffDecision.detail}</p> : null}
                          </>
                        ) : null}
                        <p>
                          imported {latestGrokHandoff.importedScenes ?? 0}/{latestGrokHandoff.totalScenes ?? 0} / accepted{" "}
                          {latestGrokHandoff.acceptedScenes ?? 0}/{latestGrokHandoff.totalScenes ?? 0} / rejected{" "}
                          {latestGrokHandoff.rejectedScenes ?? 0}
                        </p>
                        {latestHandoffLiveFailCategories.length ? (
                          <p className="warn">live fail categories: {compactListLabel(latestHandoffLiveFailCategories, "0")}</p>
                        ) : null}
                        {latestHandoffReplacementBacklog.length ? (
                          <div className="render-library-inline-panel">
                            {latestHandoffReplacementBacklog.slice(0, 4).map((item) => (
                              <p key={item.sceneId || item.selectedFileName} className="fail">
                                replace {item.sceneId || "scene"}: {compactListLabel(item.failCategories ?? [], "review failed")}
                                {typeof item.unreviewedLocalCandidateCount === "number"
                                  ? ` / local candidates ${item.unreviewedLocalCandidateCount}/${item.localCandidateCount ?? 0}`
                                  : ""}
                                {item.unreviewedLocalCandidates?.length
                                  ? ` / review ${compactListLabel(item.unreviewedLocalCandidates, "0")}`
                                  : ""}
                                {item.operatorAction ? ` - ${item.operatorAction}` : ""}
                              </p>
                            ))}
                          </div>
                        ) : null}
                        {latestHandoffImportPreflight ? (
                          <>
                            <p className={latestHandoffImportPreflight.readyForReview ? "pass" : "warn"}>
                              import preflight: ready {latestHandoffImportPreflight.readyScenes ?? 0}/
                              {latestHandoffImportPreflight.totalScenes ?? 0}, present{" "}
                              {latestHandoffImportPreflight.presentScenes ?? 0}
                            </p>
                            {latestHandoffImportPreflight.staleScenes?.length ? (
                              <p>stale imports: {compactListLabel(latestHandoffImportPreflight.staleScenes, "0")}</p>
                            ) : null}
                            {latestHandoffImportPreflight.invalidScenes?.length ? (
                              <p>ffprobe-invalid imports: {compactListLabel(latestHandoffImportPreflight.invalidScenes, "0")}</p>
                            ) : null}
                          </>
                        ) : null}
                        {latestHandoffBrowserGeneration ? (
                          <>
                            <p className={(latestHandoffBrowserGeneration.generatedScenes ?? 0) > 0 ? "warn" : "fail"}>
                              browser generated: {latestHandoffBrowserGeneration.generatedScenes ?? 0}/
                              {latestGrokHandoff.totalScenes ?? 0}, import proof:{" "}
                              {latestHandoffBrowserGeneration.doesNotSatisfyFreshSourceProof ? "not satisfied" : "review"}
                            </p>
                            {latestHandoffBrowserGeneration.generatedSceneIds?.length ? (
                              <p>generated posts: {compactListLabel(latestHandoffBrowserGeneration.generatedSceneIds, "0")}</p>
                            ) : null}
                          </>
                        ) : null}
                        {latestHandoffMissingScenes.length ? (
                          <p>missing fresh imports: {compactListLabel(latestHandoffMissingScenes, "0")}</p>
                        ) : null}
                        {latestHandoffFreshness ? (
                          <p>
                            Downloads freshness: fresh {latestHandoffFreshness.freshCandidateCount ?? 0} / old excluded{" "}
                            {latestHandoffFreshness.excludedOldCandidateCount ?? 0}
                          </p>
                        ) : null}
                        {latestHandoffDecision?.nextAction ? <p>{latestHandoffDecision.nextAction}</p> : null}
                        {latestGrokHandoff.operatorAction ? <p>{latestGrokHandoff.operatorAction}</p> : null}
                        <div className="grok-direct-import-actions">
                          {latestGrokHandoff.productionQueueUrl ? (
                            <a className="render-publish-btn" href={latestGrokHandoff.productionQueueUrl} target="_blank" rel="noreferrer">
                              <ExternalLink size={14} />
                              Production queue
                            </a>
                          ) : null}
                          {latestGrokHandoff.reviewPacketUrl ? (
                            <a className="render-publish-btn" href={latestGrokHandoff.reviewPacketUrl} target="_blank" rel="noreferrer">
                              <FileVideo size={14} />
                              Review packet
                            </a>
                          ) : null}
                          <button
                            className="render-publish-btn"
                            onClick={handleFreshSourceIntake}
                            disabled={materializingFreshSourceIntake}
                          >
                            <Clipboard size={14} />
                            {materializingFreshSourceIntake ? "Intake 저장 중" : "Fresh intake 저장"}
                          </button>
                          <button
                            className="render-publish-btn"
                            onClick={handleSourceRecoveryAcceptance}
                            disabled={materializingSourceRecoveryAcceptance || !sourceRecoveryPlan?.totalScenes}
                          >
                            <Clipboard size={14} />
                            {materializingSourceRecoveryAcceptance ? "Recovery 준비 중" : "Recovery review 준비"}
                          </button>
                          <button
                            className="render-publish-btn"
                            onClick={handleSourceRecoveryRerenderPlan}
                            disabled={materializingSourceRecoveryRerenderPlan || !sourceRecoveryPlan?.totalScenes}
                          >
                            <FileVideo size={14} />
                            {materializingSourceRecoveryRerenderPlan ? "Rerender plan 준비 중" : "Rerender plan 준비"}
                          </button>
                        </div>
                        {latestGrokHandoff.freshSourceIntakeTemplatePath ? (
                          <p>fresh intake template: {latestGrokHandoff.freshSourceIntakeTemplatePath}</p>
                        ) : null}
                        {freshSourceIntakeResult ? (
                          <>
                            <p className={freshSourceIntakeResult.ok ? "warn" : "fail"}>
                              fresh-source intake:{" "}
                              {freshSourceIntakeResult.ok ? "written, not proof" : freshSourceIntakeResult.error || "failed"}
                            </p>
                            {freshSourceIntakeResult.path ? <p>intake file: {freshSourceIntakeResult.path}</p> : null}
                            {freshSourceIntakeResult.packet?.operatorChecklist?.length ? (
                              <p>intake checklist items: {freshSourceIntakeResult.packet.operatorChecklist.length}</p>
                            ) : null}
                            {freshSourceIntakeResult.sourceRecoveryExecutionChecklist?.length ? (
                              <p>
                                recovery scenes: {freshSourceIntakeResult.sourceRecoveryExecutionChecklist.length} / first lane{" "}
                                {freshSourceIntakeResult.sourceRecoveryExecutionChecklist[0]?.recommendedLane || "source-recovery"}
                              </p>
                            ) : null}
                            {freshSourceIntakeResult.goalBoundary ? <p>{freshSourceIntakeResult.goalBoundary}</p> : null}
                          </>
                        ) : null}
                        <SourceRecoveryAcceptanceResultDetails result={sourceRecoveryAcceptanceResult} />
                        <SourceRecoveryRerenderPlanResultDetails result={sourceRecoveryRerenderPlanResult} />
                      </div>
                    ) : null}
                  </>
              </div>
              <div>
                <span>Pexels candidate curation</span>
                {stockCuration ? (
                  <>
                    <p>{stockCurationLabel(stockCuration)}</p>
                    {stockCuration.status ? <p>status: {stockCuration.status}</p> : null}
                    {stockCuration.scenes?.length ? (
                      <p>scenes: {compactListLabel(stockCuration.scenes, "0")}</p>
                    ) : null}
                    {stockCurationMissing.length ? (
                      <p>missing: {compactListLabel(stockCurationMissing, "0")}</p>
                    ) : null}
                    {stockCuration.detail ? <p>{stockCuration.detail}</p> : null}
                  </>
                ) : (
                  <p>No curation evidence returned by the audit route.</p>
                )}
                {pexelsReplacementResearch?.available ? (
                  <div className="render-library-inline-panel">
                    <p className={pexelsReplacementClass(pexelsReplacementResearch)}>
                      direct-URL fallback: {pexelsReplacementLabel(pexelsReplacementResearch)}
                    </p>
                    <p>
                      candidates {pexelsReplacementResearch.totalCandidates ?? 0} / conditional{" "}
                      {pexelsReplacementResearch.conditionalFallbackCandidates ?? 0} / direct-use fail{" "}
                      {pexelsReplacementResearch.failedDirectUseCandidates ?? 0} / upload-ready{" "}
                      {pexelsReplacementResearch.uploadReadyCandidates ?? 0}
                    </p>
                    {typeof pexelsReplacementResearch.videoOnlyNoAudioCandidates === "number" ? (
                      <p>video-only no audio: {pexelsReplacementResearch.videoOnlyNoAudioCandidates}</p>
                    ) : null}
                    {pexelsReplacementResearch.scenes?.length ? (
                      <p>fallback scenes: {compactListLabel(pexelsReplacementResearch.scenes, "0")}</p>
                    ) : null}
                    {pexelsReplacementResearch.candidates?.slice(0, 3).map((candidate) => (
                      <p key={candidate.sceneId || candidate.candidateFileName} className={candidate.uploadReady ? "pass" : "warn"}>
                        {candidate.sceneId || "scene"}: {candidate.verdict || "needs-review"}
                        {candidate.reframeSmokeVerdict ? ` / reframe ${candidate.reframeSmokeVerdict}` : ""}
                        {candidate.previousLowerEmptyAreaConcernCorrected ? " / lower-frame concern corrected" : ""}
                        {candidate.candidateFileName ? ` / ${candidate.candidateFileName}` : ""}
                      </p>
                    ))}
                    {pexelsReplacementResearch.doesNotSatisfy?.length ? (
                      <p>not proof for: {compactListLabel(pexelsReplacementResearch.doesNotSatisfy, "0")}</p>
                    ) : null}
                    {pexelsReplacementResearch.operatorAction ? <p>{pexelsReplacementResearch.operatorAction}</p> : null}
                  </div>
                ) : null}
              </div>
              <div>
                <span>Source recovery plan</span>
                <SourceRecoveryPlanDetails plan={sourceRecoveryPlan} acceptance={sourceRecoveryAcceptance} />
              </div>
              <div>
                <span>Operating goal policy</span>
                {goalReadiness ? (
                  <>
                    <p>{goalReadinessLabel(goalReadiness.goalComplete, goalReadiness.overallStatus)}</p>
                    {operatingDecision ? (
                      <>
                        <p className={operatorDecisionClass(operatingDecision.status)}>
                          live-channel decision: {operatingDecision.label || "수정 필요"}
                        </p>
                        {operatingDecision.detail ? <p>{operatingDecision.detail}</p> : null}
                        {operatingDecision.nextAction ? <p>{operatingDecision.nextAction}</p> : null}
                      </>
                    ) : null}
                    {preUploadDecision ? (
                      <>
                        <p className={operatorDecisionClass(preUploadDecision.status)}>
                          pre-upload decision: {preUploadDecision.label || "수정 필요"}
                        </p>
                        {preUploadDecision.detail ? <p>{preUploadDecision.detail}</p> : null}
                        {preUploadDecision.nextAction ? <p>{preUploadDecision.nextAction}</p> : null}
                      </>
                    ) : null}
                    <p>
                      artifact gate: {goalReadiness.artifactGateComplete ? "ready" : "incomplete"} / operating Goal:{" "}
                      {goalReadiness.operatingSystemComplete ? "complete" : "active"}
                    </p>
                    {goalReadiness.preUploadBoundary ? <p>{goalReadiness.preUploadBoundary}</p> : null}
                    {runwaySummary ? (
                      <p className={runwaySummary.readyForTodayUpload ? "pass" : "warn"}>
                        runway next: {runwaySummary.primaryBlockerLabel || "none"} - {runwaySummary.nextAction || "maintain packet evidence"}
                      </p>
                    ) : null}
                    {runwayChecklist.length ? (
                      <div className="render-library-inline-panel">
                        {runwayChecklist.map((item) => (
                          <p key={item.key || item.label} className={goalReadinessClass(item.status)}>
                            {item.label || item.key}: {item.status || "unchecked"}
                            {item.detail ? ` - ${item.detail}` : ""}
                          </p>
                        ))}
                      </div>
                    ) : null}
                    <QualityGateSystemPanel title="Unified gate system" gateSystem={goalReadiness.gateSystem ?? libraryAudit.gateSystem} />
                    {freshSourceRepeatability ? (
                      <>
                        <p className={goalReadinessClass(freshSourceRepeatability.status)}>
                          fresh-source repeatability: {freshSourceRepeatability.status || "missing"}
                        </p>
                        {freshSourceRepeatability.artifactPath ? <p>fresh-source artifact: {freshSourceRepeatability.artifactPath}</p> : null}
                        {freshSourceRepeatability.templateArtifactPath ? (
                          <p>fresh-source template: {freshSourceRepeatability.templateArtifactPath}</p>
                        ) : null}
                        {freshSourceRepeatability.missingFields?.length ? (
                          <p>missing fresh-source fields: {compactListLabel(freshSourceRepeatability.missingFields, "0")}</p>
                        ) : null}
                        {freshSourceRepeatability.failedFields?.length ? (
                          <p>failed fresh-source fields: {compactListLabel(freshSourceRepeatability.failedFields, "0")}</p>
                        ) : null}
                        <ProofCheckIssues label="fresh-source proof issue" rows={freshSourceProofIssueRows} />
                        {freshSourceRepeatability.detail ? <p>{freshSourceRepeatability.detail}</p> : null}
                        {freshSourceRepeatability.operatorAction ? <p>{freshSourceRepeatability.operatorAction}</p> : null}
                      </>
                    ) : null}
                    {phoneSizedHumanReview ? (
                      <>
                        <p className={goalReadinessClass(phoneSizedHumanReview.status)}>
                          phone-sized human review: {phoneSizedHumanReview.status || "missing"}
                        </p>
                        {phoneSizedHumanReview.artifactPath ? <p>review artifact: {phoneSizedHumanReview.artifactPath}</p> : null}
                        {phoneSizedHumanReview.templateArtifactPath ? (
                          <p>review template: {phoneSizedHumanReview.templateArtifactPath}</p>
                        ) : null}
                        {phoneSizedHumanReview.missingFields?.length ? (
                          <p>missing phone review fields: {compactListLabel(phoneSizedHumanReview.missingFields, "0")}</p>
                        ) : null}
                        {phoneReviewLiveFailureFields.length ? (
                          <p>live phone fail fields: {phoneReviewLiveFailureFields.join(", ")}</p>
                        ) : null}
                        {phoneSizedHumanReview.failedFields?.length ? (
                          <p>failed phone review fields: {compactListLabel(phoneSizedHumanReview.failedFields, "0")}</p>
                        ) : null}
                        <ProofCheckIssues label="phone review proof issue" rows={phoneReviewProofIssueRows} />
                        {phoneSizedHumanReview.detail ? <p>{phoneSizedHumanReview.detail}</p> : null}
                        {phoneSizedHumanReview.operatorAction ? <p>{phoneSizedHumanReview.operatorAction}</p> : null}
                      </>
                    ) : null}
                    {platformAnalytics ? (
                      <>
                        <p className={goalReadinessClass(platformAnalytics.status)}>
                          platform analytics: {platformAnalytics.status || "missing"}
                        </p>
                        {platformAnalytics.artifactPath ? <p>analytics artifact: {platformAnalytics.artifactPath}</p> : null}
                        {platformAnalytics.templateArtifactPath ? (
                          <p>analytics template: {platformAnalytics.templateArtifactPath}</p>
                        ) : null}
                        {platformAnalytics.missingFields?.length ? (
                          <p>missing analytics fields: {compactListLabel(platformAnalytics.missingFields, "0")}</p>
                        ) : null}
                        {platformAnalytics.failedFields?.length ? (
                          <p>failed analytics fields: {compactListLabel(platformAnalytics.failedFields, "0")}</p>
                        ) : null}
                        <ProofCheckIssues label="analytics proof issue" rows={platformAnalyticsProofIssueRows} />
                        {platformAnalytics.detail ? <p>{platformAnalytics.detail}</p> : null}
                        {platformAnalytics.operatorAction ? <p>{platformAnalytics.operatorAction}</p> : null}
                      </>
                    ) : null}
                    {goalReadiness.completionPolicy ? <p>{goalReadiness.completionPolicy}</p> : null}
                    {evidenceTemplateResult ? (
                      <>
                        <p className={evidenceTemplateResult.ok ? "warn" : "fail"}>
                          evidence templates: {evidenceTemplateResult.ok ? "written, not proof" : evidenceTemplateResult.error || "failed"}
                        </p>
                        {evidenceTemplateResult.templates?.phoneSizedHumanReview?.path ? (
                          <p>phone template file: {evidenceTemplateResult.templates.phoneSizedHumanReview.path}</p>
                        ) : null}
                        {evidenceTemplateResult.templates?.platformAnalytics?.path ? (
                          <p>analytics template file: {evidenceTemplateResult.templates.platformAnalytics.path}</p>
                        ) : null}
                        {evidenceTemplateResult.templates?.freshSourceRepeatability?.path ? (
                          <p>fresh-source template file: {evidenceTemplateResult.templates.freshSourceRepeatability.path}</p>
                        ) : null}
                        {evidenceTemplateResult.goalBoundary ? <p>{evidenceTemplateResult.goalBoundary}</p> : null}
                      </>
                    ) : null}
                    {freshSourceEvidenceResult ? (
                      <>
                        <p className={freshSourceEvidenceResult.ok ? "warn" : "fail"}>
                          fresh-source evidence:{" "}
                          {freshSourceEvidenceResult.ok
                            ? "written, not proof"
                            : freshSourceEvidenceResult.error || "failed"}
                        </p>
                        {freshSourceEvidenceResult.artifactPaths?.handoffManifestPath ? (
                          <p>fresh-source handoff draft: {freshSourceEvidenceResult.artifactPaths.handoffManifestPath}</p>
                        ) : null}
                        {freshSourceEvidenceResult.artifactPaths?.sourceReviewPath ? (
                          <p>fresh-source review draft: {freshSourceEvidenceResult.artifactPaths.sourceReviewPath}</p>
                        ) : null}
                        {typeof freshSourceEvidenceResult.reviewRequiredSceneCount === "number" ? (
                          <p>
                            review required scenes: {freshSourceEvidenceResult.reviewRequiredSceneCount} / accepted{" "}
                            {freshSourceEvidenceResult.acceptedSceneCount ?? 0}
                          </p>
                        ) : null}
                        {typeof freshSourceEvidenceResult.proofBlockerCount === "number" ? (
                          <p>
                            fresh-source proof blockers: {freshSourceEvidenceResult.proofBlockerCount} / proof-ready scenes{" "}
                            {freshSourceEvidenceResult.freshSourceProofReadySceneCount ?? 0}
                          </p>
                        ) : null}
                        {freshSourceEvidenceResult.sourceRecoveryAcceptanceStatus?.status ? (
                          <p>
                            source recovery acceptance: {freshSourceEvidenceResult.sourceRecoveryAcceptanceStatus.status}
                            {typeof freshSourceEvidenceResult.sourceRecoveryAcceptanceBlockerCount === "number"
                              ? ` / blockers ${freshSourceEvidenceResult.sourceRecoveryAcceptanceBlockerCount}`
                              : ""}
                          </p>
                        ) : null}
                        {freshSourceEvidenceResult.sourceRecoveryAcceptanceStatus?.blocksFreshSourceProof === true &&
                        freshSourceEvidenceResult.sourceRecoveryAcceptanceStatus.requiredArtifactPath ? (
                          <p>source recovery acceptance file: {freshSourceEvidenceResult.sourceRecoveryAcceptanceStatus.requiredArtifactPath}</p>
                        ) : null}
                        {freshSourceEvidenceResult.freshSourceTemplate?.path ? (
                          <p>fresh-source template file: {freshSourceEvidenceResult.freshSourceTemplate.path}</p>
                        ) : null}
                        {freshSourceEvidenceResult.goalBoundary ? <p>{freshSourceEvidenceResult.goalBoundary}</p> : null}
                      </>
                    ) : null}
                    {dashboardSmokeResult ? (
                      <>
                        <p className={dashboardSmokeResult.ok ? "warn" : "fail"}>
                          dashboard smoke:{" "}
                          {dashboardSmokeResult.ok
                            ? "browser-rendered evidence saved, not proof"
                            : dashboardSmokeResult.error || dashboardSmokeResult.issues?.join("; ") || "failed"}
                        </p>
                        {dashboardSmokeResult.path ? <p>dashboard smoke file: {dashboardSmokeResult.path}</p> : null}
                        {dashboardSmokeResult.sha256 ? <p>dashboard smoke sha256: {dashboardSmokeResult.sha256}</p> : null}
                        {dashboardSmokeResult.goalBoundary ? <p>{dashboardSmokeResult.goalBoundary}</p> : null}
                      </>
                    ) : null}
                    {phoneEvidenceResult ? (
                      <>
                        <p className={phoneEvidenceResult.ok ? "warn" : "fail"}>
                          phone evidence:{" "}
                          {phoneEvidenceResult.ok
                            ? "packet-local review evidence prepared, not proof"
                            : phoneEvidenceResult.error || phoneEvidenceResult.issues?.join("; ") || "failed"}
                        </p>
                        {phoneEvidenceResult.phoneTemplate?.path ? <p>phone template file: {phoneEvidenceResult.phoneTemplate.path}</p> : null}
                        {phoneEvidenceResult.pendingFields?.length ? (
                          <p>pending operator evidence: {compactListLabel(phoneEvidenceResult.pendingFields, "0")}</p>
                        ) : null}
                        {phoneEvidenceResult.goalBoundary ? <p>{phoneEvidenceResult.goalBoundary}</p> : null}
                      </>
                    ) : null}
                    {goalRequirements.slice(0, 5).map((item) => (
                      <p key={item.key || item.label} className={goalReadinessClass(item.status)}>
                        {item.label || item.key}: {item.status || "unknown"}
                      </p>
                    ))}
                    {operatingGoalRequirements.slice(0, 3).map((item) => (
                      <p key={item.key || item.label} className={goalReadinessClass(item.status)}>
                        {item.label || item.key}: {item.status || "unknown"}
                      </p>
                    ))}
                    {goalGaps.slice(0, 3).map((item) => <p key={item}>gap: {item}</p>)}
                    {grokProofMonitorUrl ? <p>proof monitor: {grokProofMonitorUrl}</p> : null}
                  </>
                ) : (
                  <p>Goal readiness audit unavailable.</p>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="render-publish-gate-lists">
            <div>
              <span>bridge route</span>
              <p>새 audit route가 live bridge에 아직 로드되지 않았을 수 있습니다.</p>
            </div>
            <div>
              <span>safe next step</span>
              <p>Grok background wait가 끝난 뒤 bridge를 재시작하고 다시 점검합니다.</p>
            </div>
          </div>
        )
      ) : null}
    </div>
  );
}

export default function RenderReviewPanel() {
  const { renderResult } = useStudioState();
  const [publishPacket, setPublishPacket] = useState<PublishPacketResult | null>(null);
  const [finalizingMode, setFinalizingMode] = useState<"publish" | "channel" | "top-tier" | null>(null);
  const [libraryAudit, setLibraryAudit] = useState<FinalVideoLibraryAuditResult | null>(null);
  const [loadingLibraryAudit, setLoadingLibraryAudit] = useState(false);
  const [evidenceTemplateResult, setEvidenceTemplateResult] = useState<EvidenceTemplateMaterializeResult | null>(null);
  const [materializingEvidenceTemplates, setMaterializingEvidenceTemplates] = useState(false);
  const [dashboardSmokeResult, setDashboardSmokeResult] = useState<FinalLibraryDashboardSmokeResult | null>(null);
  const [capturingDashboardSmoke, setCapturingDashboardSmoke] = useState(false);
  const [phoneEvidenceResult, setPhoneEvidenceResult] = useState<FinalLibraryPhoneReviewEvidenceResult | null>(null);
  const [preparingPhoneEvidence, setPreparingPhoneEvidence] = useState(false);
  const [freshSourceEvidenceResult, setFreshSourceEvidenceResult] = useState<FinalLibraryFreshSourceEvidenceResult | null>(null);
  const [preparingFreshSourceEvidence, setPreparingFreshSourceEvidence] = useState(false);
  const [freshSourceIntakeResult, setFreshSourceIntakeResult] = useState<FreshSourceIntakeMaterializeResult | null>(null);
  const [materializingFreshSourceIntake, setMaterializingFreshSourceIntake] = useState(false);
  const [sourceRecoveryAcceptanceResult, setSourceRecoveryAcceptanceResult] = useState<SourceRecoveryAcceptanceMaterializeResult | null>(null);
  const [materializingSourceRecoveryAcceptance, setMaterializingSourceRecoveryAcceptance] = useState(false);
  const [sourceRecoveryRerenderPlanResult, setSourceRecoveryRerenderPlanResult] = useState<SourceRecoveryRerenderPlanResult | null>(null);
  const [materializingSourceRecoveryRerenderPlan, setMaterializingSourceRecoveryRerenderPlan] = useState(false);
  const libraryDashboardRef = useRef<HTMLDivElement | null>(null);
  const result = renderResult?.renderResult;
  const autoFinalizedPacket = renderResult?.finalizeResult ?? null;
  const outputPath = result?.outputPath ?? "";
  useEffect(() => {
    setPublishPacket(autoFinalizedPacket);
    setLibraryAudit(null);
  }, [outputPath, autoFinalizedPacket]);
  if (!result?.outputPath) return null;

  const report = result.qualityReport;
  const checks = report?.checks ?? {};
  const score = qualityScore(checks);
  const summary = report?.localMediaSummary ?? result.localMediaSummary ?? {};
  const totalScenes = numberValue(summary.totalScenes);
  const uploaded = numberValue(summary.uploaded);
  const generated = numberValue(summary.generated);
  const placeholders = numberValue(summary.placeholder);
  const videoScenes = (result.localMedia ?? []).filter((item) => item.outputKind === "video").length;
  const providers = report?.providers?.length ? report.providers : [];
  const sourceRows = (result.localMedia ?? []).slice(0, 4);
  const production = report?.productionReview;
  const productionRows = production?.scenes?.slice(0, 4) ?? [];
  const productionSummary = production?.summary ?? {};
  const templateReview = production?.templateSourceReview;
  const readiness = report?.publishReadiness;
  const readinessStatus = readiness?.status;
  const readinessScore = readiness?.score;
  const requiredFixes = readiness?.requiredFixes ?? [];
  const recommendedFixes = readiness?.recommendedFixes ?? [];
  const strengths = readiness?.strengths ?? [];
  const channelReadiness = report?.channelReadiness;
  const channelStatus = channelReadiness?.status;
  const channelScore = channelReadiness?.score;
  const channelRequiredFixes = channelReadiness?.requiredFixes ?? [];
  const channelRecommendedFixes = channelReadiness?.recommendedFixes ?? [];
  const channelStrengths = channelReadiness?.strengths ?? [];
  const channelSummary = channelReadiness?.summary ?? {};
  const firstSceneId = typeof channelSummary.firstSceneId === "string" ? channelSummary.firstSceneId : "scene-01";
  const heroOriginalReady = channelSummary.heroOriginalClipReady === true;
  const heroEvidenceReady = channelSummary.heroOriginalityEvidenceReady === true;
  const heroAiOrLocalReady = channelSummary.heroAiOrLocalReady === true;
  const canPublish = readinessStatus === "ready";
  const canChannelPublish = channelStatus === "channel-ready";
  const grokHeroScenes = numberValue(productionSummary.grokHandoffScenes);
  const localHeroScenes = numberValue(productionSummary.localModelVideoScenes);
  const topTierReadiness = report?.topTierReadiness;
  const topTierReadinessStatus = topTierReadiness?.status;
  const topTierReadinessScore = topTierReadiness?.score;
  const topTierRequiredFixes = topTierReadiness?.requiredFixes ?? [];
  const topTierStrengths = topTierReadiness?.strengths ?? [];
  const topTierStatus = topTierReadinessStatus ?? (canChannelPublish && heroAiOrLocalReady
    ? "top-tier-ready"
    : heroAiOrLocalReady
      ? "needs-quality-review"
      : "needs-grok-local-hero");
  const topTierScore = topTierReadinessScore ?? {
    passed: [
      canPublish,
      canChannelPublish,
      heroOriginalReady,
      heroEvidenceReady,
      heroAiOrLocalReady,
    ].filter(Boolean).length,
    total: 5,
  };
  const fallbackTopTierGaps = [
    !canPublish ? "Publish gate must be ready before this can be treated as a finished upload candidate." : null,
    !canChannelPublish ? "Channel gate must pass before this can be treated as channel-owned final work." : null,
    !heroOriginalReady ? `First hook (${firstSceneId}) still needs an original/direct/Grok/local MP4 hero clip.` : null,
    !heroEvidenceReady ? "First hook needs prompt/source rationale and quality-review evidence." : null,
    !heroAiOrLocalReady ? "Top-tier AI-assisted benchmark gap: add a Grok app/web or local Wan/LTX/Hunyuan MP4 hero shot." : null,
  ].filter(Boolean) as string[];
  const topTierGaps = topTierRequiredFixes.length > 0 ? topTierRequiredFixes : fallbackTopTierGaps;
  const sourcePipelineStatus = report?.sourcePipelineStatus ?? publishPacket?.sourcePipelineStatus ?? libraryAudit?.sourcePipelineStatus ?? null;
  const productionMetaNarrationScenes = stringList(productionSummary.productionMetaNarrationScenes);
  const productionMetaSubtitleScenes = stringList(productionSummary.productionMetaSubtitleScenes);
  const missingNarrationScenes = stringList(productionSummary.missingNarrationScenes);
  const thinNarrationScenes = stringList(productionSummary.thinNarrationScenes);
  const captionSparsePlan = productionSummary.captionSparsePlan === true;
  const longTopHookScenes = stringList(productionSummary.longTopHookScenes);
  const missingCaptionLayoutScenes = stringList(productionSummary.missingCaptionLayoutReviewScenes);
  const missingLayoutVariantScenes = stringList(productionSummary.missingLayoutVariantScenes);
  const missingFreeAudioAssets = stringList(productionSummary.missingFreeAudioProvenanceAssets);
  const weakBgmSelectionAssets = stringList(productionSummary.weakBgmSelectionAssets);
  const placeholderBgmAssets = stringList(productionSummary.placeholderBgmAssets);
  const freeAudioAssets = stringList(productionSummary.freeAudioProvenanceAssets);
  const bgmSelectionAssets = stringList(productionSummary.bgmSelectionAssets);
  const templateName = String(templateReview?.template || productionSummary.contentTemplate || "template");
  const viewerNarrationReady = checkPassed(checks.ttsNarrationEvidence)
    && checkPassed(checks.voicePolicyCompliance)
    && productionMetaNarrationScenes.length === 0
    && productionMetaSubtitleScenes.length === 0
    && missingNarrationScenes.length === 0
    && thinNarrationScenes.length === 0;
  const captionDecisionReady = checkPassed(checks.captionLayoutReview)
    && !captionSparsePlan
    && longTopHookScenes.length === 0
    && missingCaptionLayoutScenes.length === 0;
  const audioProvenanceReady = checkPassed(checks.freeAssetProvenance)
    && checkPassed(checks.bgmAssetRotation)
    && checkPassed(checks.bgmSoundQuality)
    && missingFreeAudioAssets.length === 0
    && weakBgmSelectionAssets.length === 0
    && placeholderBgmAssets.length === 0;
  const templateDecisionReady = (templateReview?.status ?? "warn") === "pass"
    && missingLayoutVariantScenes.length === 0;
  const heroDecisionReady = topTierStatus === "top-tier-ready";
  const decisionCards = [
    {
      key: "viewer-narration",
      icon: <Sparkles size={14} />,
      status: viewerNarrationReady ? "pass" : checkFailed(checks.ttsNarrationEvidence) ? "fail" : "warn",
      title: "Viewer narration",
      value: viewerNarrationReady ? "시청자용 TTS" : "대사 재작성",
      detail: viewerNarrationReady
        ? `${stringList(productionSummary.narrationScenes).length} scene, voice policy pass`
        : `voice ${checks.voicePolicyCompliance?.status ?? "missing"} / meta ${compactListLabel([...productionMetaNarrationScenes, ...productionMetaSubtitleScenes], "0")} / thin ${thinNarrationScenes.length}`,
    },
    {
      key: "caption-layout",
      icon: <Subtitles size={14} />,
      status: captionDecisionReady ? "pass" : checkFailed(checks.captionLayoutReview) ? "fail" : "warn",
      title: "Caption layout",
      value: captionDecisionReady ? "safe preset" : "layout fix",
      detail: captionDecisionReady
        ? `caption plan ${JSON.stringify(productionSummary.captionPresetCounts ?? {})}`
        : `sparse ${captionSparsePlan ? "yes" : "no"} / long hook ${compactListLabel(longTopHookScenes, "0")}`,
    },
    {
      key: "free-audio",
      icon: <Music2 size={14} />,
      status: audioProvenanceReady ? "pass" : checkFailed(checks.freeAssetProvenance) ? "fail" : "warn",
      title: "Free BGM/SFX",
      value: audioProvenanceReady ? "provenance ready" : "source proof gap",
      detail: audioProvenanceReady
        ? compactListLabel(freeAudioAssets.length ? freeAudioAssets : bgmSelectionAssets, "sidecar ready")
        : `missing ${missingFreeAudioAssets.length} / weak ${weakBgmSelectionAssets.length} / placeholder ${placeholderBgmAssets.length}`,
    },
    {
      key: "template-mix",
      icon: <Layers3 size={14} />,
      status: templateDecisionReady ? "pass" : "warn",
      title: "Template mix",
      value: templateName,
      detail: templateDecisionReady
        ? templateReview?.sourceMix || `${stringList(productionSummary.layoutVariantScenes).length} layout variants`
        : `missing layout ${compactListLabel(missingLayoutVariantScenes, "0")}`,
    },
    {
      key: "hero-gap",
      icon: <FileVideo size={14} />,
      status: heroDecisionReady ? "pass" : "warn",
      title: "AI hero gap",
      value: heroDecisionReady ? "top-tier ready" : topTierLabel(topTierStatus),
      detail: heroDecisionReady
        ? "Grok/local hero evidence is present"
        : `Grok/local hero scenes: ${grokHeroScenes + localHeroScenes}`,
    },
  ];
  const nextProductionActions = [
    sourcePipelineStatus?.grok?.nextAction,
    sourcePipelineStatus?.localVideo?.nextAction,
    sourcePipelineStatus?.pexels?.nextAction,
    ...topTierGaps.slice(0, 2),
  ].filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  const uploadReview = report?.uploadReview;
  const uploadReviewStatus = uploadReview?.status;
  const uploadReviewScore = uploadReview?.score;
  const uploadRequiredFixes = uploadReview?.requiredFixes ?? [];
  const uploadManualItems = uploadReview?.manualReviewItems ?? [];
  const uploadStrengths = uploadReview?.strengths ?? [];
  const missingRationaleCount = productionSummary.missingRationaleScenes?.length ?? 0;
  const missingContinuityCount = productionSummary.missingContinuityScenes?.length ?? 0;
  const allChecksPass = score.total > 0 && score.passed === score.total;
  const rerenderBlockers = ["outputSpec", "noPlaceholders", "movingClipPriority", "sourceMotionEvidence", "captionDensityAndSafeZone"]
    .filter((key) => checkFailed(checks[key]));
  const operatorDecision = rerenderBlockers.length > 0 || readinessStatus === "blocked"
    ? {
        status: "fail" as const,
        label: "재렌더 필요",
        detail: rerenderBlockers.length ? rerenderBlockers.join(", ") : "publish gate blocked",
      }
    : canPublish && canChannelPublish && uploadReviewStatus === "ready"
      ? {
          status: "pass" as const,
          label: "패킷 준비",
          detail: "publish/channel/upload artifact gates ready; same-day upload still requires final-library pre-upload evidence",
        }
      : {
          status: "warn" as const,
          label: "수정 필요",
          detail: `${channelReadinessLabel(channelStatus)} / ${uploadReviewLabel(uploadReviewStatus)}`,
        };
  const sceneAuditRows = production?.scenes?.slice(0, 8) ?? [];

  async function handleFinalize(requireChannelReady = false, requireTopTier = false) {
    if (!result?.outputPath) return;
    setFinalizingMode(requireTopTier ? "top-tier" : requireChannelReady ? "channel" : "publish");
    setPublishPacket(null);
    try {
      const packet = await finalizeRender({
        outputPath: result.outputPath,
        qualityReportPath: result.qualityReportPath,
        projectId: report?.projectId,
        requireChannelReady: requireChannelReady || requireTopTier,
        requireTopTier,
      });
      setPublishPacket(packet);
    } catch (error) {
      setPublishPacket({
        ok: false,
        error: error instanceof Error ? error.message : "publish packet request failed",
      });
    } finally {
      setFinalizingMode(null);
    }
  }

  async function handleLibraryAudit() {
    setLoadingLibraryAudit(true);
    const audit = await auditFinalVideoLibrary(20);
    setLibraryAudit(audit);
    setLoadingLibraryAudit(false);
  }

  const libraryCounts = libraryAudit?.counts ?? {};
  const libraryBest = libraryAudit?.bestPacket ?? null;
  const libraryDecision = libraryPacketDecision(libraryBest);
  const libraryNextActions = (libraryBest?.nextActions ?? []).slice(0, 4);
  const libraryGoalReadiness = libraryAudit?.goalReadiness ?? null;
  const libraryFreshSourceRepeatability = libraryGoalReadiness?.freshSourceRepeatability ?? null;
  const libraryPhoneReview = libraryGoalReadiness?.phoneSizedHumanReview ?? null;
  const libraryPhoneReviewLiveFailureFields = (libraryPhoneReview?.missingFields ?? [])
    .filter((field) => LIVE_PHONE_REVIEW_FIELDS.includes(field));
  const libraryPlatformAnalytics = libraryGoalReadiness?.platformAnalytics ?? null;
  const libraryFreshSourceProofIssueRows = combinedProofCheckIssueRows(
    ["artifact", libraryFreshSourceRepeatability?.evidenceArtifactChecks],
    ["digest", libraryFreshSourceRepeatability?.evidenceDigestChecks],
    [
      "required",
      {
        finalVideoDigest: libraryFreshSourceRepeatability?.finalVideoDigestCheck,
        recordedAt: libraryFreshSourceRepeatability?.recordedAtCheck,
      },
    ],
  );
  const libraryPhoneReviewProofIssueRows = combinedProofCheckIssueRows(
    ["artifact", libraryPhoneReview?.evidenceArtifactChecks],
    ["digest", libraryPhoneReview?.evidenceDigestChecks],
    [
      "required",
      {
        finalVideoDigest: libraryPhoneReview?.finalVideoDigestCheck,
        reviewedAt: libraryPhoneReview?.reviewedAtCheck,
        deviceViewport: libraryPhoneReview?.deviceViewportCheck,
      },
    ],
  );
  const libraryPlatformAnalyticsProofIssueRows = combinedProofCheckIssueRows(
    ["artifact", libraryPlatformAnalytics?.evidenceArtifactChecks],
    [
      "required",
      {
        finalVideoDigest: libraryPlatformAnalytics?.finalVideoDigestCheck,
        snapshotDigest: libraryPlatformAnalytics?.snapshotDigestCheck,
        sampleWindow: libraryPlatformAnalytics?.sampleWindowCheck,
        nextImprovementAction: libraryPlatformAnalytics?.nextImprovementActionCheck,
      },
    ],
  );
  const libraryPreUploadDecision = libraryGoalReadiness?.preUploadDecision ?? null;
  const libraryRunwayChecklist = libraryGoalReadiness?.operatingRunwayChecklist ?? [];
  const libraryRunwaySummary = libraryGoalReadiness?.runwayChecklistSummary ?? null;
  const grokProofMonitorUrl =
    libraryAudit?.sourcePipelineStatus?.grok?.proofMonitorUrl ?? libraryGoalReadiness?.proofMonitorUrl ?? null;
  const grokObservedPostUrl =
    libraryAudit?.sourcePipelineStatus?.grok?.observedPostUrl ?? libraryGoalReadiness?.observedPostUrl ?? null;
  const grokObservedPostScriptUrl =
    libraryAudit?.sourcePipelineStatus?.grok?.observedPostDownloadScriptUrl ??
    libraryAudit?.sourcePipelineStatus?.grok?.bookmarkletDirectImport?.observedPostDownloadScriptUrl ??
    null;
  const latestGrokHandoff = libraryAudit?.sourcePipelineStatus?.grok?.latestHandoff ?? null;
  const latestHandoffImportPreflight = latestGrokHandoff?.importPreflight ?? null;
  const latestHandoffBrowserGeneration = latestGrokHandoff?.browserGenerationProof ?? null;
  const latestHandoffReplacementBacklog = latestGrokHandoff?.replacementBacklog ?? [];
  const latestHandoffLiveFailCategories = latestGrokHandoff?.liveFailCategories ?? [];
  const libraryGrokHandoffSelection = libraryAudit?.sourcePipelineStatus?.grok?.handoffSelection ?? null;
  const libraryGrokNativeDownloadPromptPolicy = libraryAudit?.sourcePipelineStatus?.grok?.nativeDownloadPromptPolicy ?? null;
  const libraryStockCuration = libraryAudit?.sourcePipelineStatus?.pexels?.candidateCuration ?? null;
  const libraryStockCurationMissing = libraryStockCuration?.missingScenes ?? [];
  const libraryPexelsReplacementResearch = libraryAudit?.sourcePipelineStatus?.pexels?.replacementResearch ?? null;
  const librarySourceRecoveryPlan = libraryAudit?.sourcePipelineStatus?.sourceRecoveryPlan ?? null;
  const librarySourceRecoveryAcceptance = libraryAudit?.sourcePipelineStatus?.sourceRecoveryAcceptance ?? null;
  const libraryPipelineHints = [
    libraryAudit?.sourcePipelineStatus?.grok?.nextAction,
    libraryAudit?.sourcePipelineStatus?.localVideo?.nextAction,
    libraryAudit?.sourcePipelineStatus?.pexels?.nextAction,
  ].filter(Boolean) as string[];
  const libraryPreUploadNextActions =
    libraryPreUploadDecision && libraryPreUploadDecision.status !== "upload"
      ? [libraryPreUploadDecision.nextAction, libraryPreUploadDecision.detail].filter((item): item is string => Boolean(item))
      : [];
  const displayedLibraryNextActions = libraryPreUploadNextActions.length
    ? libraryPreUploadNextActions
    : (libraryNextActions.length
        ? libraryNextActions.map((item) => item.operatorAction || item.label || item.key)
        : libraryPipelineHints
      ).filter((item): item is string => Boolean(item));

  async function handleEvidenceTemplates() {
    setMaterializingEvidenceTemplates(true);
    setEvidenceTemplateResult(null);
    try {
      const result = await materializeFinalLibraryEvidenceTemplates({
        projectId: libraryBest?.projectId,
        limit: 20,
      });
      setEvidenceTemplateResult(result);
      const audit = await auditFinalVideoLibrary(20);
      setLibraryAudit(audit);
    } catch (error) {
      setEvidenceTemplateResult({
        ok: false,
        error: error instanceof Error ? error.message : "evidence template request failed",
        proofArtifactsCreated: false,
        goalComplete: false,
      });
    } finally {
      setMaterializingEvidenceTemplates(false);
    }
  }

  async function handleDashboardSmoke() {
    setCapturingDashboardSmoke(true);
    setDashboardSmokeResult(null);
    try {
      const result = await captureFinalLibraryDashboardSmoke({
        projectId: libraryBest?.projectId,
        limit: 20,
        surface: "render-review-final-library",
        browserRendered: true,
        bridgeConnected: libraryAudit?.ok === true,
        finalLibraryPanelVisible: Boolean(libraryDashboardRef.current),
        preUploadReady: libraryGoalReadiness?.preUploadReady === true,
        visibleTexts: visibleTextLines(libraryDashboardRef.current),
        url: window.location.href,
        userAgent: navigator.userAgent,
      });
      setDashboardSmokeResult(result);
      const audit = await auditFinalVideoLibrary(20);
      setLibraryAudit(audit);
    } catch (error) {
      setDashboardSmokeResult({
        ok: false,
        error: error instanceof Error ? error.message : "dashboard smoke capture failed",
        proofArtifactsCreated: false,
        freshSourceProofCreated: false,
        goalComplete: false,
      });
    } finally {
      setCapturingDashboardSmoke(false);
    }
  }

  async function handlePhoneEvidence() {
    setPreparingPhoneEvidence(true);
    setPhoneEvidenceResult(null);
    try {
      const result = await prepareFinalLibraryPhoneReviewEvidence({
        projectId: libraryBest?.projectId,
        limit: 20,
      });
      setPhoneEvidenceResult(result);
      const audit = await auditFinalVideoLibrary(20);
      setLibraryAudit(audit);
    } catch (error) {
      setPhoneEvidenceResult({
        ok: false,
        error: error instanceof Error ? error.message : "phone evidence prep failed",
        proofArtifactsCreated: false,
        phoneReviewProofCreated: false,
        goalComplete: false,
      });
    } finally {
      setPreparingPhoneEvidence(false);
    }
  }

  async function handleFreshSourceEvidence() {
    setPreparingFreshSourceEvidence(true);
    setFreshSourceEvidenceResult(null);
    try {
      const result = await prepareFinalLibraryFreshSourceEvidence({
        projectId: libraryBest?.projectId,
        limit: 20,
      });
      setFreshSourceEvidenceResult(result);
      const audit = await auditFinalVideoLibrary(20);
      setLibraryAudit(audit);
    } catch (error) {
      setFreshSourceEvidenceResult({
        ok: false,
        error: error instanceof Error ? error.message : "fresh-source evidence prep failed",
        proofArtifactsCreated: false,
        freshSourceProofCreated: false,
        goalComplete: false,
      });
    } finally {
      setPreparingFreshSourceEvidence(false);
    }
  }

  async function handleFreshSourceIntake() {
    setMaterializingFreshSourceIntake(true);
    setFreshSourceIntakeResult(null);
    try {
      const result = await materializeFreshSourceIntakePacket({
        projectId: latestGrokHandoff?.projectId,
        sceneId: latestGrokHandoff?.nextMissingSceneId,
      });
      setFreshSourceIntakeResult(result);
      const audit = await auditFinalVideoLibrary(20);
      setLibraryAudit(audit);
    } catch (error) {
      setFreshSourceIntakeResult({
        ok: false,
        error: error instanceof Error ? error.message : "fresh-source intake request failed",
        proofArtifactCreated: false,
        freshSourceProofCreated: false,
        goalComplete: false,
      });
    } finally {
      setMaterializingFreshSourceIntake(false);
    }
  }

  async function handleSourceRecoveryAcceptance() {
    setMaterializingSourceRecoveryAcceptance(true);
    setSourceRecoveryAcceptanceResult(null);
    try {
      const result = await materializeSourceRecoveryAcceptancePacket({
        projectId: latestGrokHandoff?.projectId,
        sceneId: latestGrokHandoff?.nextMissingSceneId,
      });
      setSourceRecoveryAcceptanceResult(result);
      const audit = await auditFinalVideoLibrary(20);
      setLibraryAudit(audit);
    } catch (error) {
      setSourceRecoveryAcceptanceResult({
        ok: false,
        error: error instanceof Error ? error.message : "source recovery acceptance request failed",
        proofArtifactCreated: false,
        freshSourceProofCreated: false,
        goalComplete: false,
        directRenderAllowed: false,
        uploadReady: false,
      });
    } finally {
      setMaterializingSourceRecoveryAcceptance(false);
    }
  }

  async function handleSourceRecoveryRerenderPlan() {
    setMaterializingSourceRecoveryRerenderPlan(true);
    setSourceRecoveryRerenderPlanResult(null);
    try {
      const result = await materializeSourceRecoveryRerenderPlan({
        projectId: latestGrokHandoff?.projectId,
        sceneId: latestGrokHandoff?.nextMissingSceneId,
      });
      setSourceRecoveryRerenderPlanResult(result);
      const audit = await auditFinalVideoLibrary(20);
      setLibraryAudit(audit);
    } catch (error) {
      setSourceRecoveryRerenderPlanResult({
        ok: false,
        status: "request-failed",
        error: error instanceof Error ? error.message : "source recovery rerender plan request failed",
        blockedBySourceRecoveryAcceptance: true,
        rerenderInputReady: false,
        renderExecuted: false,
        freshSourceProofCreated: false,
        goalComplete: false,
      });
    } finally {
      setMaterializingSourceRecoveryRerenderPlan(false);
    }
  }

  return (
    <section className="render-review-panel">
      <div className="render-review-head">
        <div>
          <div className="render-review-kicker">Render QA</div>
          <h2>최종 MP4 검수</h2>
        </div>
        <div className={`render-review-score ${allChecksPass ? "pass" : "warn"}`}>
          <Gauge size={16} />
          <span>{score.passed}/{score.total || 0}</span>
        </div>
      </div>

      <div className="render-review-output">
        <FileVideo size={18} />
        <div className="render-review-paths">
          <span>{result.outputPath}</span>
          {result.qualityReportPath ? <small>{result.qualityReportPath}</small> : null}
        </div>
        <button className="render-copy-btn" title="MP4 경로 복사" onClick={() => copyText(result.outputPath)}>
          <Clipboard size={14} />
        </button>
      </div>

      <div className="render-decision-lane">
        <div className="render-decision-head">
          <div>
            <span>Operator decision lane</span>
            <strong>{heroDecisionReady ? "상위권 기준 통과" : "다음 제작 판단 필요"}</strong>
          </div>
          <small>{decisionCards.filter((card) => card.status === "pass").length}/{decisionCards.length}</small>
        </div>
        <div className="render-decision-grid">
          {decisionCards.map((card) => (
            <div key={card.key} className={`render-decision-card ${card.status}`}>
              <div className="render-decision-card-title">
                {card.icon}
                <span>{card.title}</span>
              </div>
              <strong>{card.value}</strong>
              <p>{card.detail}</p>
            </div>
          ))}
        </div>
        {nextProductionActions.length > 0 ? (
          <div className="render-next-production">
            <span>다음 production action</span>
            {nextProductionActions.slice(0, 4).map((item, index) => (
              <p key={`${item}-${index}`}>{item}</p>
            ))}
          </div>
        ) : null}
      </div>

      <div className={`render-ops-triage ${operatorDecision.status}`}>
        <div>
          <span>Live channel decision</span>
          <strong>{operatorDecision.label}</strong>
        </div>
        <p>{operatorDecision.detail}</p>
        <small>
          hook {productionSummary.firstSceneHookReady ? "ready" : "review"} / caption {captionDecisionReady ? "safe" : "review"} / audio {audioProvenanceReady ? "ready" : "review"}
        </small>
      </div>

      {sceneAuditRows.length > 0 ? (
        <div className="render-scene-audit-grid">
          {sceneAuditRows.map((item, index) => {
            const status = sceneReadyStatus(item, firstSceneId);
            const candidate = item.selectedFileName || item.selectedCandidateSummary || "candidate not recorded";
            return (
              <div key={`${item.sceneId ?? index}-audit`} className={`render-scene-audit-card ${status}`}>
                <div className="render-scene-audit-head">
                  <span>{String(item.sceneId ?? `scene-${index + 1}`)}</span>
                  <small>{sourceRailLabel(item)}</small>
                </div>
                <strong>{candidate}</strong>
                <p>{item.sourceRationale || "source rationale missing"}</p>
                <div className="render-scene-audit-tags">
                  <span className={item.captionPreset ? "pass" : "warn"}>{String(item.captionPreset || "caption?")}</span>
                  <span className={item.sceneId === firstSceneId && (item.hookNote || item.captionPreset === "top-hook") ? "pass" : item.sceneId === firstSceneId ? "warn" : "pass"}>
                    {item.sceneId === firstSceneId ? "hook" : "body"}
                  </span>
                  <span className={item.audioMixReviewNote ? "pass" : "warn"}>audio</span>
                  <span className={item.visualQualityVerdictStatus === "pass" ? "pass" : "warn"}>watermark/logo</span>
                  <span className={(item.caveats?.length ?? 0) === 0 ? "pass" : "warn"}>{(item.caveats?.length ?? 0) === 0 ? "ready" : `${item.caveats?.length} caveat`}</span>
                </div>
              </div>
            );
          })}
        </div>
      ) : null}

      <div className="render-publish-actions">
        <button className="render-publish-btn" onClick={() => handleFinalize(false)} disabled={finalizingMode !== null}>
          <FileVideo size={14} />
          {finalizingMode === "publish" ? "패킷 저장 중" : canPublish ? "최종 패킷 저장" : "차단 사유 확인"}
        </button>
        <button className="render-publish-btn channel" onClick={() => handleFinalize(true)} disabled={finalizingMode !== null}>
          <FileVideo size={14} />
          {finalizingMode === "channel" ? "채널 검사 중" : canChannelPublish ? "채널 패킷 저장" : "채널 차단 확인"}
        </button>
        <button className="render-publish-btn channel" onClick={() => handleFinalize(true, true)} disabled={finalizingMode !== null}>
          <FileVideo size={14} />
          {finalizingMode === "top-tier" ? "상위권 검사 중" : topTierReadinessStatus === "top-tier-ready" ? "상위권 패킷 저장" : "상위권 차단 확인"}
        </button>
        <button className="render-publish-btn" onClick={handleLibraryAudit} disabled={loadingLibraryAudit}>
          <RefreshCw size={14} className={loadingLibraryAudit ? "spin" : undefined} />
          {loadingLibraryAudit ? "라이브러리 점검 중" : "최종 라이브러리 점검"}
        </button>
        <button
          className="render-publish-btn"
          onClick={handleEvidenceTemplates}
          disabled={materializingEvidenceTemplates || !libraryAudit?.ok}
        >
          <Clipboard size={14} />
          {materializingEvidenceTemplates ? "템플릿 저장 중" : "증거 템플릿 저장"}
        </button>
        <button
          className="render-publish-btn"
          onClick={handleDashboardSmoke}
          disabled={capturingDashboardSmoke || !libraryAudit?.ok}
        >
          <Gauge size={14} />
          {capturingDashboardSmoke ? "Smoke 저장 중" : "Dashboard smoke 저장"}
        </button>
        <button
          className="render-publish-btn"
          onClick={handlePhoneEvidence}
          disabled={preparingPhoneEvidence || !libraryAudit?.ok}
        >
          <FileVideo size={14} />
          {preparingPhoneEvidence ? "Phone evidence 준비 중" : "Phone evidence 준비"}
        </button>
        <button
          className="render-publish-btn"
          onClick={handleFreshSourceEvidence}
          disabled={preparingFreshSourceEvidence || !libraryAudit?.ok}
        >
          <Clipboard size={14} />
          {preparingFreshSourceEvidence ? "Fresh evidence 준비 중" : "Fresh proof evidence 준비"}
        </button>
        <button
          className="render-publish-btn"
          onClick={handleFreshSourceIntake}
          disabled={materializingFreshSourceIntake || !libraryAudit?.ok || !latestGrokHandoff?.available}
        >
          <Clipboard size={14} />
          {materializingFreshSourceIntake ? "Intake 저장 중" : "Fresh intake 저장"}
        </button>
        <button
          className="render-publish-btn"
          onClick={handleSourceRecoveryAcceptance}
          disabled={materializingSourceRecoveryAcceptance || !libraryAudit?.ok || !librarySourceRecoveryPlan?.totalScenes}
        >
          <Clipboard size={14} />
          {materializingSourceRecoveryAcceptance ? "Recovery 준비 중" : "Recovery review 준비"}
        </button>
        <button
          className="render-publish-btn"
          onClick={handleSourceRecoveryRerenderPlan}
          disabled={materializingSourceRecoveryRerenderPlan || !libraryAudit?.ok || !librarySourceRecoveryPlan?.totalScenes}
        >
          <FileVideo size={14} />
          {materializingSourceRecoveryRerenderPlan ? "Rerender plan 준비 중" : "Rerender plan 준비"}
        </button>
        <span className={canPublish ? "pass" : "warn"}>
          {canChannelPublish
            ? "channel-ready render는 업로드 후보 패킷으로 저장됩니다"
            : canPublish
              ? "publish-ready 저장 가능, channel packet은 gate가 거부합니다"
              : "ready가 아니면 route가 저장을 거부합니다"}
        </span>
      </div>

      {libraryAudit ? (
        <div ref={libraryDashboardRef} className={`render-publish-gate render-library-audit final-library-dashboard ${libraryAuditClass(libraryAudit)}`}>
          <div className="render-publish-gate-head">
            <div>
              <span>Final video library</span>
              <strong>
                {libraryAudit.ok
                  ? `top-tier ${libraryCounts.topTierReady ?? 0} / channel ${libraryCounts.channelReady ?? 0}`
                  : libraryAudit.error || "library audit failed"}
              </strong>
            </div>
            <small>{libraryAudit.scanned ?? 0} scanned</small>
          </div>
          {libraryAudit.ok ? (
            <>
              <div className="render-top-tier-summary">
                <span className={(libraryCounts.withMp4 ?? 0) > 0 ? "pass" : "warn"}>mp4 {libraryCounts.withMp4 ?? 0}</span>
                <span className={(libraryCounts.withQualityAudit ?? 0) > 0 ? "pass" : "warn"}>audit {libraryCounts.withQualityAudit ?? 0}</span>
                <span className={(libraryCounts.withPublishPacket ?? 0) > 0 ? "pass" : "warn"}>packet {libraryCounts.withPublishPacket ?? 0}</span>
              <span className={(libraryCounts.uploadReady ?? 0) > 0 ? "pass" : "warn"}>upload {libraryCounts.uploadReady ?? 0}</span>
              <span className={(libraryCounts.topTierReady ?? 0) > 0 ? "pass" : "warn"}>top-tier {libraryCounts.topTierReady ?? 0}</span>
              {libraryGrokNativeDownloadPromptPolicy ? (
                <span className={libraryGrokNativeDownloadPromptPolicy.blocksIfPromptAppears ? "fail" : "warn"}>
                  native download prompt {libraryGrokNativeDownloadPromptPolicy.status || "policy"}
                </span>
              ) : null}
              <span className={stockCurationClass(libraryStockCuration)}>Pexels curation {stockCurationLabel(libraryStockCuration)}</span>
              <span className={pexelsReplacementClass(libraryPexelsReplacementResearch)}>
                Pexels fallback {pexelsReplacementLabel(libraryPexelsReplacementResearch)}
              </span>
              {libraryPreUploadDecision ? (
                <span className={operatorDecisionClass(libraryPreUploadDecision.status)}>
                  today upload {libraryPreUploadDecision.label || "수정 필요"}
                </span>
              ) : null}
              </div>
              <div className="render-publish-gate-lists">
                <div>
                  <span>best packet</span>
                  {libraryBest ? (
                    <>
                      <p>{libraryBest.projectId}</p>
                      {libraryPreUploadDecision ? (
                        <>
                          <p className={operatorDecisionClass(libraryPreUploadDecision.status)}>
                            today upload decision: {libraryPreUploadDecision.label || "수정 필요"}
                          </p>
                          {libraryPreUploadDecision.detail ? <p>{libraryPreUploadDecision.detail}</p> : null}
                        </>
                      ) : null}
                      <p className={libraryDecision.status === "packet" ? "pass" : libraryDecision.status === "rerender" ? "fail" : "warn"}>
                        artifact packet decision: {libraryDecision.label}
                      </p>
                      <p>{libraryDecision.detail}</p>
                      <p>
                        upload {libraryBest.summary?.uploadReady ? "ready" : "not ready"} / channel{" "}
                        {libraryBest.summary?.channelReady ? "ready" : "not ready"}
                      </p>
                      {libraryBest.summary?.benchmarkGap ? <p>{libraryBest.summary.benchmarkGap}</p> : null}
                      {libraryBest.summary?.stockCandidateCurationStatus ? (
                        <p>Pexels curation: {libraryBest.summary.stockCandidateCurationStatus}</p>
                      ) : null}
                      {libraryBest.finalVideoPath ? <p>{libraryBest.finalVideoPath}</p> : null}
                    </>
                  ) : (
                    <p>No final MP4 packet found yet.</p>
                  )}
                </div>
                <div>
                  <span>next automation action</span>
                  {displayedLibraryNextActions.slice(0, 4).map((item, index) => <p key={`${item}-${index}`}>{item}</p>)}
                  {libraryGrokNativeDownloadPromptPolicy ? (
                    <p className={libraryGrokNativeDownloadPromptPolicy.blocksIfPromptAppears ? "fail" : "warn"}>
                      native download prompt: {libraryGrokNativeDownloadPromptPolicy.status || "policy"}
                      {libraryGrokNativeDownloadPromptPolicy.operatorAction ? ` - ${libraryGrokNativeDownloadPromptPolicy.operatorAction}` : ""}
                    </p>
                  ) : null}
                  {grokProofMonitorUrl ? (
                    <p>
                      <a href={grokProofMonitorUrl} target="_blank" rel="noreferrer">
                        Open Grok proof monitor
                      </a>
                    </p>
                  ) : null}
                  {grokObservedPostUrl ? (
                    <p>
                      <a href={grokObservedPostUrl} target="_blank" rel="noreferrer">
                        Open observed Grok post
                      </a>
                    </p>
                  ) : null}
                  <GrokObservedPostDirectImportActions
                    observedPostUrl={grokObservedPostUrl}
                    scriptUrl={grokObservedPostScriptUrl}
                    proofMonitorUrl={grokProofMonitorUrl}
                  />
                  {displayedLibraryNextActions.length === 0 ? (
                    <p>No pipeline hint returned. Re-run after bridge restart if the route was just added.</p>
                  ) : null}
                </div>
                <div>
                  <span>Pexels candidate curation</span>
                  {libraryStockCuration ? (
                    <>
                      <p>{stockCurationLabel(libraryStockCuration)}</p>
                      {libraryStockCurationMissing.length ? (
                        <p>missing: {compactListLabel(libraryStockCurationMissing, "0")}</p>
                      ) : null}
                      {libraryStockCuration.detail ? <p>{libraryStockCuration.detail}</p> : null}
                    </>
                  ) : (
                    <p>No curation evidence returned by the audit route.</p>
                  )}
                  {libraryPexelsReplacementResearch?.available ? (
                    <div className="render-library-inline-panel">
                      <p className={pexelsReplacementClass(libraryPexelsReplacementResearch)}>
                        direct-URL fallback: {pexelsReplacementLabel(libraryPexelsReplacementResearch)}
                      </p>
                      <p>
                        candidates {libraryPexelsReplacementResearch.totalCandidates ?? 0} / conditional{" "}
                        {libraryPexelsReplacementResearch.conditionalFallbackCandidates ?? 0} / direct-use fail{" "}
                        {libraryPexelsReplacementResearch.failedDirectUseCandidates ?? 0} / upload-ready{" "}
                        {libraryPexelsReplacementResearch.uploadReadyCandidates ?? 0}
                      </p>
                      {typeof libraryPexelsReplacementResearch.videoOnlyNoAudioCandidates === "number" ? (
                        <p>video-only no audio: {libraryPexelsReplacementResearch.videoOnlyNoAudioCandidates}</p>
                      ) : null}
                      {libraryPexelsReplacementResearch.scenes?.length ? (
                        <p>fallback scenes: {compactListLabel(libraryPexelsReplacementResearch.scenes, "0")}</p>
                      ) : null}
                      {libraryPexelsReplacementResearch.candidates?.slice(0, 3).map((candidate) => (
                      <p key={candidate.sceneId || candidate.candidateFileName} className={candidate.uploadReady ? "pass" : "warn"}>
                        {candidate.sceneId || "scene"}: {candidate.verdict || "needs-review"}
                        {candidate.reframeSmokeVerdict ? ` / reframe ${candidate.reframeSmokeVerdict}` : ""}
                        {candidate.previousLowerEmptyAreaConcernCorrected ? " / lower-frame concern corrected" : ""}
                        {candidate.candidateFileName ? ` / ${candidate.candidateFileName}` : ""}
                      </p>
                    ))}
                      {libraryPexelsReplacementResearch.doesNotSatisfy?.length ? (
                        <p>not proof for: {compactListLabel(libraryPexelsReplacementResearch.doesNotSatisfy, "0")}</p>
                      ) : null}
                      {libraryPexelsReplacementResearch.operatorAction ? <p>{libraryPexelsReplacementResearch.operatorAction}</p> : null}
                    </div>
                  ) : null}
                </div>
                <div>
                  <span>Source recovery plan</span>
                  <SourceRecoveryPlanDetails plan={librarySourceRecoveryPlan} acceptance={librarySourceRecoveryAcceptance} />
                </div>
                <div>
                  <span>Operating proof prep</span>
                  {libraryGoalReadiness ? (
                    <>
                      <p>
                        artifact gate: {libraryGoalReadiness.artifactGateComplete ? "ready" : "incomplete"} / operating Goal:{" "}
                        {libraryGoalReadiness.operatingSystemComplete ? "complete" : "active"}
                      </p>
                      {libraryGoalReadiness.operatorDecision?.label ? (
                        <p className={operatorDecisionClass(libraryGoalReadiness.operatorDecision.status)}>
                          live-channel decision: {libraryGoalReadiness.operatorDecision.label}
                        </p>
                      ) : null}
                      {libraryPreUploadDecision?.label ? (
                        <>
                          <p className={operatorDecisionClass(libraryPreUploadDecision.status)}>
                            pre-upload decision: {libraryPreUploadDecision.label}
                          </p>
                          {libraryPreUploadDecision.detail ? <p>{libraryPreUploadDecision.detail}</p> : null}
                        </>
                      ) : null}
                      {libraryRunwaySummary ? (
                        <p className={libraryRunwaySummary.readyForTodayUpload ? "pass" : "warn"}>
                          runway next: {libraryRunwaySummary.primaryBlockerLabel || "none"} -{" "}
                          {libraryRunwaySummary.nextAction || "maintain packet evidence"}
                        </p>
                      ) : null}
                      {libraryRunwayChecklist.length ? (
                        <div className="render-library-inline-panel">
                          {libraryRunwayChecklist.map((item) => (
                            <p key={item.key || item.label} className={goalReadinessClass(item.status)}>
                              {item.label || item.key}: {item.status || "unchecked"}
                              {item.detail ? ` - ${item.detail}` : ""}
                            </p>
                          ))}
                        </div>
                      ) : null}
                      <QualityGateSystemPanel title="Unified gate system" gateSystem={libraryGoalReadiness.gateSystem ?? libraryAudit.gateSystem} />
                      {libraryFreshSourceRepeatability ? (
                        <>
                          <p className={goalReadinessClass(libraryFreshSourceRepeatability.status)}>
                            fresh-source proof: {libraryFreshSourceRepeatability.status || "missing"}
                          </p>
                          {libraryFreshSourceRepeatability.templateArtifactPath ? (
                            <p>fresh-source template: {libraryFreshSourceRepeatability.templateArtifactPath}</p>
                          ) : null}
                          <ProofCheckIssues label="fresh-source proof issue" rows={libraryFreshSourceProofIssueRows} />
                        </>
                      ) : null}
                      {libraryPhoneReview ? (
                        <>
                          <p className={goalReadinessClass(libraryPhoneReview.status)}>
                            phone review: {libraryPhoneReview.status || "missing"}
                          </p>
                          {libraryPhoneReview.templateArtifactPath ? <p>phone template: {libraryPhoneReview.templateArtifactPath}</p> : null}
                          {libraryPhoneReviewLiveFailureFields.length ? (
                            <p>live phone fail fields: {libraryPhoneReviewLiveFailureFields.join(", ")}</p>
                          ) : null}
                          <ProofCheckIssues label="phone review proof issue" rows={libraryPhoneReviewProofIssueRows} />
                        </>
                      ) : null}
                      {libraryPlatformAnalytics ? (
                        <>
                          <p className={goalReadinessClass(libraryPlatformAnalytics.status)}>
                            analytics: {libraryPlatformAnalytics.status || "missing"}
                          </p>
                          {libraryPlatformAnalytics.templateArtifactPath ? <p>analytics template: {libraryPlatformAnalytics.templateArtifactPath}</p> : null}
                          <ProofCheckIssues label="analytics proof issue" rows={libraryPlatformAnalyticsProofIssueRows} />
                        </>
                      ) : null}
                      {evidenceTemplateResult ? (
                        <>
                          <p className={evidenceTemplateResult.ok ? "warn" : "fail"}>
                            evidence templates: {evidenceTemplateResult.ok ? "written, not proof" : evidenceTemplateResult.error || "failed"}
                          </p>
                          {evidenceTemplateResult.templates?.freshSourceRepeatability?.path ? (
                            <p>fresh-source template file: {evidenceTemplateResult.templates.freshSourceRepeatability.path}</p>
                          ) : null}
                          {evidenceTemplateResult.goalBoundary ? <p>{evidenceTemplateResult.goalBoundary}</p> : null}
                        </>
                      ) : null}
                      {freshSourceEvidenceResult ? (
                        <>
                          <p className={freshSourceEvidenceResult.ok ? "warn" : "fail"}>
                            fresh-source evidence:{" "}
                            {freshSourceEvidenceResult.ok
                              ? "written, not proof"
                              : freshSourceEvidenceResult.error || "failed"}
                          </p>
                          {freshSourceEvidenceResult.artifactPaths?.handoffManifestPath ? (
                            <p>fresh-source handoff draft: {freshSourceEvidenceResult.artifactPaths.handoffManifestPath}</p>
                          ) : null}
                          {freshSourceEvidenceResult.artifactPaths?.sourceReviewPath ? (
                            <p>fresh-source review draft: {freshSourceEvidenceResult.artifactPaths.sourceReviewPath}</p>
                          ) : null}
                          {typeof freshSourceEvidenceResult.reviewRequiredSceneCount === "number" ? (
                            <p>
                              review required scenes: {freshSourceEvidenceResult.reviewRequiredSceneCount} / accepted{" "}
                              {freshSourceEvidenceResult.acceptedSceneCount ?? 0}
                            </p>
                          ) : null}
                          {typeof freshSourceEvidenceResult.proofBlockerCount === "number" ? (
                            <p>
                              fresh-source proof blockers: {freshSourceEvidenceResult.proofBlockerCount} / proof-ready scenes{" "}
                              {freshSourceEvidenceResult.freshSourceProofReadySceneCount ?? 0}
                            </p>
                          ) : null}
                          {freshSourceEvidenceResult.sourceRecoveryAcceptanceStatus?.status ? (
                            <p>
                              source recovery acceptance: {freshSourceEvidenceResult.sourceRecoveryAcceptanceStatus.status}
                              {typeof freshSourceEvidenceResult.sourceRecoveryAcceptanceBlockerCount === "number"
                                ? ` / blockers ${freshSourceEvidenceResult.sourceRecoveryAcceptanceBlockerCount}`
                                : ""}
                            </p>
                          ) : null}
                          {freshSourceEvidenceResult.sourceRecoveryAcceptanceStatus?.blocksFreshSourceProof === true &&
                          freshSourceEvidenceResult.sourceRecoveryAcceptanceStatus.requiredArtifactPath ? (
                            <p>source recovery acceptance file: {freshSourceEvidenceResult.sourceRecoveryAcceptanceStatus.requiredArtifactPath}</p>
                          ) : null}
                          {freshSourceEvidenceResult.freshSourceTemplate?.path ? (
                            <p>fresh-source template file: {freshSourceEvidenceResult.freshSourceTemplate.path}</p>
                          ) : null}
                          {freshSourceEvidenceResult.goalBoundary ? <p>{freshSourceEvidenceResult.goalBoundary}</p> : null}
                        </>
                      ) : null}
                      {dashboardSmokeResult ? (
                        <>
                          <p className={dashboardSmokeResult.ok ? "warn" : "fail"}>
                            dashboard smoke:{" "}
                            {dashboardSmokeResult.ok
                              ? "browser-rendered evidence saved, not proof"
                              : dashboardSmokeResult.error || dashboardSmokeResult.issues?.join("; ") || "failed"}
                          </p>
                          {dashboardSmokeResult.path ? <p>dashboard smoke file: {dashboardSmokeResult.path}</p> : null}
                          {dashboardSmokeResult.sha256 ? <p>dashboard smoke sha256: {dashboardSmokeResult.sha256}</p> : null}
                          {dashboardSmokeResult.goalBoundary ? <p>{dashboardSmokeResult.goalBoundary}</p> : null}
                        </>
                      ) : null}
                      {phoneEvidenceResult ? (
                        <>
                          <p className={phoneEvidenceResult.ok ? "warn" : "fail"}>
                            phone evidence:{" "}
                            {phoneEvidenceResult.ok
                              ? "packet-local review evidence prepared, not proof"
                              : phoneEvidenceResult.error || phoneEvidenceResult.issues?.join("; ") || "failed"}
                          </p>
                          {phoneEvidenceResult.phoneTemplate?.path ? <p>phone template file: {phoneEvidenceResult.phoneTemplate.path}</p> : null}
                          {phoneEvidenceResult.pendingFields?.length ? (
                            <p>pending operator evidence: {compactListLabel(phoneEvidenceResult.pendingFields, "0")}</p>
                          ) : null}
                          {phoneEvidenceResult.goalBoundary ? <p>{phoneEvidenceResult.goalBoundary}</p> : null}
                        </>
                      ) : null}
                      {latestGrokHandoff?.available ? (
                        <>
                          <p className={latestGrokHandoff.blocksOperatingGoal ? "warn" : "pass"}>
                            fresh handoff: {latestGrokHandoff.projectId} / {latestGrokHandoff.status || "unknown"}
                          </p>
                          {libraryGrokHandoffSelection?.preferredProductionHandoff ? (
                            <p className="warn">
                              handoff selection: using {libraryGrokHandoffSelection.selectedProjectId || latestGrokHandoff.projectId}; newer{" "}
                              {libraryGrokHandoffSelection.latestByMtimeProjectId || "unknown"} ignored
                            </p>
                          ) : null}
                          {latestHandoffImportPreflight ? (
                            <>
                              <p className={latestHandoffImportPreflight.readyForReview ? "pass" : "warn"}>
                                import preflight: ready {latestHandoffImportPreflight.readyScenes ?? 0}/
                                {latestHandoffImportPreflight.totalScenes ?? 0}, present{" "}
                                {latestHandoffImportPreflight.presentScenes ?? 0}
                              </p>
                              {latestHandoffImportPreflight.staleScenes?.length ? (
                                <p>stale imports: {compactListLabel(latestHandoffImportPreflight.staleScenes, "0")}</p>
                              ) : null}
                              {latestHandoffImportPreflight.invalidScenes?.length ? (
                                <p>ffprobe-invalid imports: {compactListLabel(latestHandoffImportPreflight.invalidScenes, "0")}</p>
                              ) : null}
                            </>
                          ) : null}
                          {latestHandoffBrowserGeneration ? (
                            <>
                              <p className={(latestHandoffBrowserGeneration.generatedScenes ?? 0) > 0 ? "warn" : "fail"}>
                                browser generated: {latestHandoffBrowserGeneration.generatedScenes ?? 0}/
                                {latestGrokHandoff.totalScenes ?? 0}, import proof:{" "}
                                {latestHandoffBrowserGeneration.doesNotSatisfyFreshSourceProof ? "not satisfied" : "review"}
                              </p>
                              {latestHandoffBrowserGeneration.generatedSceneIds?.length ? (
                                <p>generated posts: {compactListLabel(latestHandoffBrowserGeneration.generatedSceneIds, "0")}</p>
                              ) : null}
                            </>
                          ) : null}
                          {latestGrokHandoff.missingScenes?.length ? (
                            <p>missing fresh imports: {compactListLabel(latestGrokHandoff.missingScenes, "0")}</p>
                          ) : null}
                          <p>
                            accepted {latestGrokHandoff.acceptedScenes ?? 0}/{latestGrokHandoff.totalScenes ?? 0} / rejected{" "}
                            {latestGrokHandoff.rejectedScenes ?? 0}
                          </p>
                          {latestHandoffLiveFailCategories.length ? (
                            <p className="warn">live fail categories: {compactListLabel(latestHandoffLiveFailCategories, "0")}</p>
                          ) : null}
                          {latestHandoffReplacementBacklog.length ? (
                            <div className="render-library-inline-panel">
                              {latestHandoffReplacementBacklog.slice(0, 4).map((item) => (
                                <p key={item.sceneId || item.selectedFileName} className="fail">
                                  replace {item.sceneId || "scene"}: {compactListLabel(item.failCategories ?? [], "review failed")}
                                  {typeof item.unreviewedLocalCandidateCount === "number"
                                    ? ` / local candidates ${item.unreviewedLocalCandidateCount}/${item.localCandidateCount ?? 0}`
                                    : ""}
                                  {item.unreviewedLocalCandidates?.length
                                    ? ` / review ${compactListLabel(item.unreviewedLocalCandidates, "0")}`
                                    : ""}
                                  {item.operatorAction ? ` - ${item.operatorAction}` : ""}
                                </p>
                              ))}
                            </div>
                          ) : null}
                          {latestGrokHandoff.freshSourceIntakeTemplatePath ? (
                            <p>fresh intake template: {latestGrokHandoff.freshSourceIntakeTemplatePath}</p>
                          ) : null}
                        </>
                      ) : null}
                      {freshSourceIntakeResult ? (
                        <>
                          <p className={freshSourceIntakeResult.ok ? "warn" : "fail"}>
                            fresh-source intake:{" "}
                            {freshSourceIntakeResult.ok ? "written, not proof" : freshSourceIntakeResult.error || "failed"}
                          </p>
                          {freshSourceIntakeResult.path ? <p>intake file: {freshSourceIntakeResult.path}</p> : null}
                          {freshSourceIntakeResult.sourceRecoveryExecutionChecklist?.length ? (
                            <p>
                              recovery scenes: {freshSourceIntakeResult.sourceRecoveryExecutionChecklist.length} / first lane{" "}
                              {freshSourceIntakeResult.sourceRecoveryExecutionChecklist[0]?.recommendedLane || "source-recovery"}
                            </p>
                          ) : null}
                          {freshSourceIntakeResult.goalBoundary ? <p>{freshSourceIntakeResult.goalBoundary}</p> : null}
                        </>
                      ) : null}
                      <SourceRecoveryAcceptanceResultDetails result={sourceRecoveryAcceptanceResult} />
                      <SourceRecoveryRerenderPlanResultDetails result={sourceRecoveryRerenderPlanResult} />
                    </>
                  ) : (
                    <p>Run final library audit to prepare phone-review and analytics worksheets.</p>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="render-publish-gate-lists">
              <div>
                <span>bridge route</span>
                <p>새 audit route가 live bridge에 아직 로드되지 않았을 수 있습니다.</p>
              </div>
              <div>
                <span>safe next step</span>
                <p>Grok background wait가 끝난 뒤 bridge를 재시작하고 다시 점검합니다.</p>
              </div>
            </div>
          )}
        </div>
      ) : null}

      {publishPacket ? (
        <div className={`render-publish-result ${publishPacket.ok ? "pass" : "fail"}`}>
          {publishPacket.ok ? (
            <>
              <strong>
                {publishPacket.topTierRequired
                  ? "top-tier 패킷 저장 완료"
                  : publishPacket.channelReadyRequired
                    ? "channel-ready 패킷 저장 완료"
                    : "final-videos 패킷 저장 완료"}
              </strong>
              <p>{publishPacket.finalVideoPath}</p>
              {publishPacket.channelReadiness?.status ? (
                <small>channel: {channelReadinessLabel(publishPacket.channelReadiness.status)}</small>
              ) : null}
              {publishPacket.topTierReadiness?.status ? (
                <small>top-tier: {topTierLabel(publishPacket.topTierReadiness.status)}</small>
              ) : null}
              {publishPacket.publishChecklistPath ? <small>{publishPacket.publishChecklistPath}</small> : null}
              {publishPacket.qualityChecklistPath ? <small>{publishPacket.qualityChecklistPath}</small> : null}
              {publishPacket.qualityAuditPath ? <small>{publishPacket.qualityAuditPath}</small> : null}
              {publishPacket.publishPacketPath ? <small>{publishPacket.publishPacketPath}</small> : null}
              {publishPacket.publishPacket?.decision?.label ? (
                <small>artifact packet decision: {publishPacket.publishPacket.decision.label}</small>
              ) : null}
              {publishPacket.publishPacket?.titleCandidates?.length ? (
                <small>titles: {publishPacket.publishPacket.titleCandidates.slice(0, 2).join(" / ")}</small>
              ) : null}
              {publishPacket.publishPacket?.hashtags?.length ? (
                <small>hashtags: {publishPacket.publishPacket.hashtags.join(" ")}</small>
              ) : null}
              {publishPacket.qualityAudit?.summary ? (
                <small>
                  audit: {publishPacket.qualityAudit.summary.passed ?? 0}/{publishPacket.qualityAudit.summary.total ?? 0}
                  {publishPacket.qualityAudit.summary.benchmarkGap ? ` - ${publishPacket.qualityAudit.summary.benchmarkGap}` : ""}
                </small>
              ) : null}
              {publishPacket.contactSheetPath ? <small>{publishPacket.contactSheetPath}</small> : null}
              {publishPacket.audioLevel?.ok ? (
                <small>audio: mean {publishPacket.audioLevel.meanVolumeDb} dB / max {publishPacket.audioLevel.maxVolumeDb} dB</small>
              ) : null}
            </>
          ) : (
            <>
              <strong>{publishPacket.error || "publish packet 저장 실패"}</strong>
              {(publishPacket.requiredFixes ?? []).slice(0, 2).map((item) => <p key={item}>{item}</p>)}
              {(publishPacket.nextActions ?? []).slice(0, 4).map((item) => (
                <p key={item.key ?? item.label}>
                  <span>{item.priority || "next"}</span>: {item.label || item.key}
                  {item.operatorAction ? ` - ${item.operatorAction}` : ""}
                </p>
              ))}
              {publishPacket.channelReadiness?.status ? (
                <small>channel: {channelReadinessLabel(publishPacket.channelReadiness.status)}</small>
              ) : null}
              {publishPacket.topTierReadiness?.status ? (
                <small>top-tier: {topTierLabel(publishPacket.topTierReadiness.status)}</small>
              ) : null}
              {publishPacket.sourcePipelineStatus?.grok?.nextAction ? (
                <small>Grok: {publishPacket.sourcePipelineStatus.grok.nextAction}</small>
              ) : null}
              {publishPacket.sourcePipelineStatus?.localVideo?.nextAction ? (
                <small>Local: {publishPacket.sourcePipelineStatus.localVideo.nextAction}</small>
              ) : null}
              {publishPacket.blockedQualityAuditPath ? <small>{publishPacket.blockedQualityAuditPath}</small> : null}
            </>
          )}
        </div>
      ) : null}

      {readiness ? (
        <div className={`render-publish-gate ${readinessClass(readinessStatus)}`}>
          <div className="render-publish-gate-head">
            <div>
              <span>Publish gate</span>
              <strong>{readinessLabel(readinessStatus)}</strong>
            </div>
            <small>
              {readinessScore?.passed ?? 0}/{readinessScore?.total ?? 0}
            </small>
          </div>
          <div className="render-publish-gate-lists">
            {requiredFixes.length > 0 ? (
              <div>
                <span>필수 수정</span>
                {requiredFixes.slice(0, 3).map((item) => <p key={item}>{item}</p>)}
              </div>
            ) : null}
            {recommendedFixes.length > 0 ? (
              <div>
                <span>권장 보완</span>
                {recommendedFixes.slice(0, 3).map((item) => <p key={item}>{item}</p>)}
              </div>
            ) : null}
            {requiredFixes.length === 0 && recommendedFixes.length === 0 ? (
              <div>
                <span>통과 근거</span>
                {(strengths.length ? strengths : ["No blocking publish issues"]).slice(0, 3).map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {channelReadiness ? (
        <div className={`render-publish-gate render-channel-gate ${channelReadinessClass(channelStatus)}`}>
          <div className="render-publish-gate-head">
            <div>
              <span>Channel gate</span>
              <strong>{channelReadinessLabel(channelStatus)}</strong>
            </div>
            <small>
              {channelScore?.passed ?? 0}/{channelScore?.total ?? 0}
            </small>
          </div>
          <div className="render-review-caveats">
            <span className={heroOriginalReady ? undefined : "warn"}>{firstSceneId}: hero original MP4 {heroOriginalReady ? "ready" : "missing"}</span>
            <span className={heroEvidenceReady ? undefined : "warn"}>hero evidence {heroEvidenceReady ? "ready" : "missing"}</span>
            <span className={heroAiOrLocalReady ? undefined : "warn"}>Grok/local hero {heroAiOrLocalReady ? "ready" : "missing for top-tier"}</span>
          </div>
          <div className="render-publish-gate-lists">
            {channelRequiredFixes.length > 0 ? (
              <div>
                <span>채널 필수</span>
                {channelRequiredFixes.slice(0, 3).map((item) => <p key={item}>{item}</p>)}
              </div>
            ) : null}
            {channelRecommendedFixes.length > 0 ? (
              <div>
                <span>채널 보완</span>
                {channelRecommendedFixes.slice(0, 3).map((item) => <p key={item}>{item}</p>)}
              </div>
            ) : null}
            {channelRequiredFixes.length === 0 && channelRecommendedFixes.length === 0 ? (
              <div>
                <span>채널 근거</span>
                {(channelStrengths.length ? channelStrengths : ["Original-footage gate has no blocking issue"]).slice(0, 3).map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className={`render-publish-gate render-top-tier-gate ${topTierClass(topTierStatus)}`}>
        <div className="render-publish-gate-head">
          <div>
            <span>Top-tier AI-assisted gate</span>
            <strong>{topTierLabel(topTierStatus)}</strong>
          </div>
          <small>{topTierScore.passed}/{topTierScore.total}</small>
        </div>
        <div className="render-top-tier-summary">
          <span className={canPublish ? "pass" : "warn"}>publish {canPublish ? "ready" : "not ready"}</span>
          <span className={canChannelPublish ? "pass" : "warn"}>channel {canChannelPublish ? "ready" : "not ready"}</span>
          <span className={heroAiOrLocalReady ? "pass" : "warn"}>Grok/local hero {heroAiOrLocalReady ? `${grokHeroScenes + localHeroScenes} scene` : "0 scene"}</span>
        </div>
        <div className="render-publish-gate-lists">
          <div>
            <span>{topTierGaps.length > 0 ? "남은 gap" : "통과 근거"}</span>
            {(topTierGaps.length ? topTierGaps : topTierStrengths.length ? topTierStrengths : [
              "Publish/channel gates are ready and the hero scene has Grok/local AI-assisted MP4 evidence.",
              "This can be treated as a stronger AI-assisted channel candidate after operator visual review.",
            ]).slice(0, 4).map((item) => <p key={item}>{item}</p>)}
          </div>
          <div>
            <span>판정 기준</span>
            <p>Upload-ready is not the same as top-tier AI-assisted quality.</p>
            <p>Top-tier claim needs a reviewed Grok/local hero MP4, not only curated stock or direct upload.</p>
          </div>
        </div>
      </div>

      {uploadReview ? (
        <div className={`render-publish-gate render-upload-gate ${uploadReviewClass(uploadReviewStatus)}`}>
          <div className="render-publish-gate-head">
            <div>
              <span>Upload review</span>
              <strong>{uploadReviewLabel(uploadReviewStatus)}</strong>
            </div>
            <small>
              {uploadReviewScore?.passed ?? 0}/{uploadReviewScore?.total ?? 0}
            </small>
          </div>
          <div className="render-publish-gate-lists">
            {uploadRequiredFixes.length > 0 ? (
              <div>
                <span>업로드 전 필수</span>
                {uploadRequiredFixes.slice(0, 3).map((item) => <p key={item}>{item}</p>)}
              </div>
            ) : null}
            {uploadManualItems.length > 0 ? (
              <div>
                <span>수동 검수</span>
                {uploadManualItems.slice(0, 4).map((item) => <p key={item}>{item}</p>)}
              </div>
            ) : null}
            {uploadRequiredFixes.length === 0 && uploadManualItems.length === 0 ? (
              <div>
                <span>업로드 근거</span>
                {(uploadStrengths.length ? uploadStrengths : ["Upload review has no blocking issue"]).slice(0, 4).map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="render-review-metrics">
        <span><strong>{totalScenes}</strong> scenes</span>
        <span><strong>{videoScenes}</strong> video</span>
        <span><strong>{uploaded}</strong> upload</span>
        <span><strong>{generated}</strong> stock/local</span>
        <span className={placeholders > 0 ? "danger" : ""}><strong>{placeholders}</strong> placeholder</span>
      </div>

      {report?.gateSystem ? (
        <div className="render-publish-gate-lists">
          <QualityGateSystemPanel title="Render gate system" gateSystem={report.gateSystem} />
        </div>
      ) : null}

      <div className="render-check-grid">
        {Object.entries(checks).map(([key, check]) => (
          <div key={key} className={`render-check ${statusClass(check.status)}`}>
            <div className="render-check-title">
              <StatusIcon status={check.status} />
              <span>{CHECK_LABELS[key] ?? key}</span>
            </div>
            <p>{check.detail || "no detail"}</p>
          </div>
        ))}
      </div>

      {productionRows.length > 0 ? (
        <div className="render-source-strip">
          {productionRows.map((item, index) => (
            <div key={`${item.sceneId ?? index}-${index}`} className="render-source-pill">
              <span>{String(item.sceneId ?? `scene-${index + 1}`)}</span>
              <small>{sourceLabel(item)} / {item.caveats?.length ? `${item.caveats.length} caveat` : "ready note"}</small>
            </div>
          ))}
        </div>
      ) : sourceRows.length > 0 && (
        <div className="render-source-strip">
          {sourceRows.map((item, index) => (
            <div key={`${item.sceneId ?? index}-${index}`} className="render-source-pill">
              <span>{String(item.sceneId ?? `scene-${index + 1}`)}</span>
              <small>{String(item.mode ?? item.status ?? "media")} / {String(item.outputKind ?? "asset")}</small>
            </div>
          ))}
        </div>
      )}

      <div className="render-review-caveats">
        {providers.length > 0 ? <span>providers: {providers.join(", ")}</span> : <span>providers: report pending</span>}
        {placeholders > 0 ? (
          <span className="danger">placeholder 컷 교체 필요</span>
        ) : (
          <span>placeholder 없음</span>
        )}
        {videoScenes < totalScenes ? (
          <span className="warn">정지 이미지 컷 검토 필요</span>
        ) : (
          <span>모든 씬 motion source</span>
        )}
        {productionSummary.stockOnly ? <span className="warn">stock-only: 직접/Grok/local 컷 필요</span> : null}
        {channelStatus && channelStatus !== "channel-ready" ? <span className="warn">채널 원본성: {channelReadinessLabel(channelStatus)}</span> : null}
        {uploadReviewStatus && uploadReviewStatus !== "ready" ? <span className="warn">업로드 검수: {uploadReviewLabel(uploadReviewStatus)}</span> : null}
        {missingRationaleCount > 0 ? <span className="warn">선택 근거 누락 {missingRationaleCount}</span> : null}
        {missingContinuityCount > 0 ? <span className="warn">연속성 메모 누락 {missingContinuityCount}</span> : null}
        {productionSummary.firstSceneHookReady === false ? <span className="warn">첫 2초 hook 점검 필요</span> : null}
      </div>
    </section>
  );
}

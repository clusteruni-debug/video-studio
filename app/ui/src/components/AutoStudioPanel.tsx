import { useEffect, useMemo, useState } from "react";
import { Clapperboard, Image as ImageIcon, Loader2, Play, RefreshCw, Sparkles, Video } from "lucide-react";
import {
  fetchAutoStudioProviders,
  runAutoStudio,
  type AutoStudioProvider,
  type AutoStudioProviderRegistry,
  type AutoStudioRunResult,
  type RenderSmokeResult,
} from "../lib/bridge";
import { useStudioActions, useStudioState } from "../context/StudioContext";
import SceneDirectorPanel from "./SceneDirectorPanel";

type RenderMode = "draft" | "smoke";

const providerIcon = (provider: AutoStudioProvider) => {
  if (provider.key === "grok") return Clapperboard;
  if (provider.mediaKind.includes("video")) return Video;
  return ImageIcon;
};

function providerStateLabel(provider: AutoStudioProvider) {
  const mode = provider.executionMode || provider.mode;
  if (mode === "operator-handoff") return "handoff";
  if (mode === "manual-import") return "manual";
  if (mode === "command") return provider.ready ? "command" : "setup";
  if (provider.canGenerateNow || provider.renderableNow) return "draft";
  return "setup";
}

function providerClass(provider: AutoStudioProvider, active: boolean) {
  return [
    "auto-provider-card",
    active ? "active" : "",
    provider.requiresOperatorProof ? "manual" : "",
    (provider.executionMode || provider.mode) === "manual-import" ? "future" : "",
  ].filter(Boolean).join(" ");
}

function renderResultForStudio(result: AutoStudioRunResult): RenderSmokeResult | null {
  const raw = result.renderResult;
  if (!raw || typeof raw !== "object") return null;
  const renderResult = raw as RenderSmokeResult["renderResult"];
  return {
    ok: Boolean(renderResult?.ok),
    saveResult: result.projectSave?.["saveResult"] as Record<string, unknown> | undefined,
    renderResult,
  };
}

export default function AutoStudioPanel() {
  const { templateType, tone, lang, targetDuration, subtitleStyle, bgmEnabled } = useStudioState();
  const actions = useStudioActions();
  const [seed, setSeed] = useState("");
  const [providerKey, setProviderKey] = useState("auto-image");
  const [renderMode, setRenderMode] = useState<RenderMode>("draft");
  const [generateAssets, setGenerateAssets] = useState(true);
  const [registry, setRegistry] = useState<AutoStudioProviderRegistry | null>(null);
  const [result, setResult] = useState<AutoStudioRunResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const providers = useMemo(() => registry?.providers ?? [], [registry]);
  const activeProvider = providers.find((provider) => provider.key === providerKey) ?? providers[0];
  const warnings = result?.assetPipeline?.warnings ?? [];

  useEffect(() => {
    let cancelled = false;
    fetchAutoStudioProviders()
      .then((payload) => {
        if (cancelled) return;
        setRegistry(payload);
        if (payload.defaultProvider) setProviderKey(payload.defaultProvider);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Auto Studio provider 확인 실패");
      });
    return () => { cancelled = true; };
  }, []);

  const run = async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const payload = await runAutoStudio({
        seed,
        assetProvider: providerKey,
        renderMode,
        generateAssets,
        templateType,
        tone,
        lang,
        targetDuration,
        subtitleStyle,
        bgmEnabled,
      });
      if (!payload.ok) {
        setError(payload.error || "Auto Studio 실행 실패");
        return;
      }
      setResult(payload);
      if (payload.creatorPrompt?.topicPrompt) actions.setPrompt(payload.creatorPrompt.topicPrompt);
      if (payload.draftResult) actions.setDraftResult(payload.draftResult);
      const studioRenderResult = renderResultForStudio(payload);
      if (studioRenderResult) actions.setRenderResult(studioRenderResult);
      actions.setActiveTab(studioRenderResult?.ok ? "review" : "plan");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Auto Studio 연결 실패");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="auto-studio-panel">
      <div className="auto-studio-head">
        <div>
          <span className="workspace-kicker">Auto Studio MVP</span>
          <h2>소재에서 초안까지 자동 실행</h2>
        </div>
        <button className="icon-button subtle" onClick={() => fetchAutoStudioProviders().then(setRegistry)} title="provider 새로고침">
          <RefreshCw size={15} />
        </button>
      </div>

      <div className="auto-studio-controls">
        <label className="auto-studio-field">
          <span>Seed</span>
          <input
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
            placeholder="비워두면 오늘 한국 핫 소재"
          />
        </label>
        <div className="auto-studio-segment">
          <button className={renderMode === "draft" ? "active" : ""} onClick={() => setRenderMode("draft")}>
            초안
          </button>
          <button className={renderMode === "smoke" ? "active" : ""} onClick={() => setRenderMode("smoke")}>
            MP4
          </button>
        </div>
        <label className="auto-studio-check">
          <input
            type="checkbox"
            checked={generateAssets}
            onChange={(event) => setGenerateAssets(event.target.checked)}
          />
          <span>에셋 생성</span>
        </label>
        <button className="workspace-primary-action" disabled={loading} onClick={run}>
          {loading ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
          {loading ? "실행 중" : "자동 실행"}
        </button>
      </div>

      <div className="auto-provider-grid">
        {providers.map((provider) => {
          const Icon = providerIcon(provider);
          return (
            <button
              key={provider.key}
              className={providerClass(provider, provider.key === providerKey)}
              onClick={() => setProviderKey(provider.key)}
              title={provider.proofBoundary || provider.adapterInterface}
            >
              <span className="auto-provider-icon"><Icon size={16} /></span>
              <strong>{provider.label}</strong>
              <small>{providerStateLabel(provider)}</small>
            </button>
          );
        })}
      </div>

      {activeProvider && (
        <div className={`auto-studio-provider-note ${activeProvider.requiresOperatorProof ? "manual" : ""}`}>
          <Sparkles size={15} />
          <span>{activeProvider.proofBoundary || activeProvider.adapterInterface || activeProvider.detail}</span>
        </div>
      )}

      {error && <div className="auto-studio-error">{error}</div>}

      {result && (
        <div className="auto-studio-result">
          <div>
            <span>{result.status}</span>
            <strong>{result.selectedCandidate?.title || result.creatorPrompt?.title}</strong>
            <small>{result.runId}</small>
          </div>
          <div className="auto-studio-metrics">
            <span>{String(result.metrics?.sceneCount ?? 0)} scenes</span>
            <span>{String(result.metrics?.attachedSceneAssetCount ?? 0)} assets</span>
            <span>{String(result.metrics?.paidProviderUsage ?? 0)} paid</span>
          </div>
          {warnings.length > 0 && (
            <ul>
              {warnings.slice(0, 3).map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}
            </ul>
          )}
        </div>
      )}

      <SceneDirectorPanel run={result} providers={providers} />
    </section>
  );
}

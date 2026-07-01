import { Clipboard, ExternalLink, FileUp, RotateCcw, ShieldAlert, UploadCloud } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import {
  importAutoStudioSceneAsset,
  updateAutoStudioHandoffTask,
  type AutoStudioHandoffTask,
  type AutoStudioProvider,
  type AutoStudioRunResult,
  type HandoffTaskStatus,
  type SceneAssetPayload,
} from "../lib/bridge";
import { useStudioActions, useStudioState } from "../context/StudioContext";

type Props = {
  run: AutoStudioRunResult | null;
  providers: AutoStudioProvider[];
};

const handoffStatuses: Record<HandoffTaskStatus, string> = {
  queued: "queued",
  "prompt-copied": "prompt-copied",
  "operator-generated": "operator-generated",
  imported: "imported",
  blocked: "blocked",
  "fallback-used": "fallback-used",
};

function sceneIdFor(sceneNum: number, index: number) {
  const n = Number.isFinite(sceneNum) && sceneNum > 0 ? sceneNum : index + 1;
  return `scene-${String(n).padStart(2, "0")}`;
}

function readFileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("file-read-failed"));
    reader.onload = () => {
      const value = String(reader.result ?? "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    };
    reader.readAsDataURL(file);
  });
}

function assetLabel(asset?: SceneAssetPayload | null) {
  if (!asset?.sourcePath && !asset?.fileName) return "no imported asset";
  return asset.fileName || asset.sourcePath || "imported asset";
}

function isHandoffProvider(provider?: AutoStudioProvider) {
  const mode = provider?.executionMode || provider?.mode;
  return mode === "operator-handoff" || mode === "manual-import";
}

export default function SceneDirectorPanel({ run, providers }: Props) {
  const { draftResult } = useStudioState();
  const actions = useStudioActions();
  const [statusOverrides, setStatusOverrides] = useState<Record<string, HandoffTaskStatus>>({});
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  const scenes = draftResult?.scenes ?? [];
  const runId = run?.runId || "";
  const queue = run?.assetPipeline?.handoffQueue ?? [];
  const queueByScene = useMemo(() => {
    const map = new Map<string, AutoStudioHandoffTask>();
    for (const task of queue) map.set(task.sceneId, task);
    return map;
  }, [queue]);
  const providerByKey = useMemo(() => {
    const map = new Map<string, AutoStudioProvider>();
    for (const provider of providers) map.set(provider.key, provider);
    return map;
  }, [providers]);
  const importedByScene = useMemo(() => {
    const map = new Map<string, SceneAssetPayload>();
    for (const asset of run?.assetPipeline?.importedSceneAssets ?? []) map.set(asset.sceneId, asset);
    return map;
  }, [run?.assetPipeline?.importedSceneAssets]);

  if (!scenes.length && !queue.length) return null;

  const markTask = async (task: AutoStudioHandoffTask | undefined, status: HandoffTaskStatus, sourceSurface = "") => {
    if (!task?.taskId) return;
    setBusyTaskId(task.taskId);
    setStatusOverrides((prev) => ({ ...prev, [task.taskId]: status }));
    const sceneIndex = scenes.findIndex((scene, index) => sceneIdFor(scene.scene_num, index) === task.sceneId);
    if (sceneIndex >= 0) actions.editScene(sceneIndex, "handoff_status", status);
    try {
      if (runId) {
        const result = await updateAutoStudioHandoffTask({
          runId,
          taskId: task.taskId,
          status,
          sourceSurface,
        });
        if (!result.ok) setNotice(result.error || "handoff status update failed");
      }
    } finally {
      setBusyTaskId(null);
    }
  };

  const copyPrompt = async (task: AutoStudioHandoffTask | undefined) => {
    if (!task) return;
    await navigator.clipboard.writeText(task.prompt || "");
    await markTask(task, "prompt-copied");
  };

  const importFile = async (task: AutoStudioHandoffTask | undefined, sceneIndex: number, file: File | null) => {
    if (!task || !file || !runId) return;
    setBusyTaskId(task.taskId);
    setNotice(null);
    try {
      const fileBase64 = await readFileBase64(file);
      const result = await importAutoStudioSceneAsset({
        runId,
        sceneId: task.sceneId,
        provider: task.provider,
        handoffTaskId: task.taskId,
        prompt: task.prompt,
        fileName: file.name,
        fileBase64,
        sourceSurface: task.targetUrl || task.provider,
        operatorNote: "Imported through dashboard Scene Director.",
        proofMode: "operator-local-import",
      });
      if (!result.ok || !result.asset) {
        setNotice(result.error || "asset import failed");
        return;
      }
      const asset = result.asset;
      actions.editScene(sceneIndex, "image_source", task.provider);
      actions.editScene(sceneIndex, "handoff_provider", task.provider);
      actions.editScene(sceneIndex, "handoff_status", "imported");
      actions.editScene(sceneIndex, "handoff_task_id", task.taskId);
      actions.editScene(sceneIndex, "handoff_expected_file", task.expectedFileName);
      actions.editScene(sceneIndex, "handoff_target_url", task.targetUrl || "");
      actions.editScene(sceneIndex, "handoff_output_kind", task.outputKind);
      actions.editScene(sceneIndex, "handoff_provenance_path", result.provenancePath || asset.provenancePath || "");
      actions.editScene(sceneIndex, "_upload_preview", asset.previewUrl || null);
      actions.editScene(sceneIndex, "_upload_file", null);
      actions.editScene(sceneIndex, "_upload_kind", asset.mimeType === "video/mp4" ? "video" : "image");
      actions.editScene(sceneIndex, "_upload_name", asset.fileName);
      actions.editScene(sceneIndex, "_upload_mime", asset.mimeType || null);
      actions.editScene(sceneIndex, "_server_asset_path", asset.sourcePath || null);
      actions.editScene(sceneIndex, "_server_asset_preview_url", asset.previewUrl || null);
      actions.editScene(sceneIndex, "_server_asset_mime", asset.mimeType || null);
      actions.editScene(sceneIndex, "_video_url", asset.previewUrl || null);
      actions.editScene(sceneIndex, "_selected_pexels_video", null);
      actions.editScene(sceneIndex, "has_image", true);
      actions.editScene(sceneIndex, "source_rationale", `${task.provider} local import: ${asset.sourcePath || asset.fileName}.`);
      actions.editScene(sceneIndex, "originality_evidence", `Operator import sidecar: ${result.provenancePath || asset.provenancePath || "recorded"}.`);
      setStatusOverrides((prev) => ({ ...prev, [task.taskId]: "imported" }));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "asset import failed");
    } finally {
      setBusyTaskId(null);
    }
  };

  const changeProvider = (sceneIndex: number, providerKey: string) => {
    const provider = providerByKey.get(providerKey);
    actions.editScene(sceneIndex, "image_source", providerKey);
    actions.editScene(sceneIndex, "handoff_provider", isHandoffProvider(provider) ? providerKey : "");
    actions.editScene(sceneIndex, "handoff_status", isHandoffProvider(provider) ? "queued" : "");
    actions.editScene(sceneIndex, "handoff_target_url", provider?.targetUrl || "");
    actions.editScene(sceneIndex, "handoff_output_kind", provider?.expectedOutputKind || "");
    actions.editScene(sceneIndex, "source_rationale", provider?.proofBoundary || "");
  };

  const useFallback = (sceneIndex: number, task: AutoStudioHandoffTask | undefined) => {
    actions.editScene(sceneIndex, "image_source", "pexels-video");
    actions.editScene(sceneIndex, "handoff_provider", "");
    actions.editScene(sceneIndex, "handoff_status", "fallback-used");
    actions.editScene(sceneIndex, "handoff_provenance_path", "");
    actions.editScene(sceneIndex, "source_rationale", "Fallback source selected for draft render only; publish-ready still requires source review.");
    if (task) void markTask(task, "fallback-used");
  };

  return (
    <section className="scene-director-panel">
      <div className="scene-director-head">
        <div>
          <span className="workspace-kicker">Scene Director</span>
          <h3>장면별 handoff와 import readiness</h3>
        </div>
        <div className={`scene-readiness-pill ${run?.assetPipeline?.renderReadiness?.renderReady ? "ready" : "blocked"}`}>
          {run?.assetPipeline?.renderReadiness?.renderReady ? "render-ready" : "import proof needed"}
        </div>
      </div>

      {notice && <div className="scene-director-notice">{notice}</div>}

      <div className="scene-director-grid">
        {scenes.map((scene, index) => {
          const sceneId = sceneIdFor(scene.scene_num, index);
          const task = queueByScene.get(sceneId);
          const providerKey = scene.handoff_provider || task?.provider || scene.image_source || "auto-image";
          const provider = providerByKey.get(providerKey);
          const status = task ? (statusOverrides[task.taskId] || scene.handoff_status || task.status) : scene.handoff_status;
          const imported = importedByScene.get(sceneId);
          const currentAsset = imported || (
            scene._server_asset_path
              ? { sceneId, role: "visual" as const, fileName: scene._upload_name || scene._server_asset_path, sourcePath: scene._server_asset_path, mimeType: scene._server_asset_mime || undefined }
              : null
          );
          const ready = Boolean(scene._upload_file || scene._server_asset_path || !isHandoffProvider(provider));
          return (
            <article key={sceneId} className={`scene-director-card ${ready ? "ready" : "blocked"}`}>
              <div className="scene-director-card-head">
                <div>
                  <strong>{sceneId}</strong>
                  <span>{scene.display_text || scene.image_prompt || "Untitled scene"}</span>
                </div>
                <small>{status ? handoffStatuses[status as HandoffTaskStatus] || status : "draft"}</small>
              </div>

              <div className="scene-director-fields">
                <label>
                  <span>Provider</span>
                  <select value={providerKey} onChange={(event) => changeProvider(index, event.target.value)}>
                    {providers.map((item) => (
                      <option key={item.key} value={item.key}>{item.label}</option>
                    ))}
                  </select>
                </label>
                <div>
                  <span>Expected</span>
                  <strong>{task?.expectedFileName || scene.handoff_expected_file || scene._upload_kind || "draft asset"}</strong>
                </div>
                <div>
                  <span>Current asset</span>
                  <strong>{assetLabel(currentAsset)}</strong>
                </div>
              </div>

              <p className="scene-director-prompt">{task?.prompt || scene.grok_prompt || scene.image_prompt}</p>

              {!ready && (
                <div className="scene-director-warning">
                  <ShieldAlert size={14} />
                  <span>{provider?.proofBoundary || task?.proofBoundary || "local import proof required"}</span>
                </div>
              )}

              <div className="scene-director-actions">
                <button className="workflow-secondary-action" disabled={!task?.targetUrl} onClick={() => task?.targetUrl && window.open(task.targetUrl, "_blank", "noopener,noreferrer")}>
                  <ExternalLink size={14} />
                  Open Provider
                </button>
                <button className="workflow-secondary-action" disabled={!task?.prompt || busyTaskId === task?.taskId} onClick={() => copyPrompt(task)}>
                  <Clipboard size={14} />
                  Copy Prompt
                </button>
                <button className="workflow-secondary-action" disabled={!task || busyTaskId === task.taskId} onClick={() => markTask(task, "operator-generated")}>
                  <UploadCloud size={14} />
                  Mark Generated
                </button>
                <button className="workflow-secondary-action" disabled={!task || busyTaskId === task.taskId} onClick={() => task && fileInputs.current[task.taskId]?.click()}>
                  <FileUp size={14} />
                  Import File
                </button>
                <button className="workflow-secondary-action" onClick={() => useFallback(index, task)}>
                  <RotateCcw size={14} />
                  Use Fallback
                </button>
                {task && (
                  <input
                    ref={(element) => { fileInputs.current[task.taskId] = element; }}
                    type="file"
                    accept=".png,.mp4,image/png,video/mp4"
                    hidden
                    onChange={(event) => {
                      const file = event.target.files?.[0] ?? null;
                      event.target.value = "";
                      void importFile(task, index, file);
                    }}
                  />
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

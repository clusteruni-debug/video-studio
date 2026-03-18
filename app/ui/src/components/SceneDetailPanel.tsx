import type { StudioProjectRecord } from "../lib/planner";
import {
    assetKey,
    localizeReason,
    manifestUploadedAsset,
    routeLabel,
    sceneAssetAccept,
    sceneAssetHint,
    sceneAssetLabel,
    visualProviderOptions,
    type LocalSceneAsset,
    type SceneAssetRole,
} from "./shared";

export interface SceneDetailPanelProps {
    project: StudioProjectRecord;
    sceneId: string;
    sceneAssets: Record<string, LocalSceneAsset>;
    clearedAssetKeys: Record<string, true>;
    providerOverrides: Record<string, string>;
    onSelectAsset: (projectId: string, sceneId: string, role: SceneAssetRole, file: File | null) => void;
    onClearAsset: (projectId: string, sceneId: string, role: SceneAssetRole) => void;
    onProviderOverride: (projectId: string, sceneId: string, provider: string) => void;
    onClose: () => void;
}

export default function SceneDetailPanel(props: SceneDetailPanelProps) {
    const {
        project, sceneId, sceneAssets, clearedAssetKeys, providerOverrides,
        onSelectAsset, onClearAsset, onProviderOverride, onClose,
    } = props;

    const scene = project.plan.scenes.find((s) => s.id === sceneId);
    const route = project.routes.find((r) => r.sceneId === sceneId);
    const manifestScene = project.manifest.scenes.find((s) => s.sceneId === sceneId);

    if (!scene) return null;

    const roles: SceneAssetRole[] = ["visual", "audio", "sfx"];

    return (
        <div className="scene-detail">
            <div className="scene-detail-header">
                <div className="scene-detail-title-group">
                    <span className={`route-badge route-${route?.route ?? "local"}`}>
                        {routeLabel(route?.route ?? "local")}
                    </span>
                    <h3>{scene.title}</h3>
                    <span className="scene-detail-duration">{scene.durationSec.toFixed(1)}초</span>
                </div>
                <button className="scene-detail-close" type="button" onClick={onClose}>✕</button>
            </div>

            <p className="scene-detail-prompt">{scene.prompt}</p>

            <div className="scene-detail-meta">
                <div className="scene-detail-scores">
                    <span>우선도 {scene.priority}</span>
                    <span>현실감 {scene.humanRealism}</span>
                    <span>오디오 {scene.nativeAudioNeed}</span>
                </div>
                <div className="scene-detail-provider">
                    <label className="summary-label">비주얼 프로바이더</label>
                    <select
                        value={providerOverrides[sceneId] ?? ""}
                        onChange={(e) => onProviderOverride(project.id, sceneId, e.target.value)}
                    >
                        <option value="">자동</option>
                        {visualProviderOptions(manifestScene?.visualKind).map((opt) => (
                            <option key={opt.key} value={opt.key}>{opt.label}</option>
                        ))}
                    </select>
                </div>
            </div>

            <div className="scene-detail-assets">
                {roles.map((role) => {
                    const key = assetKey(project.id, sceneId, role);
                    const draft = sceneAssets[key];
                    const cleared = Boolean(clearedAssetKeys[key]);
                    const uploaded = manifestUploadedAsset(project, sceneId, role, cleared);

                    return (
                        <div key={role} className="scene-detail-asset-row">
                            <div className="scene-detail-asset-info">
                                <span className="summary-label">{sceneAssetLabel(role)}</span>
                                <span className="scene-detail-asset-status">
                                    {draft
                                        ? draft.file.name
                                        : uploaded
                                        ? uploaded.sourceLabel ?? "저장된 자산"
                                        : sceneAssetHint(role)}
                                </span>
                            </div>
                            <div className="scene-detail-asset-actions">
                                <label className="upload-chip">
                                    파일 선택
                                    <input
                                        type="file"
                                        accept={sceneAssetAccept(role)}
                                        onChange={(e) => {
                                            onSelectAsset(project.id, sceneId, role, e.target.files?.[0] ?? null);
                                            e.currentTarget.value = "";
                                        }}
                                    />
                                </label>
                                {(draft || uploaded) ? (
                                    <button className="ghost-chip" type="button" onClick={() => onClearAsset(project.id, sceneId, role)}>
                                        해제
                                    </button>
                                ) : null}
                            </div>
                            {role === "visual" && draft?.previewUrl ? (
                                draft.file.type.startsWith("video/") ? (
                                    <video className="scene-detail-preview" src={draft.previewUrl} muted playsInline />
                                ) : (
                                    <img className="scene-detail-preview" src={draft.previewUrl} alt={`${scene.title} preview`} />
                                )
                            ) : null}
                        </div>
                    );
                })}
            </div>

            <div className="scene-detail-footer">
                <strong>{scene.subtitleText}</strong>
                <small>{localizeReason(route?.reason)}</small>
            </div>
        </div>
    );
}

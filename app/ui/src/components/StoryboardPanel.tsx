import type { StudioProjectRecord } from "../lib/planner";
import {
    assetKey,
    audioKindLabel,
    formatUsd,
    routeLabel,
    visualKindLabel,
    type LocalSceneAsset,
    type SceneAssetRole,
} from "./shared";
import SceneDetailPanel from "./SceneDetailPanel";

export interface StoryboardPanelProps {
    selectedProject: StudioProjectRecord | null;
    sceneAssets: Record<string, LocalSceneAsset>;
    clearedAssetKeys: Record<string, true>;
    providerOverrides: Record<string, string>;
    selectedSceneId: string | null;
    onSelectScene: (sceneId: string | null) => void;
    onSelectAsset: (projectId: string, sceneId: string, role: SceneAssetRole, file: File | null) => void;
    onClearAsset: (projectId: string, sceneId: string, role: SceneAssetRole) => void;
    onProviderOverride: (projectId: string, sceneId: string, provider: string) => void;
    onGenerateSceneImages: () => void;
    isGeneratingSceneImages: boolean;
    sceneImageProgress: string;
}

export default function StoryboardPanel(props: StoryboardPanelProps) {
    const {
        selectedProject, sceneAssets, clearedAssetKeys, providerOverrides,
        selectedSceneId, onSelectScene,
        onSelectAsset, onClearAsset, onProviderOverride,
        onGenerateSceneImages, isGeneratingSceneImages, sceneImageProgress,
    } = props;

    if (!selectedProject) {
        return (
            <div className="main-canvas">
                <div className="canvas-empty">
                    <div className="canvas-empty-icon">▶</div>
                    <h2>영상 프로젝트 시작</h2>
                    <p>좌측에 프롬프트를 입력하고 생성 버튼을 누르세요</p>
                </div>
            </div>
        );
    }

    const totalDuration = selectedProject.manifest.totalDurationSec;
    const sceneCount = selectedProject.plan.scenes.length;
    const totalCost = selectedProject.estimatedCostUsd;

    return (
        <div className="main-canvas">
            {/* Compact project header */}
            <div className="canvas-header">
                <span className="canvas-header-title">{selectedProject.plan.title}</span>
                <span className="canvas-header-meta">
                    {sceneCount}장면 · {totalDuration.toFixed(1)}초 · {totalCost === 0 ? "무료" : formatUsd(totalCost)}
                </span>
                {sceneCount > 0 && (
                    <button
                        className="subtle-button"
                        type="button"
                        onClick={onGenerateSceneImages}
                        disabled={isGeneratingSceneImages}
                    >
                        {isGeneratingSceneImages ? sceneImageProgress : "장면 이미지 일괄 생성"}
                    </button>
                )}
            </div>

            {/* Visual scene grid */}
            <div className="scene-grid">
                {selectedProject.plan.scenes.map((scene) => {
                    const route = selectedProject.routes.find((r) => r.sceneId === scene.id);
                    const manifestScene = selectedProject.manifest.scenes.find((s) => s.sceneId === scene.id);
                    const visualKey = assetKey(selectedProject.id, scene.id, "visual");
                    const draft = sceneAssets[visualKey];
                    const isSelected = selectedSceneId === scene.id;

                    return (
                        <button
                            key={scene.id}
                            className={`scene-card-visual ${isSelected ? "selected" : ""}`}
                            type="button"
                            onClick={() => onSelectScene(isSelected ? null : scene.id)}
                        >
                            <div className="scene-card-thumb">
                                {draft?.previewUrl ? (
                                    draft.file.type.startsWith("video/") ? (
                                        <video src={draft.previewUrl} muted playsInline />
                                    ) : (
                                        <img src={draft.previewUrl} alt={scene.title} />
                                    )
                                ) : (
                                    <div className="scene-card-placeholder" />
                                )}
                                <div className="scene-card-overlays">
                                    <span className={`route-badge route-${route?.route ?? "local"}`}>
                                        {routeLabel(route?.route ?? "local")}
                                    </span>
                                    <span className="scene-card-duration">{scene.durationSec.toFixed(1)}초</span>
                                </div>
                            </div>
                            <div className="scene-card-info">
                                <strong>{scene.title}</strong>
                                <span>
                                    {visualKindLabel(manifestScene?.visualKind)} · {audioKindLabel(manifestScene?.audioKind)}
                                </span>
                            </div>
                        </button>
                    );
                })}
            </div>

            {/* Scene detail panel — shown when a scene is selected */}
            {selectedSceneId && (
                <SceneDetailPanel
                    project={selectedProject}
                    sceneId={selectedSceneId}
                    sceneAssets={sceneAssets}
                    clearedAssetKeys={clearedAssetKeys}
                    providerOverrides={providerOverrides}
                    onSelectAsset={onSelectAsset}
                    onClearAsset={onClearAsset}
                    onProviderOverride={onProviderOverride}
                    onClose={() => onSelectScene(null)}
                />
            )}
        </div>
    );
}

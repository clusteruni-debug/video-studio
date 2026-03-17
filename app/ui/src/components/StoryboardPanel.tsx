import type { StudioProjectRecord } from "../lib/planner";
import {
    assetKey,
    audioKindLabel,
    budgetModeLabel,
    formatUsd,
    localizeReason,
    manifestUploadedAsset,
    plannerLabel,
    routeHintCopy,
    routeLabel,
    sceneAssetAccept,
    sceneAssetHint,
    sceneAssetLabel,
    visualKindLabel,
    type LocalSceneAsset,
    type SceneAssetRole,
} from "./shared";

export interface StoryboardPanelProps {
    selectedProject: StudioProjectRecord | null;
    sceneAssets: Record<string, LocalSceneAsset>;
    clearedAssetKeys: Record<string, true>;
    onSelectAsset: (projectId: string, sceneId: string, role: SceneAssetRole, file: File | null) => void;
    onClearAsset: (projectId: string, sceneId: string, role: SceneAssetRole) => void;
}

export default function StoryboardPanel(props: StoryboardPanelProps) {
    const { selectedProject, sceneAssets, clearedAssetKeys, onSelectAsset, onClearAsset } = props;

    if (!selectedProject) {
        return (
            <section className="panel storyboard-panel">
                <div className="panel-header">
                    <span className="panel-index">02</span>
                    <div>
                        <h2>장면 보드</h2>
                        <p>실제 생성 전에 장면 수, 길이, 프리미엄 사용 여부를 먼저 보고 결정합니다.</p>
                    </div>
                </div>
                <div className="empty-panel">
                    <p>아직 장면 초안이 없습니다. 왼쪽에서 프롬프트를 입력하고 초안을 생성해 주세요.</p>
                </div>
            </section>
        );
    }

    const totalCost = selectedProject.estimatedCostUsd;
    const paidScenes = selectedProject.routes.filter((r) => r.route !== "local").length;

    return (
        <section className="panel storyboard-panel">
            <div className="panel-header">
                <span className="panel-index">02</span>
                <div>
                    <h2>장면 보드</h2>
                    <p>실제 생성 전에 장면 수, 길이, 프리미엄 사용 여부를 먼저 보고 결정합니다.</p>
                </div>
            </div>

            <div className="project-brief-card">
                <span className="summary-label">현재 선택된 프로젝트</span>
                <h3>{selectedProject.plan.title}</h3>
                <p>{selectedProject.plan.sourcePrompt}</p>
                <div className="project-brief-tags">
                    <span>{selectedProject.plan.aspectRatio}</span>
                    <span>{budgetModeLabel(selectedProject.plan.budgetMode)}</span>
                    <span>{plannerLabel(selectedProject.planner)}</span>
                    <span>{formatUsd(selectedProject.estimatedCostUsd)}</span>
                </div>
            </div>

            <div className="cost-preview-bar">
                <span className="summary-label">예상 비용</span>
                <strong>
                    {totalCost === 0
                        ? `무료 ${selectedProject.plan.scenes.length}장면`
                        : `${formatUsd(totalCost)} (유료 ${paidScenes}장면)`}
                </strong>
            </div>

            <div className="summary-strip">
                <div>
                    <span className="summary-label">화면 비율</span>
                    <strong>{selectedProject.plan.aspectRatio}</strong>
                </div>
                <div>
                    <span className="summary-label">예산 모드</span>
                    <strong>{budgetModeLabel(selectedProject.plan.budgetMode)}</strong>
                </div>
                <div>
                    <span className="summary-label">예상 비용</span>
                    <strong>{formatUsd(selectedProject.estimatedCostUsd)}</strong>
                </div>
                <div>
                    <span className="summary-label">기획 엔진</span>
                    <strong>{plannerLabel(selectedProject.planner)}</strong>
                </div>
                <div>
                    <span className="summary-label">출력 파일</span>
                    <strong>{selectedProject.manifest.outputPath}</strong>
                </div>
            </div>

            <p className="bridge-message">
                장면별로 고른 파일은 현재 브라우저 세션에서 유지되고, 저장이나 렌더를 누를 때
                `storage/inputs/.../uploads` 아래로 복사됩니다.
            </p>

            <div className="scene-list">
                {selectedProject.plan.scenes.map((scene) => {
                    const route = selectedProject.routes.find((item) => item.sceneId === scene.id);
                    const manifestScene = selectedProject.manifest.scenes.find((item) => item.sceneId === scene.id);
                    const visualKey = assetKey(selectedProject.id, scene.id, "visual");
                    const audioKey = assetKey(selectedProject.id, scene.id, "audio");
                    const visualDraft = sceneAssets[visualKey];
                    const audioDraft = sceneAssets[audioKey];
                    const visualCleared = Boolean(clearedAssetKeys[visualKey]);
                    const audioCleared = Boolean(clearedAssetKeys[audioKey]);
                    const uploadedVisual = manifestUploadedAsset(selectedProject, scene.id, "visual", visualCleared);
                    const uploadedAudio = manifestUploadedAsset(selectedProject, scene.id, "audio", audioCleared);

                    return (
                        <article key={scene.id} className="scene-card">
                            <div className="scene-meta">
                                <div className="scene-badge-group">
                                    <span className={`route-badge route-${route?.route ?? "local"}`}>{routeLabel(route?.route ?? "local")}</span>
                                    <span className="mini-chip">{routeHintCopy(route?.route ?? "local")}</span>
                                </div>
                                <span className="scene-duration">{scene.durationSec.toFixed(1)}초</span>
                            </div>
                            <h3>{scene.title}</h3>
                            <p>{scene.prompt}</p>
                            <div className="scene-scores">
                                <span>우선도 {scene.priority}</span>
                                <span>현실감 {scene.humanRealism}</span>
                                <span>오디오 {scene.nativeAudioNeed}</span>
                            </div>
                            <div className="scene-pipeline">
                                <span>{visualKindLabel(manifestScene?.visualKind)}</span>
                                <span>{audioKindLabel(manifestScene?.audioKind)}</span>
                                <span>{manifestScene?.cacheDir ?? "storage/cache"}</span>
                            </div>
                            <div className="scene-assets">
                                <SceneAssetCard
                                    role="visual"
                                    sceneTitle={scene.title}
                                    draftAsset={visualDraft}
                                    uploadedAsset={uploadedVisual}
                                    durationSec={scene.durationSec}
                                    onSelect={(file) => onSelectAsset(selectedProject.id, scene.id, "visual", file)}
                                    onClear={() => onClearAsset(selectedProject.id, scene.id, "visual")}
                                />
                                <SceneAssetCard
                                    role="audio"
                                    sceneTitle={scene.title}
                                    draftAsset={audioDraft}
                                    uploadedAsset={uploadedAudio}
                                    durationSec={scene.durationSec}
                                    onSelect={(file) => onSelectAsset(selectedProject.id, scene.id, "audio", file)}
                                    onClear={() => onClearAsset(selectedProject.id, scene.id, "audio")}
                                />
                            </div>
                            <div className="scene-footer">
                                <strong>{scene.subtitleText}</strong>
                                <small>{localizeReason(route?.reason)}</small>
                            </div>
                        </article>
                    );
                })}
            </div>
        </section>
    );
}

function SceneAssetCard(props: {
    role: SceneAssetRole;
    sceneTitle: string;
    draftAsset: LocalSceneAsset | undefined;
    uploadedAsset: ReturnType<typeof manifestUploadedAsset>;
    durationSec: number;
    onSelect: (file: File | null) => void;
    onClear: () => void;
}) {
    const { role, sceneTitle, draftAsset, uploadedAsset, durationSec, onSelect, onClear } = props;

    return (
        <section className="scene-asset-card">
            <div className="scene-asset-header">
                <div>
                    <span className="summary-label">{sceneAssetLabel(role)}</span>
                    <strong>
                        {role === "visual"
                            ? draftAsset?.file.name ?? uploadedAsset?.sourceLabel ?? "아직 연결하지 않음"
                            : draftAsset?.file.name ?? uploadedAsset?.sourceLabel ?? "자막으로 자동 보이스오버 생성"}
                    </strong>
                    <small>
                        {draftAsset
                            ? role === "visual"
                                ? "이 세션에서 선택됨 · 저장이나 렌더 시 업로드"
                                : "이 세션에서 선택됨 · 장면 음성으로 우선 사용"
                            : uploadedAsset?.sourcePath ?? sceneAssetHint(role)}
                    </small>
                </div>
                <div className="scene-asset-actions">
                    <label className="upload-chip">
                        파일 선택
                        <input
                            type="file"
                            accept={sceneAssetAccept(role)}
                            onChange={(event) => {
                                onSelect(event.target.files?.[0] ?? null);
                                event.currentTarget.value = "";
                            }}
                        />
                    </label>
                    {(draftAsset || uploadedAsset) ? (
                        <button className="ghost-chip" type="button" onClick={onClear}>
                            해제
                        </button>
                    ) : null}
                </div>
            </div>
            {role === "visual" ? (
                draftAsset?.previewUrl ? (
                    draftAsset.file.type.startsWith("video/") ? (
                        <video className="scene-asset-preview" src={draftAsset.previewUrl} muted playsInline />
                    ) : (
                        <img className="scene-asset-preview" src={draftAsset.previewUrl} alt={`${sceneTitle} visual preview`} />
                    )
                ) : (
                    <div className="asset-placeholder">
                        {uploadedAsset ? "이전에 저장된 업로드 자산이 연결되어 있습니다." : "선택하지 않으면 자동 카드 비주얼을 사용합니다."}
                    </div>
                )
            ) : (
                <div className="asset-audio-pill-row">
                    <span className="mini-chip">{draftAsset ? "세션 업로드 대기" : uploadedAsset ? "저장된 업로드" : "자동 TTS"}</span>
                    <span className="mini-chip">{durationSec.toFixed(1)}초 장면 길이</span>
                </div>
            )}
        </section>
    );
}

import { useState } from "react";
import type { BudgetMode } from "../../../../shared/contracts/plan";
import type { ProviderAvailability, StudioProjectRecord } from "../lib/planner";
import {
    IMAGE_ENGINES,
    IMAGE_SIZES,
    formatDate,
    formatUsd,
    type CreationMode,
    type ImageInputMode,
} from "./shared";

export interface SidebarProps {
    creationMode: CreationMode;
    onCreationModeChange: (mode: CreationMode) => void;
    prompt: string;
    onPromptChange: (value: string) => void;
    imageSizeIndex: number;
    onImageSizeIndexChange: (index: number) => void;
    imageEngineIndex: number;
    onImageEngineIndexChange: (index: number) => void;
    budgetMode: BudgetMode;
    onBudgetModeChange: (mode: BudgetMode) => void;
    monthlyCapUsd: number;
    onMonthlyCapUsdChange: (value: number) => void;
    availability: ProviderAvailability;
    onAvailabilityChange: (updater: (current: ProviderAvailability) => ProviderAvailability) => void;
    preferBridge: boolean;
    onPreferBridgeChange: (value: boolean) => void;
    isGenerating: boolean;
    onGenerate: () => void;
    projects: StudioProjectRecord[];
    selectedProjectId: string | null;
    onSelectProject: (id: string) => void;
    onRemoveProject: (id: string) => void;
    imageInputMode: ImageInputMode;
    onImageInputModeChange: (mode: ImageInputMode) => void;
    batchPrompts: string;
    onBatchPromptsChange: (value: string) => void;
    stylePrefix: string;
    onStylePrefixChange: (value: string) => void;
}

type VideoEngine = "local" | "sora2" | "veo3";

export default function Sidebar(props: SidebarProps) {
    const {
        creationMode, onCreationModeChange,
        prompt, onPromptChange,
        imageSizeIndex, onImageSizeIndexChange,
        imageEngineIndex, onImageEngineIndexChange,
        budgetMode, onBudgetModeChange,
        monthlyCapUsd, onMonthlyCapUsdChange,
        availability, onAvailabilityChange,
        preferBridge, onPreferBridgeChange,
        isGenerating, onGenerate,
        projects, selectedProjectId, onSelectProject, onRemoveProject,
        imageInputMode, onImageInputModeChange,
        batchPrompts, onBatchPromptsChange,
        stylePrefix, onStylePrefixChange,
    } = props;

    const [showAdvanced, setShowAdvanced] = useState(false);

    const isImageMode = creationMode === "image";
    const isBatchMode = imageInputMode === "batch";

    const batchLineCount = batchPrompts.split("\n").filter((l) => l.trim()).length;

    function deriveVideoEngine(): VideoEngine {
        if (availability.veo3) return "veo3";
        if (availability.sora2) return "sora2";
        return "local";
    }

    function handleVideoEngineChange(engine: VideoEngine): void {
        onAvailabilityChange(() => ({
            premiumEnabled: engine !== "local",
            sora2: engine === "sora2",
            veo3: engine === "veo3",
        }));
    }

    return (
        <aside className="sidebar">
            {/* Mode toggle */}
            <div className="mode-toggle">
                <button
                    className={`mode-toggle-btn ${isImageMode ? "active" : ""}`}
                    type="button"
                    onClick={() => onCreationModeChange("image")}
                >
                    이미지
                </button>
                <button
                    className={`mode-toggle-btn ${!isImageMode ? "active" : ""}`}
                    type="button"
                    onClick={() => onCreationModeChange("video")}
                >
                    영상
                </button>
            </div>

            {isImageMode && (
                <div className="mode-toggle batch-mode-toggle">
                    <button
                        className={`mode-toggle-btn ${!isBatchMode ? "active" : ""}`}
                        type="button"
                        onClick={() => onImageInputModeChange("single")}
                    >
                        단일
                    </button>
                    <button
                        className={`mode-toggle-btn ${isBatchMode ? "active" : ""}`}
                        type="button"
                        onClick={() => onImageInputModeChange("batch")}
                    >
                        배치
                    </button>
                </div>
            )}

            {isImageMode && (
                <div className="sidebar-section">
                    <label className="sidebar-field">
                        <span>스타일 접두사</span>
                        <textarea
                            className="style-prefix-field"
                            value={stylePrefix}
                            onChange={(e) => onStylePrefixChange(e.target.value)}
                            rows={2}
                            placeholder="예: dark atmospheric pixel art, 8-bit style"
                        />
                    </label>
                </div>
            )}

            <div className="sidebar-section">
                <label className="sidebar-field">
                    <span>{isImageMode && isBatchMode ? "배치 프롬프트" : "프롬프트"}</span>
                    {isImageMode && isBatchMode ? (
                        <textarea
                            value={batchPrompts}
                            onChange={(e) => onBatchPromptsChange(e.target.value)}
                            rows={10}
                            placeholder={"한 줄에 프롬프트 하나씩\n파일명: 프롬프트 (선택)\n예:\nenemy_shadow: dark silhouette creature\nenemy_flame: fire elemental monster"}
                        />
                    ) : (
                        <textarea
                            value={prompt}
                            onChange={(e) => onPromptChange(e.target.value)}
                            rows={5}
                            placeholder={isImageMode
                                ? "예: 노을이 지는 바닷가, 빈티지 필름 느낌"
                                : "예: 차분한 카페 분위기의 30초 인스타 릴스, 부드러운 여성 나레이션"
                            }
                        />
                    )}
                </label>
            </div>

            {/* Engine & settings per mode */}
            {isImageMode ? (
                <div className="sidebar-section">
                    <label className="sidebar-field compact">
                        <span>이미지 엔진</span>
                        <select
                            value={imageEngineIndex}
                            onChange={(e) => onImageEngineIndexChange(Number(e.target.value))}
                        >
                            {IMAGE_ENGINES.map((engine, idx) => (
                                <option key={engine.key} value={idx}>{engine.label}</option>
                            ))}
                        </select>
                    </label>
                    <span className="sidebar-engine-hint">{IMAGE_ENGINES[imageEngineIndex].description}</span>

                    <label className="sidebar-field compact">
                        <span>이미지 크기</span>
                        <select
                            value={imageSizeIndex}
                            onChange={(e) => onImageSizeIndexChange(Number(e.target.value))}
                        >
                            {IMAGE_SIZES.map((size, idx) => (
                                <option key={size.label} value={idx}>{size.label}</option>
                            ))}
                        </select>
                    </label>
                </div>
            ) : (
                <div className="sidebar-section">
                    <label className="sidebar-field compact">
                        <span>영상 엔진</span>
                        <select
                            value={deriveVideoEngine()}
                            onChange={(e) => handleVideoEngineChange(e.target.value as VideoEngine)}
                        >
                            <option value="local">로컬 무료 (Pollinations + Wan)</option>
                            <option value="sora2">Sora 2 (인물 중심)</option>
                            <option value="veo3">Veo 3 (오디오 우선)</option>
                        </select>
                    </label>

                    <label className="sidebar-field compact">
                        <span>예산 모드</span>
                        <select value={budgetMode} onChange={(e) => onBudgetModeChange(e.target.value as BudgetMode)}>
                            <option value="free">무료</option>
                            <option value="standard">표준</option>
                            <option value="premium">프리미엄</option>
                        </select>
                    </label>
                </div>
            )}

            <button className="generate-button" type="button" onClick={onGenerate} disabled={isGenerating || (isImageMode && isBatchMode && batchLineCount === 0)}>
                {isGenerating
                    ? "생성 중..."
                    : isImageMode
                        ? isBatchMode
                            ? `배치 생성 (${batchLineCount}개)`
                            : "이미지 생성"
                        : "스토리보드 생성"}
            </button>

            {!isImageMode && (
                <>
                    <div className="sidebar-section">
                        <button
                            className="sidebar-collapse-toggle"
                            type="button"
                            onClick={() => setShowAdvanced((p) => !p)}
                        >
                            고급 설정 {showAdvanced ? "▲" : "▼"}
                        </button>

                        {showAdvanced && (
                            <div className="sidebar-advanced">
                                <label className="sidebar-field compact">
                                    <span>월 예산 상한 (USD)</span>
                                    <input
                                        type="number"
                                        min={0}
                                        step={5}
                                        value={monthlyCapUsd}
                                        onChange={(e) => onMonthlyCapUsdChange(Number(e.target.value))}
                                    />
                                </label>
                                <label className="sidebar-toggle">
                                    <input type="checkbox" checked={preferBridge} onChange={(e) => onPreferBridgeChange(e.target.checked)} />
                                    <span>브리지 worker 우선</span>
                                </label>
                            </div>
                        )}
                    </div>

                    <div className="sidebar-divider" />

                    <div className="sidebar-history">
                        <span className="sidebar-history-label">최근 초안</span>
                        <div className="sidebar-history-list">
                            {projects.length ? projects.map((project) => (
                                <div
                                    key={project.id}
                                    className={`sidebar-history-item ${project.id === selectedProjectId ? "active" : ""}`}
                                    role="button"
                                    tabIndex={0}
                                    onClick={() => onSelectProject(project.id)}
                                    onKeyDown={(e) => e.key === "Enter" && onSelectProject(project.id)}
                                >
                                    <div className="sidebar-history-text">
                                        <strong>{project.plan.title}</strong>
                                        <span>{formatDate(project.updatedAt)} · {project.manifest.totalDurationSec.toFixed(1)}초 · {formatUsd(project.estimatedCostUsd)}</span>
                                    </div>
                                    <button
                                        className="sidebar-history-remove"
                                        type="button"
                                        onClick={(e) => { e.stopPropagation(); onRemoveProject(project.id); }}
                                    >
                                        ×
                                    </button>
                                </div>
                            )) : (
                                <div className="sidebar-history-empty">아직 생성한 초안이 없습니다.</div>
                            )}
                        </div>
                    </div>
                </>
            )}
        </aside>
    );
}

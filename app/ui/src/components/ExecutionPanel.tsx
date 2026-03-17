import { useState } from "react";
import type { BridgeHealth } from "../lib/bridge";
import {
    buildComposeCommand,
    buildSavePlanCommand,
    buildWorkerCommand,
    type StudioProjectRecord,
} from "../lib/planner";
import { operatorSteps } from "../lib/sample-data";
import {
    bridgeSummary,
    copyLabel,
    formatDate,
    formatUsd,
    localMediaPlanSummaryLabel,
    localMediaRenderSummaryLabel,
    mediaAdapterDetail,
    mediaAdapterState,
    mediaAdapterTitle,
    plannerDetail,
    plannerLabel,
    plannerRuntimeDetail,
    plannerRuntimeLabel,
    toolPath,
    toolState,
    toolTitle,
    type BridgeStatus,
    type CopyState,
    type CopyTarget,
    type RenderState,
    type SaveState,
} from "./shared";

export interface ExecutionPanelProps {
    selectedProject: StudioProjectRecord | null;
    bridgeHealth: BridgeHealth | null;
    bridgeStatus: BridgeStatus;
    saveState: SaveState;
    renderState: RenderState;
    copyState: CopyState;
    projects: StudioProjectRecord[];
    selectedProjectId: string | null;
    onSave: () => void;
    onRender: () => void;
    onRefreshBridge: () => void;
    onCopyCommand: (target: CopyTarget, command: string) => void;
    onExportJson: (filename: string, payload: unknown) => void;
    onRemoveProject: (projectId: string) => void;
    onSelectProject: (projectId: string) => void;
}

export default function ExecutionPanel(props: ExecutionPanelProps) {
    const {
        selectedProject,
        bridgeHealth,
        bridgeStatus,
        saveState,
        renderState,
        copyState,
        projects,
        selectedProjectId,
        onSave,
        onRender,
        onRefreshBridge,
        onCopyCommand,
        onExportJson,
        onRemoveProject,
        onSelectProject,
    } = props;

    const [showAdvanced, setShowAdvanced] = useState(false);

    return (
        <section className="panel diagnostics-panel">
            <div className="panel-header">
                <span className="panel-index">03</span>
                <div>
                    <h2>실행 스테이션</h2>
                    <p>저장, 렌더 실행, 초안 관리를 한곳에 모았습니다.</p>
                </div>
            </div>

            {/* Render controls — always visible */}
            <div className="diag-block">
                <div className="diag-title">즉시 실행</div>
                {selectedProject ? (
                    <>
                        <div className="button-row">
                            <button
                                className="subtle-button"
                                type="button"
                                onClick={onSave}
                                disabled={bridgeStatus !== "connected" || saveState.status === "saving"}
                            >
                                {saveState.status === "saving" ? "저장 중..." : "프로젝트 파일 저장"}
                            </button>
                            <button
                                className="subtle-button"
                                type="button"
                                onClick={onRender}
                                disabled={bridgeStatus !== "connected" || renderState.status === "rendering"}
                            >
                                {renderState.status === "rendering" ? "렌더 중..." : "실제 초안 렌더"}
                            </button>
                            <button className="subtle-button" type="button" onClick={onRefreshBridge}>
                                상태 새로고침
                            </button>
                        </div>
                        {saveState.message ? (
                            <p className={`bridge-message bridge-${saveState.status}`}>{saveState.message}</p>
                        ) : null}
                        {renderState.message ? (
                            <p className={`bridge-message ${renderState.status === "rendered" ? "bridge-saved" : renderState.status === "failed" ? "bridge-failed" : ""}`}>
                                {renderState.message}
                            </p>
                        ) : null}
                    </>
                ) : (
                    <div className="empty-history">초안을 먼저 만든 뒤 저장이나 초안 렌더를 실행할 수 있습니다.</div>
                )}
            </div>

            {/* Recent drafts — always visible */}
            <div className="diag-block">
                <div className="diag-title">최근 초안</div>
                <div className="history-list">
                    {projects.length ? projects.map((project) => (
                        <article key={project.id} className={`history-item ${project.id === selectedProjectId ? "active" : ""}`}>
                            <button
                                className="history-main"
                                type="button"
                                onClick={() => onSelectProject(project.id)}
                            >
                                <div>
                                    <strong>{project.plan.title}</strong>
                                    <span>{formatDate(project.updatedAt)}</span>
                                </div>
                                <div className="history-actions">
                                    <span>{project.manifest.totalDurationSec.toFixed(1)}초</span>
                                    <span>{formatUsd(project.estimatedCostUsd)}</span>
                                </div>
                            </button>
                            <button className="history-remove" type="button" onClick={() => onRemoveProject(project.id)}>
                                삭제
                            </button>
                        </article>
                    )) : <div className="empty-history">생성한 초안은 이 브라우저에 임시 저장됩니다.</div>}
                </div>
            </div>

            {/* Advanced section — collapsible */}
            <div className="diag-block">
                <button
                    className="diag-title advanced-toggle"
                    type="button"
                    onClick={() => setShowAdvanced((prev) => !prev)}
                >
                    고급 {showAdvanced ? "▲" : "▼"}
                </button>

                {showAdvanced && (
                    <>
                        {/* Runtime readiness */}
                        <div className="diag-sub-block">
                            <div className="diag-subtitle">런타임 준비</div>
                            <div className="tool-grid">
                                {bridgeHealth ? (
                                    <>
                                        <article className="tool-card">
                                            <span className="summary-label">기획 엔진</span>
                                            <strong>{plannerRuntimeLabel(bridgeHealth)}</strong>
                                            <small>{plannerRuntimeDetail(bridgeHealth)}</small>
                                        </article>
                                        {Object.values(bridgeHealth.tools).map((tool) => (
                                            <article key={tool.name} className="tool-card">
                                                <span className="summary-label">{toolTitle(tool.name)}</span>
                                                <strong>{toolState(tool)}</strong>
                                                <small>{toolPath(tool)}</small>
                                            </article>
                                        ))}
                                        {Object.values(bridgeHealth.media ?? {}).map((adapter) => (
                                            <article key={adapter.key} className="tool-card">
                                                <span className="summary-label">{mediaAdapterTitle(adapter)}</span>
                                                <strong>{mediaAdapterState(adapter)}</strong>
                                                <small>{mediaAdapterDetail(adapter)}</small>
                                            </article>
                                        ))}
                                    </>
                                ) : (
                                    <div className="empty-history">브리지 상태를 먼저 확인하면 툴 준비 상황이 표시됩니다.</div>
                                )}
                            </div>
                        </div>

                        {/* Operator notes */}
                        <div className="diag-sub-block">
                            <div className="diag-subtitle">운영 메모</div>
                            {selectedProject?.planner ? (
                                <p className="bridge-message">
                                    현재 초안 기획 엔진: <strong>{plannerLabel(selectedProject.planner)}</strong>
                                    <br />
                                    {plannerDetail(selectedProject.planner)}
                                </p>
                            ) : null}
                            <ul className="operator-list">
                                {operatorSteps.map((step) => (
                                    <li key={step}>{step}</li>
                                ))}
                            </ul>
                        </div>

                        {/* Command previews */}
                        <div className="diag-sub-block">
                            <div className="diag-subtitle">작업 명령 미리보기</div>
                            {selectedProject ? (
                                <>
                                    <div className="command-stack">
                                        <div className="command-card">
                                            <span className="summary-label">라우팅 프리뷰</span>
                                            <code className="command-preview">{buildWorkerCommand(selectedProject)}</code>
                                            <button className="subtle-button" type="button" onClick={() => onCopyCommand("route", buildWorkerCommand(selectedProject))}>
                                                {copyLabel(copyState, "route")}
                                            </button>
                                        </div>
                                        <div className="command-card">
                                            <span className="summary-label">프로젝트 저장</span>
                                            <code className="command-preview">{buildSavePlanCommand(selectedProject)}</code>
                                            <button className="subtle-button" type="button" onClick={() => onCopyCommand("save", buildSavePlanCommand(selectedProject))}>
                                                {copyLabel(copyState, "save")}
                                            </button>
                                        </div>
                                        <div className="command-card">
                                            <span className="summary-label">최종 합성 명령 미리보기</span>
                                            <code className="command-preview">{buildComposeCommand(selectedProject)}</code>
                                            <button className="subtle-button" type="button" onClick={() => onCopyCommand("compose", buildComposeCommand(selectedProject))}>
                                                {copyLabel(copyState, "compose")}
                                            </button>
                                        </div>
                                    </div>
                                    <div className="button-row">
                                        <button className="subtle-button" type="button" onClick={() => onExportJson(`${selectedProject.id}.json`, selectedProject)}>
                                            프로젝트 JSON 내보내기
                                        </button>
                                        <button className="subtle-button" type="button" onClick={() => onExportJson(`${selectedProject.manifest.projectId}-render-manifest.json`, selectedProject.manifest)}>
                                            렌더 설계 파일 내보내기
                                        </button>
                                    </div>
                                </>
                            ) : (
                                <div className="empty-history">초안을 만들면 worker 인계 명령이 여기에 나타납니다.</div>
                            )}
                        </div>

                        {/* Storage paths */}
                        <div className="diag-sub-block">
                            <div className="diag-subtitle">저장 위치</div>
                            {selectedProject ? (
                                <div className="storage-grid">
                                    <div>
                                        <span className="summary-label">입력 파일</span>
                                        <strong>{selectedProject.manifest.inputDir}</strong>
                                    </div>
                                    <div>
                                        <span className="summary-label">캐시</span>
                                        <strong>{selectedProject.manifest.cacheDir}</strong>
                                    </div>
                                    <div>
                                        <span className="summary-label">렌더 결과</span>
                                        <strong>{selectedProject.manifest.renderDir}</strong>
                                    </div>
                                    <div>
                                        <span className="summary-label">합성 목록 / 자막</span>
                                        <strong>{selectedProject.manifest.concatFilePath}</strong>
                                        <strong>{selectedProject.manifest.subtitleFilePath}</strong>
                                    </div>
                                </div>
                            ) : (
                                <div className="empty-history">초안을 만들면 파일 저장 위치가 여기 표시됩니다.</div>
                            )}
                        </div>
                    </>
                )}
            </div>
        </section>
    );
}

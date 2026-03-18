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
} from "./shared";

export interface DebugDrawerProps {
    bridgeHealth: BridgeHealth | null;
    bridgeStatus: BridgeStatus;
    bridgeMessage: string;
    selectedProject: StudioProjectRecord | null;
    copyState: CopyState;
    onCopyCommand: (target: CopyTarget, command: string) => void;
    onExportJson: (filename: string, payload: unknown) => void;
    onRefreshBridge: () => void;
    onClose: () => void;
}

export default function DebugDrawer(props: DebugDrawerProps) {
    const {
        bridgeHealth, bridgeStatus, bridgeMessage,
        selectedProject, copyState,
        onCopyCommand, onExportJson, onRefreshBridge, onClose,
    } = props;

    return (
        <div className="debug-overlay" onClick={onClose}>
            <div className="debug-drawer" onClick={(e) => e.stopPropagation()}>
                <div className="debug-drawer-header">
                    <h3>고급 설정 & 진단</h3>
                    <button className="debug-drawer-close" type="button" onClick={onClose}>✕</button>
                </div>

                <div className="debug-drawer-body">
                    {/* Bridge status */}
                    <section className="debug-section">
                        <div className="debug-section-title">브리지 상태</div>
                        <div className="debug-bridge-row">
                            <strong>{bridgeSummary(bridgeStatus, bridgeHealth)}</strong>
                            <button className="subtle-button" type="button" onClick={onRefreshBridge}>새로고침</button>
                        </div>
                        <p className="debug-message">{bridgeMessage}</p>
                    </section>

                    {/* Runtime readiness */}
                    <section className="debug-section">
                        <div className="debug-section-title">런타임 준비</div>
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
                    </section>

                    {/* Operator notes */}
                    <section className="debug-section">
                        <div className="debug-section-title">운영 메모</div>
                        {selectedProject?.planner ? (
                            <p className="debug-message">
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
                    </section>

                    {/* Command previews */}
                    <section className="debug-section">
                        <div className="debug-section-title">작업 명령</div>
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
                                        <span className="summary-label">최종 합성</span>
                                        <code className="command-preview">{buildComposeCommand(selectedProject)}</code>
                                        <button className="subtle-button" type="button" onClick={() => onCopyCommand("compose", buildComposeCommand(selectedProject))}>
                                            {copyLabel(copyState, "compose")}
                                        </button>
                                    </div>
                                </div>
                                <div className="button-row" style={{ marginTop: 8 }}>
                                    <button className="subtle-button" type="button" onClick={() => onExportJson(`${selectedProject.id}.json`, selectedProject)}>
                                        프로젝트 JSON
                                    </button>
                                    <button className="subtle-button" type="button" onClick={() => onExportJson(`${selectedProject.manifest.projectId}-render-manifest.json`, selectedProject.manifest)}>
                                        렌더 설계 파일
                                    </button>
                                </div>
                            </>
                        ) : (
                            <div className="empty-history">초안을 만들면 worker 인계 명령이 나타납니다.</div>
                        )}
                    </section>

                    {/* Storage paths */}
                    <section className="debug-section">
                        <div className="debug-section-title">저장 위치</div>
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
                            <div className="empty-history">초안을 만들면 파일 저장 위치가 표시됩니다.</div>
                        )}
                    </section>
                </div>
            </div>
        </div>
    );
}

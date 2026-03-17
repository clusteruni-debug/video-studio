import type { StudioProjectRecord } from "../lib/planner";
import type { BridgeStatus, CreationMode, GeneratedImage, ImageStatus, QueueItem, RenderState, SaveState } from "./shared";

export interface BottomBarProps {
    creationMode: CreationMode;
    selectedProject: StudioProjectRecord | null;
    bridgeStatus: BridgeStatus;
    saveState: SaveState;
    renderState: RenderState;
    imageStatus: ImageStatus;
    selectedImage: GeneratedImage | null;
    onSave: () => void;
    onRender: () => void;
    onRefreshBridge: () => void;
    onDownloadImage: (image: GeneratedImage) => void;
    batchQueue: QueueItem[];
    isBatchProcessing: boolean;
}

export default function BottomBar(props: BottomBarProps) {
    const {
        creationMode, selectedProject, bridgeStatus,
        saveState, renderState, imageStatus, selectedImage,
        onSave, onRender, onRefreshBridge, onDownloadImage,
        batchQueue, isBatchProcessing,
    } = props;

    if (creationMode === "image") {
        const batchTotal = batchQueue.length;
        const batchDone = batchQueue.filter((i) => i.status === "done").length;
        const batchStatusText = batchTotal > 0 && isBatchProcessing
            ? `배치: ${batchDone}/${batchTotal} 완료`
            : imageStatus.message;

        return (
            <footer className="bottom-bar">
                <div className="bottom-bar-actions">
                    <button
                        className="bottom-bar-btn"
                        type="button"
                        disabled={!selectedImage}
                        onClick={() => selectedImage && onDownloadImage(selectedImage)}
                    >
                        다운로드
                    </button>
                </div>
                <div className={`bottom-bar-status ${imageStatus.status === "error" ? "error" : imageStatus.status === "success" ? "success" : ""}`}>
                    {batchStatusText}
                </div>
                <div className="bottom-bar-indicator" />
            </footer>
        );
    }

    const statusMessage = renderState.message || saveState.message;
    const isSuccess = renderState.status === "rendered" || saveState.status === "saved";
    const isError = renderState.status === "failed" || saveState.status === "failed";

    return (
        <footer className="bottom-bar">
            <div className="bottom-bar-actions">
                <button
                    className="bottom-bar-btn"
                    type="button"
                    onClick={onSave}
                    disabled={!selectedProject || bridgeStatus !== "connected" || saveState.status === "saving"}
                >
                    {saveState.status === "saving" ? "저장 중..." : "저장"}
                </button>
                <button
                    className="bottom-bar-btn accent"
                    type="button"
                    onClick={onRender}
                    disabled={!selectedProject || bridgeStatus !== "connected" || renderState.status === "rendering"}
                >
                    {renderState.status === "rendering" ? "렌더 중..." : "렌더 시작"}
                </button>
            </div>
            <div className={`bottom-bar-status ${isSuccess ? "success" : isError ? "error" : ""}`}>
                {statusMessage}
            </div>
            <div className="bottom-bar-indicator">
                <span
                    className={`bridge-dot bridge-dot-${bridgeStatus}`}
                    title={bridgeStatus === "connected" ? "브리지 연결됨" : "브리지 오프라인"}
                    role="button"
                    tabIndex={0}
                    onClick={onRefreshBridge}
                    onKeyDown={(e) => e.key === "Enter" && onRefreshBridge()}
                />
            </div>
        </footer>
    );
}

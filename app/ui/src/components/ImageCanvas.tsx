import { formatDate, IMAGE_ENGINES, type GeneratedImage, type QueueItem } from "./shared";

export interface ImageCanvasProps {
    images: GeneratedImage[];
    selectedImageId: string | null;
    onSelectImage: (id: string | null) => void;
    onDownload: (image: GeneratedImage) => void;
    onDownloadAll: () => void;
    onUseInVideo: (image: GeneratedImage) => void;
    onRemoveImage: (id: string) => void;
    batchQueue: QueueItem[];
    isBatchProcessing: boolean;
    onRetryAllFailed: () => void;
    onStopBatch: () => void;
}

export default function ImageCanvas(props: ImageCanvasProps) {
    const {
        images, selectedImageId, onSelectImage, onDownload, onDownloadAll, onUseInVideo, onRemoveImage,
        batchQueue, isBatchProcessing, onRetryAllFailed, onStopBatch,
    } = props;

    const selectedImage = images.find((img) => img.id === selectedImageId) ?? null;

    const totalBatch = batchQueue.length;
    const doneBatch = batchQueue.filter((i) => i.status === "done").length;
    const failedBatch = batchQueue.filter((i) => i.status === "failed").length;
    const pendingBatch = batchQueue.filter((i) => i.status === "pending" || i.status === "generating").length;
    const batchPercent = totalBatch > 0 ? Math.round((doneBatch / totalBatch) * 100) : 0;

    if (images.length === 0 && totalBatch === 0) {
        return (
            <div className="main-canvas">
                <div className="canvas-empty">
                    <div className="canvas-empty-icon">🖼</div>
                    <h2>이미지 생성</h2>
                    <p>프롬프트를 입력하고 이미지를 생성하세요</p>
                </div>
            </div>
        );
    }

    return (
        <div className="main-canvas">
            <div className="image-canvas-header">
                <span className="canvas-header-title">생성된 이미지</span>
                <span className="canvas-header-meta">{images.length}장</span>
                {images.length > 1 && (
                    <button className="subtle-button" type="button" onClick={onDownloadAll}>
                        전체 다운로드
                    </button>
                )}
            </div>

            {totalBatch > 1 && (
                <div className="batch-progress">
                    <div className="batch-progress-stats">
                        <span>배치 진행: {doneBatch}/{totalBatch} 완료{failedBatch > 0 ? ` · ${failedBatch} 실패` : ""}{pendingBatch > 0 ? ` · ${pendingBatch} 대기` : ""}</span>
                    </div>
                    <div className="batch-progress-bar">
                        <div className="batch-progress-fill" style={{ width: `${batchPercent}%` }} />
                    </div>
                    <div className="batch-progress-actions">
                        {failedBatch > 0 && (
                            <button className="subtle-button" type="button" onClick={onRetryAllFailed}>
                                실패 재시도
                            </button>
                        )}
                        {isBatchProcessing && (
                            <button className="subtle-button" type="button" onClick={onStopBatch}>
                                중지
                            </button>
                        )}
                    </div>
                </div>
            )}

            <div className="image-gallery">
                {images.map((img) => (
                    <div
                        key={img.id}
                        className={`image-gallery-item ${img.id === selectedImageId ? "selected" : ""}`}
                    >
                        <button
                            className="image-gallery-select"
                            type="button"
                            onClick={() => onSelectImage(img.id === selectedImageId ? null : img.id)}
                        >
                            <img src={img.url} alt={img.prompt} />
                        </button>
                        <button
                            className="image-gallery-remove"
                            type="button"
                            title="삭제"
                            onClick={() => onRemoveImage(img.id)}
                        >
                            ×
                        </button>
                    </div>
                ))}
            </div>

            {selectedImage && (
                <div className="image-preview-panel">
                    <div className="image-preview-img-wrap">
                        <img src={selectedImage.url} alt={selectedImage.prompt} />
                    </div>
                    <div className="image-preview-info">
                        <p className="image-preview-prompt">{selectedImage.prompt}</p>
                        <span className="image-preview-meta">
                            {IMAGE_ENGINES.find((e) => e.key === selectedImage.engine)?.label ?? selectedImage.engine} · {selectedImage.width}×{selectedImage.height} · {formatDate(selectedImage.createdAt)}
                        </span>
                    </div>
                    <div className="image-preview-actions">
                        <button
                            className="bottom-bar-btn"
                            type="button"
                            onClick={() => onDownload(selectedImage)}
                        >
                            다운로드
                        </button>
                        <button
                            className="bottom-bar-btn accent"
                            type="button"
                            onClick={() => onUseInVideo(selectedImage)}
                        >
                            영상 장면에 사용 →
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}

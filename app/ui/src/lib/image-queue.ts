export type QueueItemStatus = "pending" | "generating" | "done" | "failed";

export interface QueueItem {
    id: string;
    prompt: string;
    originalPrompt: string;
    width: number;
    height: number;
    engine: string;
    emotion: string;
    status: QueueItemStatus;
    result?: { url: string; file: File };
    error?: string;
    filename?: string;
    metadata?: Record<string, string>;
    retryCount: number;
}

export interface QueueCallbacks {
    onItemUpdate: (items: QueueItem[]) => void;
    onImageCreated?: (item: QueueItem) => void;
    onComplete?: () => void;
    /** Bridge server image generation (required — Imagen 4 / Pexels / Klipy) */
    bridgeGenerateImage?: (input: { prompt: string; width: number; height: number; model: string; emotion: string }) => Promise<{ imageBase64: string; mimeType: string } | null>;
}

const BASE_DELAY_MS = 2_000;
const FETCH_TIMEOUT_MS = 120_000;

export class ImageGenerationQueue {
    private items: QueueItem[] = [];
    private processing = false;
    private abortController: AbortController | null = null;
    private callbacks: QueueCallbacks;

    constructor(callbacks: QueueCallbacks) {
        this.callbacks = callbacks;
    }

    enqueue(item: Omit<QueueItem, "status" | "retryCount">): void {
        this.items.push({ ...item, status: "pending", retryCount: 0 });
        this.notify();
    }

    start(): void {
        if (this.processing) return;
        this.processing = true;
        void this.processLoop();
    }

    stop(): void {
        this.processing = false;
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }
    }

    retry(id: string): void {
        const item = this.items.find((i) => i.id === id);
        if (item && item.status === "failed") {
            item.status = "pending";
            item.error = undefined;
            item.retryCount += 1;
            this.notify();
            if (!this.processing) this.start();
        }
    }

    retryAllFailed(): void {
        let changed = false;
        for (const item of this.items) {
            if (item.status === "failed") {
                item.status = "pending";
                item.error = undefined;
                item.retryCount += 1;
                changed = true;
            }
        }
        if (changed) {
            this.notify();
            if (!this.processing) this.start();
        }
    }

    clear(): void {
        this.stop();
        for (const item of this.items) {
            if (item.result?.url) URL.revokeObjectURL(item.result.url);
        }
        this.items = [];
        this.notify();
    }

    getItems(): QueueItem[] {
        return [...this.items];
    }

    isProcessing(): boolean {
        return this.processing;
    }

    private notify(): void {
        this.callbacks.onItemUpdate([...this.items]);
    }

    /** Attempt image generation via bridge server (Imagen 4 / Pexels / Klipy). */
    private async fetchWithRetry(
        item: QueueItem,
        signal: AbortSignal,
    ): Promise<{ blob: Blob; usedEngine: string }> {
        if (!this.callbacks.bridgeGenerateImage) {
            throw new Error("브리지 서버가 연결되지 않았습니다. npm run bridge 실행 후 재시도하세요.");
        }

        const MAX_RETRIES = 2;
        let lastError: Error | null = null;

        for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
            if (!this.processing || signal.aborted) throw new DOMException("Aborted", "AbortError");

            try {
                item.error = attempt === 0
                    ? "브리지 서버로 이미지 생성 중..."
                    : `재시도 ${attempt}/${MAX_RETRIES}...`;
                this.notify();

                const result = await this.callbacks.bridgeGenerateImage({
                    prompt: item.prompt,
                    width: item.width,
                    height: item.height,
                    model: item.engine,
                    emotion: item.emotion,
                });

                if (result) {
                    const raw = atob(result.imageBase64);
                    const binary = new Uint8Array(raw.length);
                    for (let i = 0; i < raw.length; i++) binary[i] = raw.charCodeAt(i);
                    const blob = new Blob([binary], { type: result.mimeType });
                    return { blob, usedEngine: item.engine };
                }

                lastError = new Error("브리지 서버에서 이미지를 생성하지 못했습니다");
            } catch (err) {
                if (err instanceof DOMException && (err.name === "AbortError" || err.name === "TimeoutError")) throw err;
                lastError = err instanceof Error ? err : new Error("브리지 생성 실패");
            }

            if (attempt < MAX_RETRIES) {
                const backoffMs = BASE_DELAY_MS * Math.pow(2, attempt);
                item.error = `${Math.round(backoffMs / 1000)}초 후 재시도...`;
                this.notify();
                await this.sleep(backoffMs);
            }
        }

        throw lastError ?? new Error("브리지 서버에서 이미지 생성 실패. 서버 로그를 확인하세요.");
    }

    /** Interruptible sleep — resolves early if processing is stopped */
    private sleep(ms: number): Promise<void> {
        return new Promise((resolve) => {
            const id = setTimeout(resolve, ms);
            const check = setInterval(() => {
                if (!this.processing) {
                    clearTimeout(id);
                    clearInterval(check);
                    resolve();
                }
            }, 500);
            // Clean up interval when timer fires naturally
            setTimeout(() => clearInterval(check), ms + 100);
        });
    }

    private async processLoop(): Promise<void> {
        while (this.processing) {
            const next = this.items.find((i) => i.status === "pending");
            if (!next) {
                this.processing = false;
                this.callbacks.onComplete?.();
                this.notify();
                return;
            }

            next.status = "generating";
            next.error = undefined;
            this.notify();

            try {
                this.abortController = new AbortController();
                const timeoutSignal = AbortSignal.timeout(FETCH_TIMEOUT_MS);
                const signal = AbortSignal.any([this.abortController.signal, timeoutSignal]);

                const { blob, usedEngine } = await this.fetchWithRetry(next, signal);

                const mimeType = blob.type || "image/png";
                const ext = mimeType.includes("jpeg") || mimeType.includes("jpg")
                    ? "jpg"
                    : mimeType.includes("webp") ? "webp" : "png";
                const baseName = (next.filename?.trim()) || `batch-${next.id}`;
                const file = new File([blob], `${baseName}.${ext}`, { type: mimeType });
                const url = URL.createObjectURL(blob);

                next.status = "done";
                next.engine = usedEngine;
                next.result = { url, file };
                next.error = undefined;
                this.notify();
                this.callbacks.onImageCreated?.(next);
            } catch (error) {
                if (error instanceof DOMException && error.name === "AbortError" && !this.processing) {
                    next.status = "pending";
                    next.error = undefined;
                    this.notify();
                    return;
                }
                next.status = "failed";
                next.error = error instanceof DOMException && error.name === "TimeoutError"
                    ? "타임아웃 (120초)"
                    : error instanceof Error ? error.message : "생성 실패";
                this.notify();
            } finally {
                this.abortController = null;
            }

            if (this.processing) {
                await this.sleep(BASE_DELAY_MS);
            }
        }
    }
}

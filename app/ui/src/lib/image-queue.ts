export type QueueItemStatus = "pending" | "generating" | "done" | "failed";

export interface QueueItem {
    id: string;
    prompt: string;
    originalPrompt: string;
    width: number;
    height: number;
    engine: string;
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
}

const DELAY_MS = 2000;
const FETCH_TIMEOUT_MS = 90_000;

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
            this.notify();

            try {
                this.abortController = new AbortController();
                const encoded = encodeURIComponent(next.prompt);
                const apiUrl = `https://image.pollinations.ai/prompt/${encoded}?width=${next.width}&height=${next.height}&model=${next.engine}&nologo=true&seed=${Date.now()}`;
                const timeoutSignal = AbortSignal.timeout(FETCH_TIMEOUT_MS);
                const signal = AbortSignal.any([this.abortController.signal, timeoutSignal]);

                const response = await fetch(apiUrl, { signal });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);

                const blob = await response.blob();
                const mimeType = blob.type || "image/png";
                const ext = mimeType.includes("jpeg") || mimeType.includes("jpg")
                    ? "jpg"
                    : mimeType.includes("webp") ? "webp" : "png";
                const baseName = (next.filename?.trim()) || `batch-${next.id}`;
                const file = new File([blob], `${baseName}.${ext}`, { type: mimeType });
                const url = URL.createObjectURL(blob);

                next.status = "done";
                next.result = { url, file };
                this.notify();
                this.callbacks.onImageCreated?.(next);
            } catch (error) {
                if (error instanceof DOMException && error.name === "AbortError" && !this.processing) {
                    next.status = "pending";
                    this.notify();
                    return;
                }
                next.status = "failed";
                next.error = error instanceof DOMException && error.name === "TimeoutError"
                    ? "타임아웃 (90초)"
                    : error instanceof Error ? error.message : "생성 실패";
                this.notify();
            } finally {
                this.abortController = null;
            }

            if (this.processing) {
                await new Promise((r) => setTimeout(r, DELAY_MS));
            }
        }
    }
}

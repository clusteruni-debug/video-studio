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
    /** If provided, attempts bridge proxy when direct API fails */
    bridgeGenerateImage?: (input: { prompt: string; width: number; height: number; model: string }) => Promise<{ imageBase64: string; mimeType: string } | null>;
}

/** Base delay between requests — anonymous tier allows ~1 req at a time */
const BASE_DELAY_MS = 8_000;
const FETCH_TIMEOUT_MS = 120_000;
const MAX_AUTO_RETRIES = 3;
/** Models to try in order when the current one fails with 500 */
const MODEL_FALLBACK_CHAIN = ["sana", "zimage"];

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

    /** Attempt fetch with retry for 429/500 and model fallback */
    private async fetchWithRetry(
        item: QueueItem,
        signal: AbortSignal,
    ): Promise<{ blob: Blob; usedEngine: string }> {
        const modelsToTry = MODEL_FALLBACK_CHAIN.includes(item.engine)
            ? [item.engine, ...MODEL_FALLBACK_CHAIN.filter((m) => m !== item.engine)]
            : [item.engine, ...MODEL_FALLBACK_CHAIN];

        let lastError: Error | null = null;

        for (const model of modelsToTry) {
            for (let attempt = 0; attempt < MAX_AUTO_RETRIES; attempt++) {
                if (!this.processing) throw new DOMException("Aborted", "AbortError");

                const encoded = encodeURIComponent(item.prompt);
                const apiUrl = `https://image.pollinations.ai/prompt/${encoded}?width=${item.width}&height=${item.height}&model=${model}&nologo=true&seed=${Date.now()}`;

                try {
                    const response = await fetch(apiUrl, { signal });

                    if (response.ok) {
                        const blob = await response.blob();
                        if (blob.size < 1000) {
                            // Pollinations sometimes returns tiny error responses as 200
                            const text = await blob.text();
                            if (text.includes('"error"')) {
                                throw new Error(`서버 오류 응답 (${model})`);
                            }
                        }
                        return { blob, usedEngine: model };
                    }

                    if (response.status === 429) {
                        // Rate limited — wait with exponential backoff then retry same model
                        const backoffMs = BASE_DELAY_MS * Math.pow(2, attempt);
                        item.error = `대기 중... (${Math.round(backoffMs / 1000)}초 후 재시도)`;
                        this.notify();
                        await this.sleep(backoffMs);
                        continue;
                    }

                    if (response.status === 500) {
                        // Server error — try to parse and check if model is unavailable
                        let body: { message?: string } = {};
                        try { body = await response.json(); } catch { /* ignore */ }
                        const msg = body.message ?? "";
                        if (msg.includes("No active") || msg.includes("servers available")) {
                            // Model is down — break inner loop, try next model
                            lastError = new Error(`${model} 서버 없음`);
                            break;
                        }
                        // Other 500 — retry with backoff
                        const backoffMs = BASE_DELAY_MS * Math.pow(2, attempt);
                        item.error = `서버 오류, ${Math.round(backoffMs / 1000)}초 후 재시도...`;
                        this.notify();
                        await this.sleep(backoffMs);
                        continue;
                    }

                    // Other HTTP errors — fail immediately
                    throw new Error(`HTTP ${response.status}`);
                } catch (error) {
                    if (error instanceof DOMException && (error.name === "AbortError" || error.name === "TimeoutError")) {
                        throw error;
                    }
                    lastError = error instanceof Error ? error : new Error("네트워크 오류");
                    // Network error — backoff and retry
                    if (attempt < MAX_AUTO_RETRIES - 1) {
                        const backoffMs = BASE_DELAY_MS * Math.pow(2, attempt);
                        item.error = `네트워크 오류, ${Math.round(backoffMs / 1000)}초 후 재시도...`;
                        this.notify();
                        await this.sleep(backoffMs);
                    }
                }
            }
        }

        // All direct API attempts failed — try bridge proxy as last resort
        if (this.callbacks.bridgeGenerateImage) {
            if (!this.processing) throw new DOMException("Aborted", "AbortError");
            try {
                item.error = "직접 API 실패, 브리지 프록시 시도 중...";
                this.notify();
                const result = await this.callbacks.bridgeGenerateImage({
                    prompt: item.prompt,
                    width: item.width,
                    height: item.height,
                    model: item.engine,
                });
                if (result) {
                    const binary = new Uint8Array(result.imageBase64.length);
                    const raw = atob(result.imageBase64);
                    for (let i = 0; i < raw.length; i++) binary[i] = raw.charCodeAt(i);
                    const blob = new Blob([binary], { type: result.mimeType });
                    return { blob, usedEngine: item.engine };
                }
            } catch (err) {
                if (err instanceof DOMException && err.name === "AbortError") throw err;
                // bridge also failed — fall through to error
            }
        }

        throw lastError ?? new Error("모든 모델에서 생성 실패");
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

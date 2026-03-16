import { rehydrateStudioProjectRecord, type StudioProjectRecord } from "./planner";

const STORAGE_KEY = "video-studio-app/projects";

export function loadStoredProjects(): StudioProjectRecord[] {
    if (typeof window === "undefined") {
        return [];
    }

    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
        return [];
    }

    try {
        const parsed = JSON.parse(raw) as StudioProjectRecord[];
        return Array.isArray(parsed) ? parsed.map((record) => rehydrateStudioProjectRecord(record)) : [];
    } catch {
        return [];
    }
}

export function saveStoredProjects(records: StudioProjectRecord[]): void {
    if (typeof window === "undefined") {
        return;
    }

    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
}

import type { AspectRatio, ProjectPlan, RouteHint } from "./plan";

export type RenderAssetRole = "visual" | "audio" | "subtitle";
export type VisualKind = "image" | "video";
export type AudioKind = "voiceover" | "native" | "none";
export type AssetSourceOrigin = "generated" | "uploaded";
export type MotionPreset = "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "drift_up" | "drift_down" | "random" | "none";
export type TransitionType = "fade" | "dissolve" | "wipeleft" | "none";

export interface RenderAssetSpec {
    id: string;
    sceneId: string;
    role: RenderAssetRole;
    provider: string;
    kind: string;
    prompt: string;
    durationSec: number;
    outputPath: string;
    sourceOrigin?: AssetSourceOrigin;
    sourcePath?: string;
    sourceLabel?: string;
    sourceMimeType?: string;
}

export interface RenderSceneSpec {
    sceneId: string;
    title: string;
    startSec: number;
    endSec: number;
    durationSec: number;
    route: RouteHint;
    visualKind: VisualKind;
    audioKind: AudioKind;
    subtitleText: string;
    cacheDir: string;
    assetIds: string[];
    motionPreset: MotionPreset;
}

export interface RenderManifest {
    version: 1;
    projectId: string;
    title: string;
    aspectRatio: AspectRatio;
    storageRoot: string;
    inputDir: string;
    cacheDir: string;
    renderDir: string;
    concatFilePath: string;
    subtitleFilePath: string;
    outputPath: string;
    totalDurationSec: number;
    estimatedCostUsd: number;
    transitionType: TransitionType;
    transitionDuration: number;
    scenes: RenderSceneSpec[];
    assets: RenderAssetSpec[];
    composeCommandPreview: string;
}

function slugify(value: string): string {
    return value
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 48) || "video-project";
}

function visualKindForScene(canUseStillImage: boolean, route: RouteHint): VisualKind {
    if (route === "local" && canUseStillImage) {
        return "image";
    }

    return "video";
}

function audioKindForScene(route: RouteHint): AudioKind {
    if (route === "veo3") {
        return "native";
    }

    return "voiceover";
}

export function buildRenderManifest(input: {
    projectId: string;
    plan: ProjectPlan;
    routes: Array<{ sceneId: string; route: RouteHint }>;
    estimatedCostUsd: number;
    storageRoot?: string;
}): RenderManifest {
    const storageRoot = input.storageRoot ?? "storage";
    const projectSlug = slugify(input.plan.title);
    const inputDir = `${storageRoot}/inputs/${input.projectId}`;
    const cacheDir = `${storageRoot}/cache/${input.projectId}`;
    const renderDir = `${storageRoot}/renders/${input.projectId}`;
    const concatFilePath = `${renderDir}/concat.txt`;
    const subtitleFilePath = `${renderDir}/captions.srt`;
    const outputPath = `${renderDir}/${projectSlug}.mp4`;

    let cursor = 0;
    const assets: RenderAssetSpec[] = [];
    const scenes: RenderSceneSpec[] = input.plan.scenes.map((scene) => {
        const route = input.routes.find((item) => item.sceneId === scene.id)?.route ?? "local";
        const sceneCacheDir = `${cacheDir}/${scene.id}`;
        const visualKind = visualKindForScene(scene.canUseStillImage, route);
        const audioKind = audioKindForScene(route);
        const assetIds: string[] = [];

        const visualAssetId = `${scene.id}-visual`;
        assets.push({
            id: visualAssetId,
            sceneId: scene.id,
            role: "visual",
            provider: route,
            kind: visualKind,
            prompt: scene.prompt,
            durationSec: scene.durationSec,
            outputPath: `${sceneCacheDir}/${scene.id}.${visualKind === "image" ? "png" : "mp4"}`,
        });
        assetIds.push(visualAssetId);

        const audioAssetId = `${scene.id}-audio`;
        assets.push({
            id: audioAssetId,
            sceneId: scene.id,
            role: "audio",
            provider: audioKind === "native" ? route : "piper",
            kind: audioKind,
            prompt: scene.subtitleText,
            durationSec: scene.durationSec,
            outputPath: `${sceneCacheDir}/${scene.id}.${audioKind === "native" ? "wav" : "wav"}`,
        });
        assetIds.push(audioAssetId);

        const subtitleAssetId = `${scene.id}-subtitle`;
        assets.push({
            id: subtitleAssetId,
            sceneId: scene.id,
            role: "subtitle",
            provider: "local",
            kind: "srt-line",
            prompt: scene.subtitleText,
            durationSec: scene.durationSec,
            outputPath: `${sceneCacheDir}/${scene.id}.srt`,
        });
        assetIds.push(subtitleAssetId);

        const startSec = Number(cursor.toFixed(2));
        cursor += scene.durationSec;
        const endSec = Number(cursor.toFixed(2));

        return {
            sceneId: scene.id,
            title: scene.title,
            startSec,
            endSec,
            durationSec: Number(scene.durationSec.toFixed(2)),
            route,
            visualKind,
            audioKind,
            subtitleText: scene.subtitleText,
            cacheDir: sceneCacheDir,
            assetIds,
            motionPreset: visualKind === "image" ? "random" : "none",
        };
    });

    const composeCommandPreview =
        `ffmpeg -y -f concat -safe 0 -i "${concatFilePath}" ` +
        `-vf "subtitles=${subtitleFilePath},scale=1080:1920" -c:v libx264 -c:a aac "${outputPath}"`;

    return {
        version: 1,
        projectId: input.projectId,
        title: input.plan.title,
        aspectRatio: input.plan.aspectRatio,
        storageRoot,
        inputDir,
        cacheDir,
        renderDir,
        concatFilePath,
        subtitleFilePath,
        outputPath,
        totalDurationSec: Number(cursor.toFixed(2)),
        estimatedCostUsd: Number(input.estimatedCostUsd.toFixed(2)),
        transitionType: "fade",
        transitionDuration: 0.5,
        scenes,
        assets,
        composeCommandPreview,
    };
}

import { startTransition, useEffect, useMemo, useState } from "react";
import type { BudgetMode } from "../../../shared/contracts/plan";
import {
    fetchBridgeHealth,
    renderSmokeWithBridge,
    routePlanWithBridge,
    saveProjectWithBridge,
    type BridgeHealth,
    type BridgeToolStatus,
} from "./lib/bridge";
import { operatorSteps, samplePrompts } from "./lib/sample-data";
import {
    buildComposeCommand,
    buildSavePlanCommand,
    buildStudioProjectRecord,
    buildStudioProjectRecordFromWorker,
    buildWorkerCommand,
    type ProviderAvailability,
    type RouteDecision,
    type StudioProjectRecord,
} from "./lib/planner";
import { loadStoredProjects, saveStoredProjects } from "./lib/storage";

type CopyTarget = "route" | "save" | "compose";
type CopyState = { target: CopyTarget | null; state: "idle" | "copied" | "failed" };
type BridgeStatus = "checking" | "connected" | "offline" | "error";
type SaveState = { status: "idle" | "saving" | "saved" | "failed"; message: string };
type RenderState = { status: "idle" | "rendering" | "rendered" | "failed"; message: string };

function formatDate(value: string): string {
    return new Intl.DateTimeFormat("en", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
    }).format(new Date(value));
}

function routeLabel(route: RouteDecision["route"]): string {
    if (route === "sora2") return "Sora 2";
    if (route === "veo3") return "Veo 3";
    return "Local";
}

function copyLabel(copyState: CopyState, target: CopyTarget): string {
    if (copyState.target !== target) return "Copy";
    if (copyState.state === "copied") return "Copied";
    if (copyState.state === "failed") return "Copy failed";
    return "Copy";
}

function bridgeSummary(status: BridgeStatus, health: BridgeHealth | null): string {
    if (status === "checking") return "Checking local bridge";
    if (status === "connected" && health) return `Connected on ${health.port}`;
    if (status === "error") return "Bridge error, browser fallback";
    return "Bridge offline";
}

function toolSummary(tool: BridgeToolStatus | null | undefined): string {
    if (!tool) return "not checked";
    if (tool.ready) {
        const source = tool.source ? `via ${tool.source}` : "ready";
        return `${tool.version ?? "ready"} (${source})`;
    }

    return tool.detail ?? tool.path ?? "not available";
}

function toolPath(tool: BridgeToolStatus | null | undefined): string {
    return tool?.resolvedPath ?? tool?.path ?? "not detected";
}

function providerAvailabilityFromRecord(record: StudioProjectRecord): ProviderAvailability {
    return {
        premiumEnabled: record.routes.some((route) => route.route !== "local"),
        sora2: record.routes.some((route) => route.route === "sora2"),
        veo3: record.routes.some((route) => route.route === "veo3"),
    };
}

export default function App() {
    const [prompt, setPrompt] = useState(samplePrompts[0]);
    const [budgetMode, setBudgetMode] = useState<BudgetMode>("standard");
    const [monthlyCapUsd, setMonthlyCapUsd] = useState(30);
    const [availability, setAvailability] = useState<ProviderAvailability>({
        premiumEnabled: true,
        sora2: true,
        veo3: false,
    });
    const [preferBridge, setPreferBridge] = useState(true);
    const [projects, setProjects] = useState<StudioProjectRecord[]>([]);
    const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
    const [copyState, setCopyState] = useState<CopyState>({ target: null, state: "idle" });
    const [bridgeStatus, setBridgeStatus] = useState<BridgeStatus>("checking");
    const [bridgeHealth, setBridgeHealth] = useState<BridgeHealth | null>(null);
    const [bridgeMessage, setBridgeMessage] = useState("Checking local bridge");
    const [isGenerating, setIsGenerating] = useState(false);
    const [saveState, setSaveState] = useState<SaveState>({ status: "idle", message: "" });
    const [renderState, setRenderState] = useState<RenderState>({ status: "idle", message: "" });

    useEffect(() => {
        const stored = loadStoredProjects();
        setProjects(stored);
        setSelectedProjectId(stored[0]?.id ?? null);
    }, []);

    useEffect(() => {
        saveStoredProjects(projects);
    }, [projects]);

    useEffect(() => {
        void refreshBridgeHealth();
    }, []);

    const selectedProject = useMemo(
        () => projects.find((project) => project.id === selectedProjectId) ?? null,
        [projects, selectedProjectId],
    );

    const premiumSceneCount = useMemo(
        () => selectedProject?.routes.filter((route) => route.route !== "local").length ?? 0,
        [selectedProject],
    );

    async function refreshBridgeHealth(): Promise<void> {
        setBridgeStatus("checking");
        setBridgeMessage("Checking local bridge");
        try {
            const health = await fetchBridgeHealth();
            setBridgeHealth(health);
            setBridgeStatus("connected");
            setBridgeMessage(`Bridge connected on ${health.port}`);
        } catch (error) {
            setBridgeHealth(null);
            setBridgeStatus("offline");
            setBridgeMessage(error instanceof Error ? error.message : "Bridge offline");
        }
    }

    async function generateProject(): Promise<void> {
        const normalized = prompt.trim();
        if (!normalized || isGenerating) return;

        setIsGenerating(true);
        setSaveState({ status: "idle", message: "" });
        setRenderState({ status: "idle", message: "" });

        try {
            let nextRecord: StudioProjectRecord;

            if (preferBridge && bridgeStatus === "connected") {
                try {
                    const payload = await routePlanWithBridge({
                        prompt: normalized,
                        budgetMode,
                        availability,
                    });
                    nextRecord = buildStudioProjectRecordFromWorker({
                        projectId: `project-${Date.now()}`,
                        plan: payload.plan,
                        routes: payload.routes,
                        estimatedCostUsd: payload.estimatedTotalCostUsd,
                    });
                    setBridgeMessage("Storyboard drafted through the bridge");
                } catch (error) {
                    setBridgeStatus("error");
                    setBridgeMessage(
                        error instanceof Error
                            ? `${error.message} — browser planner fallback`
                            : "Bridge failed — browser planner fallback",
                    );
                    nextRecord = buildStudioProjectRecord({
                        prompt: normalized,
                        budgetMode,
                        monthlyCapUsd,
                        availability,
                    });
                }
            } else {
                nextRecord = buildStudioProjectRecord({
                    prompt: normalized,
                    budgetMode,
                    monthlyCapUsd,
                    availability,
                });
            }

            startTransition(() => {
                setProjects((current) => [nextRecord, ...current].slice(0, 8));
                setSelectedProjectId(nextRecord.id);
                setCopyState({ target: null, state: "idle" });
            });
        } finally {
            setIsGenerating(false);
        }
    }

    function removeProject(projectId: string): void {
        const nextProjects = projects.filter((project) => project.id !== projectId);
        startTransition(() => {
            setProjects(nextProjects);
            setSelectedProjectId((current) => (current === projectId ? nextProjects[0]?.id ?? null : current));
            setCopyState({ target: null, state: "idle" });
            setSaveState({ status: "idle", message: "" });
            setRenderState({ status: "idle", message: "" });
        });
    }

    async function copyCommand(target: CopyTarget, command: string): Promise<void> {
        try {
            await navigator.clipboard.writeText(command);
            setCopyState({ target, state: "copied" });
        } catch {
            setCopyState({ target, state: "failed" });
        }
    }

    async function exportJson(filename: string, payload: unknown): Promise<void> {
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        anchor.click();
        URL.revokeObjectURL(url);
    }

    async function saveProjectThroughBridge(): Promise<void> {
        if (!selectedProject || bridgeStatus !== "connected") return;

        setSaveState({ status: "saving", message: "Saving project files through the bridge" });
        try {
            const response = await saveProjectWithBridge({
                prompt: selectedProject.plan.sourcePrompt,
                budgetMode: selectedProject.plan.budgetMode,
                projectId: selectedProject.id,
                availability: providerAvailabilityFromRecord(selectedProject),
            });
            setSaveState({
                status: "saved",
                message: `Saved into ${response.saveResult.inputDir}`,
            });
            setBridgeMessage(`Bridge saved ${response.saveResult.projectId}`);
        } catch (error) {
            setSaveState({
                status: "failed",
                message: error instanceof Error ? error.message : "Bridge save failed",
            });
        }
    }

    async function renderProjectThroughBridge(): Promise<void> {
        if (!selectedProject || bridgeStatus !== "connected") return;

        setRenderState({ status: "rendering", message: "Running FFmpeg smoke render through the bridge" });
        try {
            const response = await renderSmokeWithBridge({
                prompt: selectedProject.plan.sourcePrompt,
                budgetMode: selectedProject.plan.budgetMode,
                projectId: selectedProject.id,
                availability: providerAvailabilityFromRecord(selectedProject),
            });
            setRenderState({
                status: "rendered",
                message: `Rendered ${response.renderResult.outputPath}`,
            });
            setBridgeMessage(`Smoke render complete for ${response.renderResult.projectId}`);
        } catch (error) {
            setRenderState({
                status: "failed",
                message: error instanceof Error ? error.message : "Bridge render failed",
            });
        }
    }

    return (
        <div className="studio-shell">
            <div className="studio-glow studio-glow-left" />
            <div className="studio-glow studio-glow-right" />

            <header className="hero">
                <div className="hero-kicker">Video Studio / Local + Premium Routing</div>
                <div className="hero-grid">
                    <div>
                        <h1>Shape the storyboard before you burn GPU time.</h1>
                        <p className="hero-copy">
                            This runtime can now plan through a local bridge, map scenes into storage,
                            and save worker-ready project files without leaving the app.
                        </p>
                    </div>
                    <div className="hero-signal">
                        <div className="signal-card">
                            <span className="signal-label">Bridge lane</span>
                            <strong>{bridgeSummary(bridgeStatus, bridgeHealth)}</strong>
                        </div>
                        <div className="signal-card">
                            <span className="signal-label">Premium scenes</span>
                            <strong>{premiumSceneCount}</strong>
                        </div>
                        <div className="signal-card">
                            <span className="signal-label">Timeline length</span>
                            <strong>{selectedProject?.manifest.totalDurationSec.toFixed(1) ?? "0.0"}s</strong>
                        </div>
                    </div>
                </div>
            </header>

            <main className="workspace">
                <section className="panel composer-panel">
                    <div className="panel-header">
                        <span className="panel-index">01</span>
                        <div>
                            <h2>Prompt Composer</h2>
                            <p>Draft in-browser, or let the local bridge call the Python worker directly.</p>
                        </div>
                    </div>

                    <label className="field">
                        <span>Prompt</span>
                        <textarea
                            value={prompt}
                            onChange={(event) => setPrompt(event.target.value)}
                            rows={7}
                            placeholder="Describe the short-form video you want to create"
                        />
                    </label>

                    <div className="chip-row">
                        {samplePrompts.map((item) => (
                            <button key={item} className="chip" type="button" onClick={() => setPrompt(item)}>
                                {item}
                            </button>
                        ))}
                    </div>

                    <div className="control-grid">
                        <label className="field compact">
                            <span>Budget mode</span>
                            <select value={budgetMode} onChange={(event) => setBudgetMode(event.target.value as BudgetMode)}>
                                <option value="free">Free</option>
                                <option value="standard">Standard</option>
                                <option value="premium">Premium</option>
                            </select>
                        </label>

                        <label className="field compact">
                            <span>Monthly cap (USD)</span>
                            <input
                                type="number"
                                min={0}
                                step={5}
                                value={monthlyCapUsd}
                                onChange={(event) => setMonthlyCapUsd(Number(event.target.value))}
                            />
                        </label>
                    </div>

                    <div className="toggle-grid">
                        <label className="toggle">
                            <input type="checkbox" checked={preferBridge} onChange={(event) => setPreferBridge(event.target.checked)} />
                            <span>Use local bridge when reachable</span>
                        </label>
                        <label className="toggle">
                            <input
                                type="checkbox"
                                checked={availability.premiumEnabled}
                                onChange={(event) => setAvailability((current) => ({ ...current, premiumEnabled: event.target.checked }))}
                            />
                            <span>Premium routing enabled</span>
                        </label>
                        <label className="toggle">
                            <input
                                type="checkbox"
                                checked={availability.sora2}
                                onChange={(event) => setAvailability((current) => ({ ...current, sora2: event.target.checked }))}
                            />
                            <span>Sora 2 available</span>
                        </label>
                        <label className="toggle">
                            <input
                                type="checkbox"
                                checked={availability.veo3}
                                onChange={(event) => setAvailability((current) => ({ ...current, veo3: event.target.checked }))}
                            />
                            <span>Veo 3 available</span>
                        </label>
                    </div>

                    <div className="bridge-banner">
                        <div>
                            <span className="summary-label">Bridge status</span>
                            <strong>{bridgeSummary(bridgeStatus, bridgeHealth)}</strong>
                        </div>
                        <button className="subtle-button" type="button" onClick={() => void refreshBridgeHealth()}>
                            Refresh bridge
                        </button>
                    </div>

                    <p className="bridge-message">{bridgeMessage}</p>

                    <button className="action-button" type="button" onClick={() => void generateProject()}>
                        {isGenerating ? "Generating..." : "Generate storyboard draft"}
                    </button>
                </section>

                <section className="panel storyboard-panel">
                    <div className="panel-header">
                        <span className="panel-index">02</span>
                        <div>
                            <h2>Storyboard Preview</h2>
                            <p>Review the routed scene plan before you touch FLUX, Wan, Sora 2, or Veo 3.</p>
                        </div>
                    </div>

                    {selectedProject ? (
                        <>
                            <div className="summary-strip">
                                <div><span className="summary-label">Aspect</span><strong>{selectedProject.plan.aspectRatio}</strong></div>
                                <div><span className="summary-label">Budget mode</span><strong>{selectedProject.plan.budgetMode}</strong></div>
                                <div><span className="summary-label">Est. premium cost</span><strong>${selectedProject.estimatedCostUsd.toFixed(2)}</strong></div>
                                <div><span className="summary-label">Render output</span><strong>{selectedProject.manifest.outputPath}</strong></div>
                            </div>

                            <div className="scene-list">
                                {selectedProject.plan.scenes.map((scene) => {
                                    const route = selectedProject.routes.find((item) => item.sceneId === scene.id);
                                    const manifestScene = selectedProject.manifest.scenes.find((item) => item.sceneId === scene.id);

                                    return (
                                        <article key={scene.id} className="scene-card">
                                            <div className="scene-meta">
                                                <span className={`route-badge route-${route?.route ?? "local"}`}>{routeLabel(route?.route ?? "local")}</span>
                                                <span>{scene.durationSec.toFixed(1)}s</span>
                                            </div>
                                            <h3>{scene.title}</h3>
                                            <p>{scene.prompt}</p>
                                            <div className="scene-scores">
                                                <span>Priority {scene.priority}</span>
                                                <span>Realism {scene.humanRealism}</span>
                                                <span>Audio {scene.nativeAudioNeed}</span>
                                            </div>
                                            <div className="scene-pipeline">
                                                <span>{manifestScene?.visualKind ?? "video"} visual</span>
                                                <span>{manifestScene?.audioKind ?? "voiceover"} audio</span>
                                                <span>{manifestScene?.cacheDir ?? "storage/cache"}</span>
                                            </div>
                                            <div className="scene-footer">
                                                <strong>{scene.subtitleText}</strong>
                                                <small>{route?.reason}</small>
                                            </div>
                                        </article>
                                    );
                                })}
                            </div>
                        </>
                    ) : (
                        <div className="empty-panel">
                            <p>No storyboard yet. Generate a draft to preview route decisions and per-scene cost.</p>
                        </div>
                    )}
                </section>

                <section className="panel diagnostics-panel">
                    <div className="panel-header">
                        <span className="panel-index">03</span>
                        <div>
                            <h2>Control Room</h2>
                            <p>Bridge health, tool visibility, storage actions, and draft history live here.</p>
                        </div>
                    </div>

                    <div className="diag-block">
                        <div className="diag-title">Shell readiness</div>
                        <ul className="status-list">
                            <li><span className={`status-dot ${bridgeStatus === "connected" ? "status-ok" : "status-warn"}`} />Local bridge: {bridgeSummary(bridgeStatus, bridgeHealth)}</li>
                            <li><span className={`status-dot ${bridgeHealth?.tools.ffmpeg?.ready ? "status-ok" : "status-warn"}`} />FFmpeg: {toolSummary(bridgeHealth?.tools.ffmpeg)}<br />{toolPath(bridgeHealth?.tools.ffmpeg)}</li>
                            <li><span className={`status-dot ${bridgeHealth?.tools.ollama?.ready ? "status-ok" : "status-warn"}`} />Ollama: {toolSummary(bridgeHealth?.tools.ollama)}<br />{toolPath(bridgeHealth?.tools.ollama)}</li>
                            <li><span className={`status-dot ${bridgeHealth?.tools.hf?.ready ? "status-ok" : "status-warn"}`} />Hugging Face CLI: {toolSummary(bridgeHealth?.tools.hf)}<br />{toolPath(bridgeHealth?.tools.hf)}</li>
                        </ul>
                    </div>

                    <div className="diag-block">
                        <div className="diag-title">Operator notes</div>
                        <ul className="operator-list">
                            {operatorSteps.map((step) => (
                                <li key={step}>{step}</li>
                            ))}
                        </ul>
                    </div>

                    <div className="diag-block">
                        <div className="diag-title">Bridge actions</div>
                        {selectedProject ? (
                            <>
                                <div className="button-row">
                                    <button className="subtle-button" type="button" onClick={() => void saveProjectThroughBridge()} disabled={bridgeStatus !== "connected" || saveState.status === "saving"}>
                                        {saveState.status === "saving" ? "Saving..." : "Save to storage now"}
                                    </button>
                                    <button className="subtle-button" type="button" onClick={() => void renderProjectThroughBridge()} disabled={bridgeStatus !== "connected" || renderState.status === "rendering"}>
                                        {renderState.status === "rendering" ? "Rendering..." : "Run FFmpeg smoke render"}
                                    </button>
                                    <button className="subtle-button" type="button" onClick={() => void refreshBridgeHealth()}>
                                        Refresh bridge
                                    </button>
                                </div>
                                {saveState.message ? <p className={`bridge-message bridge-${saveState.status}`}>{saveState.message}</p> : null}
                                {renderState.message ? (
                                    <p className={`bridge-message ${renderState.status === "rendered" ? "bridge-saved" : renderState.status === "failed" ? "bridge-failed" : ""}`}>
                                        {renderState.message}
                                    </p>
                                ) : null}
                            </>
                        ) : (
                            <div className="empty-history">Generate a draft first to unlock bridge save actions.</div>
                        )}
                    </div>

                    <div className="diag-block">
                        <div className="diag-title">Worker handoff</div>
                        {selectedProject ? (
                            <>
                                <div className="command-stack">
                                    <div className="command-card">
                                        <span className="summary-label">Route preview</span>
                                        <code className="command-preview">{buildWorkerCommand(selectedProject)}</code>
                                        <button className="subtle-button" type="button" onClick={() => void copyCommand("route", buildWorkerCommand(selectedProject))}>{copyLabel(copyState, "route")}</button>
                                    </div>
                                    <div className="command-card">
                                        <span className="summary-label">Save project files</span>
                                        <code className="command-preview">{buildSavePlanCommand(selectedProject)}</code>
                                        <button className="subtle-button" type="button" onClick={() => void copyCommand("save", buildSavePlanCommand(selectedProject))}>{copyLabel(copyState, "save")}</button>
                                    </div>
                                    <div className="command-card">
                                        <span className="summary-label">Compose preview</span>
                                        <code className="command-preview">{buildComposeCommand(selectedProject)}</code>
                                        <button className="subtle-button" type="button" onClick={() => void copyCommand("compose", buildComposeCommand(selectedProject))}>{copyLabel(copyState, "compose")}</button>
                                    </div>
                                </div>
                                <div className="button-row">
                                    <button className="subtle-button" type="button" onClick={() => void exportJson(`${selectedProject.id}.json`, selectedProject)}>Export record JSON</button>
                                    <button className="subtle-button" type="button" onClick={() => void exportJson(`${selectedProject.manifest.projectId}-render-manifest.json`, selectedProject.manifest)}>Export manifest JSON</button>
                                </div>
                            </>
                        ) : (
                            <div className="empty-history">Generate a draft first to unlock local worker commands.</div>
                        )}
                    </div>

                    <div className="diag-block">
                        <div className="diag-title">Storage layout</div>
                        {selectedProject ? (
                            <div className="storage-grid">
                                <div><span className="summary-label">Inputs</span><strong>{selectedProject.manifest.inputDir}</strong></div>
                                <div><span className="summary-label">Cache</span><strong>{selectedProject.manifest.cacheDir}</strong></div>
                                <div><span className="summary-label">Render</span><strong>{selectedProject.manifest.renderDir}</strong></div>
                                <div><span className="summary-label">Concat / subtitles</span><strong>{selectedProject.manifest.concatFilePath}</strong><strong>{selectedProject.manifest.subtitleFilePath}</strong></div>
                            </div>
                        ) : (
                            <div className="empty-history">Generate one draft to preview where local files will land.</div>
                        )}
                    </div>

                    <div className="diag-block">
                        <div className="diag-title">Recent drafts</div>
                        <div className="history-list">
                            {projects.length ? projects.map((project) => (
                                <article key={project.id} className={`history-item ${project.id === selectedProjectId ? "active" : ""}`}>
                                    <button
                                        className="history-main"
                                        type="button"
                                        onClick={() => {
                                            setSelectedProjectId(project.id);
                                            setCopyState({ target: null, state: "idle" });
                                            setSaveState({ status: "idle", message: "" });
                                        }}
                                    >
                                        <div>
                                            <strong>{project.plan.title}</strong>
                                            <span>{formatDate(project.updatedAt)}</span>
                                        </div>
                                        <div className="history-actions">
                                            <span>{project.manifest.totalDurationSec.toFixed(1)}s</span>
                                            <span>${project.estimatedCostUsd.toFixed(2)}</span>
                                        </div>
                                    </button>
                                    <button className="history-remove" type="button" onClick={() => removeProject(project.id)}>Remove</button>
                                </article>
                            )) : <div className="empty-history">Generated drafts are stored locally in this browser.</div>}
                        </div>
                    </div>
                </section>
            </main>
        </div>
    );
}

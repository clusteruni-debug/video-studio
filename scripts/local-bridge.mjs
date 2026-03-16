import { spawn } from "node:child_process";
import { access, readFile } from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import http from "node:http";
import path from "node:path";

const bridgePort = 5161;
const projectRoot = process.cwd();
const pythonPath = path.join(projectRoot, ".venv", "Scripts", "python.exe");

function jsonResponse(response, statusCode, payload) {
    response.writeHead(statusCode, {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Type": "application/json; charset=utf-8",
    });
    response.end(JSON.stringify(payload));
}

async function pathExists(targetPath) {
    try {
        await access(targetPath, fsConstants.F_OK);
        return true;
    } catch {
        return false;
    }
}

function readJsonBody(request) {
    return new Promise((resolve, reject) => {
        const chunks = [];

        request.on("data", (chunk) => {
            chunks.push(chunk);
        });
        request.on("end", () => {
            if (!chunks.length) {
                resolve({});
                return;
            }

            try {
                const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
                resolve(payload);
            } catch (error) {
                reject(error);
            }
        });
        request.on("error", reject);
    });
}

function runCommand(command, args, options = {}) {
    const { cwd = projectRoot, timeoutMs = 30000 } = options;

    return new Promise((resolve, reject) => {
        const child = spawn(command, args, {
            cwd,
            windowsHide: true,
            stdio: ["ignore", "pipe", "pipe"],
        });

        let stdout = "";
        let stderr = "";
        let timedOut = false;
        const timer = setTimeout(() => {
            timedOut = true;
            child.kill();
        }, timeoutMs);

        child.stdout.on("data", (chunk) => {
            stdout += chunk.toString("utf8");
        });
        child.stderr.on("data", (chunk) => {
            stderr += chunk.toString("utf8");
        });
        child.on("error", (error) => {
            clearTimeout(timer);
            reject(error);
        });
        child.on("close", (code) => {
            clearTimeout(timer);

            if (timedOut) {
                reject(new Error(`Command timed out: ${command} ${args.join(" ")}`));
                return;
            }

            if (code !== 0) {
                reject(new Error(stderr.trim() || `Command failed with exit code ${code}`));
                return;
            }

            resolve({
                stdout: stdout.trim(),
                stderr: stderr.trim(),
            });
        });
    });
}

async function resolveTool(toolName) {
    const pathEntries = (process.env.PATH ?? "").split(path.delimiter).filter(Boolean);
    const pathExtensions = (process.env.PATHEXT ?? ".EXE;.CMD;.BAT").split(";").filter(Boolean);
    const suffixes = toolName.includes(".") ? [""] : pathExtensions;

    for (const entry of pathEntries) {
        for (const suffix of suffixes) {
            const candidate = path.join(entry, `${toolName}${suffix}`);
            if (await pathExists(candidate)) {
                return candidate;
            }
        }
    }

    return null;
}

function buildProviderFlags(availability) {
    if (!availability?.premiumEnabled) {
        return [];
    }

    const flags = [];
    if (availability.sora2) {
        flags.push("--sora2");
    }
    if (availability.veo3) {
        flags.push("--veo3");
    }
    return flags;
}

function validateBudgetMode(value) {
    return value === "free" || value === "standard" || value === "premium";
}

async function handleHealth(response) {
    const pythonReady = await pathExists(pythonPath);
    const [ffmpeg, ollama, hf] = await Promise.all([
        resolveTool("ffmpeg"),
        resolveTool("ollama"),
        resolveTool("hf"),
    ]);

    jsonResponse(response, pythonReady ? 200 : 500, {
        ok: pythonReady,
        service: "video-studio-local-bridge",
        port: bridgePort,
        projectRoot,
        pythonPath,
        tools: {
            ffmpeg,
            hf,
            ollama,
        },
    });
}

async function handleRoutePlan(request, response) {
    const body = await readJsonBody(request);
    if (typeof body.prompt !== "string" || !body.prompt.trim()) {
        jsonResponse(response, 400, { error: "prompt is required" });
        return;
    }
    if (!validateBudgetMode(body.budgetMode)) {
        jsonResponse(response, 400, { error: "budgetMode must be free, standard, or premium" });
        return;
    }

    const args = [
        "-m",
        "worker.planner.route_plan",
        "--prompt",
        body.prompt.trim(),
        "--budget-mode",
        body.budgetMode,
        ...buildProviderFlags(body.availability),
    ];
    const { stdout } = await runCommand(pythonPath, args);

    jsonResponse(response, 200, JSON.parse(stdout));
}

async function handleSaveProject(request, response) {
    const body = await readJsonBody(request);
    if (typeof body.prompt !== "string" || !body.prompt.trim()) {
        jsonResponse(response, 400, { error: "prompt is required" });
        return;
    }
    if (!validateBudgetMode(body.budgetMode)) {
        jsonResponse(response, 400, { error: "budgetMode must be free, standard, or premium" });
        return;
    }
    if (typeof body.projectId !== "string" || !body.projectId.trim()) {
        jsonResponse(response, 400, { error: "projectId is required" });
        return;
    }

    const args = [
        "-m",
        "worker.planner.save_plan",
        "--prompt",
        body.prompt.trim(),
        "--budget-mode",
        body.budgetMode,
        "--project-id",
        body.projectId.trim(),
        ...buildProviderFlags(body.availability),
    ];
    const { stdout } = await runCommand(pythonPath, args);
    const saveResult = JSON.parse(stdout);

    const [plan, routes, manifest] = await Promise.all([
        readFile(saveResult.planPath, "utf8").then((value) => JSON.parse(value)),
        readFile(saveResult.routesPath, "utf8").then((value) => JSON.parse(value)),
        readFile(saveResult.manifestPath, "utf8").then((value) => JSON.parse(value)),
    ]);

    jsonResponse(response, 200, {
        ok: true,
        saveResult,
        plan,
        routes,
        manifest,
    });
}

export function startBridge() {
    const server = http.createServer(async (request, response) => {
        try {
            if (!request.url || !request.method) {
                jsonResponse(response, 400, { error: "missing request url or method" });
                return;
            }

            if (request.method === "OPTIONS") {
                response.writeHead(204, {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                });
                response.end();
                return;
            }

            if (request.method === "GET" && request.url === "/api/health") {
                await handleHealth(response);
                return;
            }

            if (request.method === "POST" && request.url === "/api/route-plan") {
                await handleRoutePlan(request, response);
                return;
            }

            if (request.method === "POST" && request.url === "/api/save-project") {
                await handleSaveProject(request, response);
                return;
            }

            jsonResponse(response, 404, { error: "not found" });
        } catch (error) {
            console.error(error);
            jsonResponse(response, 500, {
                error: error instanceof Error ? error.message : "unexpected bridge error",
            });
        }
    });

    return new Promise((resolve) => {
        server.listen(bridgePort, "127.0.0.1", () => {
            console.log(
                JSON.stringify(
                    {
                        ok: true,
                        service: "video-studio-local-bridge",
                        port: bridgePort,
                        projectRoot,
                    },
                    null,
                    2,
                ),
            );
            resolve(server);
        });
    });
}

const isDirectRun = process.argv[1] && path.basename(process.argv[1]) === "local-bridge.mjs";

if (isDirectRun) {
    await startBridge();
}

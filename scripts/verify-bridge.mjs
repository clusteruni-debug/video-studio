import { access } from "node:fs/promises";
import { startBridge } from "./local-bridge.mjs";

const bridgeUrl = "http://127.0.0.1:5161";

function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fileExists(targetPath) {
    try {
        await access(targetPath);
        return true;
    } catch {
        return false;
    }
}

async function fetchJson(url, init) {
    const response = await fetch(url, {
        ...init,
        headers: {
            "Content-Type": "application/json",
            ...(init?.headers ?? {}),
        },
    });

    const payload = await response.json();
    if (!response.ok) {
        throw new Error(JSON.stringify(payload));
    }

    return payload;
}

async function main() {
    const bridge = await startBridge();

    try {
        let health = null;
        for (let index = 0; index < 20; index += 1) {
            await wait(300);
            try {
                health = await fetchJson(`${bridgeUrl}/api/health`, { method: "GET" });
                break;
            } catch {
                // keep waiting for the bridge to start
            }
        }

        if (!health) {
            throw new Error("Bridge did not become healthy");
        }

        console.log("[verify] bridge health");
        console.log(JSON.stringify(health, null, 2));

        const routePayload = {
            prompt: "30-second cafe promo reel with a warm morning mood",
            budgetMode: "premium",
            availability: {
                premiumEnabled: true,
                sora2: true,
                veo3: false,
            },
        };
        const routeResponse = await fetchJson(`${bridgeUrl}/api/route-plan`, {
            method: "POST",
            body: JSON.stringify(routePayload),
        });
        console.log("[verify] route plan");
        console.log(JSON.stringify(routeResponse, null, 2));

        const savePayload = {
            prompt: "30-second cafe promo reel with a warm morning mood",
            budgetMode: "premium",
            projectId: "verify-bridge-save",
            availability: {
                premiumEnabled: true,
                sora2: true,
                veo3: false,
            },
        };
        const saveResponse = await fetchJson(`${bridgeUrl}/api/save-project`, {
            method: "POST",
            body: JSON.stringify(savePayload),
        });
        console.log("[verify] bridge save");
        console.log(JSON.stringify(saveResponse, null, 2));

        if (!(await fileExists(saveResponse.saveResult.manifestPath))) {
            throw new Error(`Missing manifest at ${saveResponse.saveResult.manifestPath}`);
        }

        console.log("[verify] manifest path");
        console.log(saveResponse.saveResult.manifestPath);
    } finally {
        await new Promise((resolve, reject) => {
            bridge.close((error) => {
                if (error) {
                    reject(error);
                    return;
                }
                resolve();
            });
        });
    }
}

main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
});

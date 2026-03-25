import type { BridgeHealth } from "../lib/bridge";

export type BridgeStatus = "checking" | "connected" | "offline" | "error";
export type CreationMode = "draft";

export function bridgeStatusLabel(status: BridgeStatus): string {
    switch (status) {
        case "connected": return "Bridge Connected";
        case "checking": return "Checking...";
        case "offline": return "Bridge Offline";
        case "error": return "Bridge Error";
    }
}

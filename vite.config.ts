import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function fileUrlToWindowsPath(value: string): string {
    const decoded = decodeURIComponent(new URL(value, import.meta.url).pathname);
    return decoded.replace(/^\/([A-Za-z]:)/, "$1");
}

const realUiRoot = fileUrlToWindowsPath("./app/ui");
const workspaceProjectRoot = "C:/vibe/projects/video-studio";
const workspaceDistRoot = `${workspaceProjectRoot}/dist`;
const devCacheRoot = `${workspaceProjectRoot}/node_modules/.vite`;
const requiredDevOptimizedDeps = [
    "react",
    "react-dom",
    "react-dom/client",
    "react/jsx-dev-runtime",
    "react/jsx-runtime",
    "lucide-react",
];

export default defineConfig(({ command }) => ({
    root: realUiRoot,
    plugins: [react()],
    cacheDir: command === "serve" ? devCacheRoot : undefined,
    server: {
        host: "127.0.0.1",
        port: 5160,
        strictPort: true,
    },
    optimizeDeps: {
        noDiscovery: true,
        include: requiredDevOptimizedDeps,
    },
    preview: {
        host: "127.0.0.1",
        port: 4160,
        strictPort: true,
    },
    build: {
        outDir: workspaceDistRoot,
        emptyOutDir: true,
    },
}));

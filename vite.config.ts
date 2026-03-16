import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function fileUrlToWindowsPath(value: string): string {
    const decoded = decodeURIComponent(new URL(value, import.meta.url).pathname);
    return decoded.replace(/^\/([A-Za-z]:)/, "$1");
}

const uiRoot = fileUrlToWindowsPath("./app/ui");
const distRoot = fileUrlToWindowsPath("./dist");

export default defineConfig({
    root: uiRoot,
    plugins: [react()],
    server: {
        host: "127.0.0.1",
        port: 5160,
        strictPort: true,
    },
    preview: {
        host: "127.0.0.1",
        port: 4160,
        strictPort: true,
    },
    build: {
        outDir: distRoot,
        emptyOutDir: true,
    },
});

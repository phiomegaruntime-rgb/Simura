import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// In dev, proxy API + WebSocket to the twin core so the browser talks to a
// single origin (no CORS juggling). In prod, nginx does the same (nginx.conf).
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            "/api": { target: "http://localhost:8000", changeOrigin: true },
            "/health": { target: "http://localhost:8000", changeOrigin: true },
            "/ws": { target: "ws://localhost:8000", ws: true },
        },
    },
});

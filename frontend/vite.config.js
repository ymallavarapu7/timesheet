import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
export default defineConfig(function (_a) {
    var mode = _a.mode;
    var env = loadEnv(mode, process.cwd(), '');
    var frontendPort = parseInt(env.FRONTEND_PORT || '5174', 10);
    var backendHost = env.BACKEND_HOST || 'localhost';
    var backendPort = parseInt(env.BACKEND_PORT || '8000', 10);
    return {
        base: env.VITE_BASE_PATH || '/',
        plugins: [react()],
        resolve: {
            alias: {
                '@': path.resolve(__dirname, './src'),
            },
        },
        server: {
            port: frontendPort,
            strictPort: true,
            proxy: {
                '/api': {
                    target: "http://".concat(backendHost, ":").concat(backendPort),
                    changeOrigin: true,
                },
            },
        },
    };
});

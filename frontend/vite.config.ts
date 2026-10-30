import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/**
 * Ticket #21: the shell builds two bundles.
 *
 * `pnpm build`      -> dist      (test hooks compiled out via __BS_TEST_HOOKS__)
 * `pnpm build:test` -> dist-test (hooks installed for the external browser gate)
 *
 * Both builds emit content-hashed files plus `.vite/manifest.json`, which the
 * backend uses to host /app assets and to stamp X-Frontend-Build.
 */
export default defineConfig(({ mode }) => {
  const testHooks = mode === 'test' || process.env.VITE_TEST_HOOKS === '1'
  const outDir = process.env.FRONTEND_OUT_DIR || (testHooks ? 'dist-test' : 'dist')

  return {
    plugins: [vue()],
    // `public/` holds the card faces, but they are imported through
    // import.meta.glob so Vite content-hashes them into dist/assets. Disabling
    // the public-dir copy keeps `dist` free of a second, un-hashed ~20 MB copy.
    publicDir: false,
    define: {
      __BS_TEST_HOOKS__: JSON.stringify(testHooks),
    },
    build: {
      outDir,
      emptyOutDir: true,
      manifest: true,
      sourcemap: false,
      rollupOptions: {
        output: {
          entryFileNames: 'assets/[name]-[hash].js',
          chunkFileNames: 'assets/[name]-[hash].js',
          assetFileNames: 'assets/[name]-[hash][extname]',
        },
      },
    },
    server: {
      proxy: {
        '/api': 'http://127.0.0.1:5000',
        '/socket.io': { target: 'http://127.0.0.1:5000', ws: true },
      },
    },
  }
})
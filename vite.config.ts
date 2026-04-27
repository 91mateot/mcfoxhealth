import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "Mateo Fitness",
        short_name: "Mateo Fit",
        description: "Personal health & fitness dashboard",
        theme_color: "#050505",
        background_color: "#050505",
        display: "standalone",
        orientation: "portrait",
        start_url: "/",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
        ],
      },
      workbox: {
        runtimeCaching: [
          // Meal writes and any GETs under /api/meal/* must never serve from
          // cache — after tool-use logs a meal, stale cache would hide it.
          {
            urlPattern: /^https:\/\/5vvp43vamk\.execute-api\.us-west-2\.amazonaws\.com\/api\/meal.*/,
            handler: "NetworkOnly",
          },
          {
            urlPattern: /^https:\/\/5vvp43vamk\.execute-api\.us-west-2\.amazonaws\.com\/api\/.*/,
            handler: "NetworkFirst",
            options: {
              cacheName: "fitness-api",
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 50, maxAgeSeconds: 60 * 60 * 24 },
            },
          },
          {
            urlPattern: /^https:\/\/fonts\.(googleapis|gstatic)\.com\/.*/,
            handler: "CacheFirst",
            options: {
              cacheName: "google-fonts",
              expiration: { maxEntries: 10, maxAgeSeconds: 60 * 60 * 24 * 365 },
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    host: true,
  },
});

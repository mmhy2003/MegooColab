import type { MetadataRoute } from "next";

// Installable as an app (PWA): served at /manifest.webmanifest, linked from every page by Next.js
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "MegooColab",
    short_name: "MegooColab",
    description: "Project management for humans and coding agents",
    start_url: "/",
    display: "standalone",
    background_color: "#0d0221",
    theme_color: "#0d0221",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      // launchers crop this one to their own shape; its art sits inside the safe zone
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}

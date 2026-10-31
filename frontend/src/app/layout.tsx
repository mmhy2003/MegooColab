import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Orbitron } from "next/font/google";

import { Providers } from "@/components/Providers";
import { ServiceWorker } from "@/components/ServiceWorker";
import { themeBootstrapScript } from "@/lib/theme";

import "./globals.css";

// headings and text
const geist = Geist({ variable: "--font-geist", subsets: ["latin"] });
// code, task keys and shortcuts
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
// the MEGOOCOLAB wordmark only: the brand mark
const orbitron = Orbitron({ variable: "--font-orbitron", subsets: ["latin"], weight: ["700"] });

export const metadata: Metadata = {
  // a page's own title comes first: "Projects · MegooColab" (client pages set it with usePageTitle, lib/title.ts)
  title: { default: "MegooColab", template: "%s · MegooColab" },
  description: "Project management for humans and coding agents",
  appleWebApp: { capable: true, title: "MegooColab", statusBarStyle: "black-translucent" },
};

// the phone's status bar follows the theme's background
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f3ff" },
    { media: "(prefers-color-scheme: dark)", color: "#0d0221" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${geist.variable} ${geistMono.variable} ${orbitron.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrapScript }} />
      </head>
      <body className="min-h-full">
        <Providers>{children}</Providers>
        <ServiceWorker />
      </body>
    </html>
  );
}

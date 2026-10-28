import type { Metadata } from "next";
import { Orbitron, Share_Tech_Mono } from "next/font/google";

import { Providers } from "@/components/Providers";
import { themeBootstrapScript } from "@/lib/theme";

import "./globals.css";

const orbitron = Orbitron({
  variable: "--font-orbitron",
  subsets: ["latin"],
  weight: ["500", "700"],
});

const shareTech = Share_Tech_Mono({
  variable: "--font-share-tech",
  subsets: ["latin"],
  weight: "400",
});

export const metadata: Metadata = {
  title: "MegooColab",
  description: "Project management for humans and coding agents",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${orbitron.variable} ${shareTech.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrapScript }} />
      </head>
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

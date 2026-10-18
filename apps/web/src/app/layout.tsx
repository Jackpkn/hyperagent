import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HyperAgent · Browser operator",
  icons: {
    icon: [{ url: "/hyperagent-icon.svg", type: "image/svg+xml" }],
  },
  description:
    "Give the agent a goal in plain English. Watch every step in a live browser, approve risky actions, and get a checked result.",
};

// Fonts load from Google Fonts so the static export needs no build-time download.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font -- single-page app; the font applies to every route */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}

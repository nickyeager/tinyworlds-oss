import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { AuthProvider } from "@/components/auth/auth-provider";
import { SessionExpiredModal } from "@/components/auth/session-expired-modal";
import "./globals.css";

const fredoka = localFont({
  src: "./fonts/fredoka.ttf",
  variable: "--font-heading",
  weight: "300 700",
  display: "swap",
});

const nunito = localFont({
  src: "./fonts/nunito.ttf",
  variable: "--font-body",
  weight: "200 900",
  display: "swap",
});

const geistMono = localFont({
  src: "./fonts/geist-mono.ttf",
  variable: "--font-geist-mono",
  weight: "100 900",
  display: "swap",
});

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://tinyworlds.us";
const SITE_NAME = "TinyWorlds";
const SITE_TAGLINE = "Make a game by describing it";
const SITE_DESCRIPTION =
  "Describe a game and play it in your browser.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: `${SITE_NAME} — Make your own game`,
    template: `%s · ${SITE_NAME}`,
  },
  description: SITE_DESCRIPTION,
  applicationName: SITE_NAME,
  keywords: [
    "AI game generator",
    "Godot",
    "Godot 4",
    "text to game",
    "Claude",
    "WebAssembly games",
    "browser games",
    "generative game design",
  ],
  authors: [{ name: "TinyWorlds" }],
  creator: SITE_NAME,
  publisher: SITE_NAME,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: SITE_NAME,
    title: `${SITE_NAME} — ${SITE_TAGLINE}`,
    description: SITE_DESCRIPTION,
    url: SITE_URL,
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: `${SITE_NAME} — ${SITE_TAGLINE}`,
    description: SITE_DESCRIPTION,
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
};

export const viewport: Viewport = {
  themeColor: "#0D0D0D",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${fredoka.variable} ${nunito.variable} ${geistMono.variable} antialiased`}
      >
        <AuthProvider>
          {children}
          <SessionExpiredModal />
        </AuthProvider>
      </body>
    </html>
  );
}

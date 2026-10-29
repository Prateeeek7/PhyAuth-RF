import type { Metadata } from "next";
import "./globals.css";
import { AppProvider } from "../components/shell/AppContext";
import { TopBar } from "../components/shell/TopBar";

export const metadata: Metadata = {
  title: "PhyAuth-RF Console",
  description: "Physical-layer RF fingerprint authentication of 433 MHz transmitters with an ESP32 + SRX882 receiver",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <AppProvider>
          <div className="shell">
            <TopBar />
            {children}
          </div>
        </AppProvider>
      </body>
    </html>
  );
}

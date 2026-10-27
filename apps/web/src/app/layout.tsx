import "@fontsource-variable/plus-jakarta-sans";
import type { Metadata } from "next";
import Script from "next/script";
import { QueryProvider } from "@/components/providers/QueryProvider";
import { ThemedToaster } from "@/components/providers/ThemedToaster";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "RABmate AI", template: "%s · RABmate AI" },
  description: "Estimasi biaya proyek, katalog harga, dan dokumen bisnis dengan bantuan AI lokal.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // The boot script may set data-theme before React hydrates <html>.
    <html lang="id" className="h-full antialiased" suppressHydrationWarning>
      <body className="min-h-full font-sans">
        <Script id="theme-boot" strategy="beforeInteractive">
          {THEME_BOOT_SCRIPT}
        </Script>
        <QueryProvider>{children}</QueryProvider>
        <ThemedToaster />
      </body>
    </html>
  );
}

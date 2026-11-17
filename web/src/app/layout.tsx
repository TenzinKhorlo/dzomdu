// first, so its @layer order (reset < base < astryx-base < astryx-theme) is registered before any component CSS
import "./globals.css"

import type { Metadata, Viewport } from "next"
import { GeistMono } from "geist/font/mono"
import { GeistSans } from "geist/font/sans"

import { AppChrome } from "@/components/app-chrome"
import { Providers } from "@/components/providers"


export const viewport: Viewport = { viewportFit: "cover" }

export const metadata: Metadata = {
  title: "Dzomdu",
  description: "Offline meeting notes with speaker recognition",
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" data-astryx-theme="dzomdu" suppressHydrationWarning>
      <body className={`${GeistSans.variable} ${GeistMono.variable} font-sans antialiased`}>
        <Providers>
          <AppChrome>{children}</AppChrome>
        </Providers>
      </body>
    </html>
  )
}

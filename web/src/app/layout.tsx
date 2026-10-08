import type { Metadata } from "next"
import { GeistMono } from "geist/font/mono"
import "@fontsource-variable/inter/opsz.css"

import { AppSidebar } from "@/components/app-sidebar"
import { SidebarInset, SidebarProvider } from "@/components/animate-ui/components/radix/sidebar"
import { Providers } from "@/components/providers"
import { SiteHeader } from "@/components/site-header"

import "./globals.css"

export const metadata: Metadata = {
  title: "Dzomdu",
  description: "Offline meeting notes with speaker recognition",
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${GeistMono.variable} font-sans antialiased`}>
        <Providers>
          <SidebarProvider>
            <AppSidebar />
            <SidebarInset>
              <SiteHeader />
              <div className="flex flex-1 flex-col gap-5 px-4 pt-5 pb-8 md:px-7">{children}</div>
            </SidebarInset>
          </SidebarProvider>
        </Providers>
      </body>
    </html>
  )
}

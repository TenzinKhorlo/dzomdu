import type { Metadata } from "next"
import { GeistMono } from "geist/font/mono"
import { GeistSans } from "geist/font/sans"

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
      <body className={`${GeistSans.variable} ${GeistMono.variable} font-sans antialiased`}>
        <Providers>
          <SidebarProvider style={{ "--sidebar-width": "14rem" } as React.CSSProperties}>
            <AppSidebar />
            <SidebarInset className="min-w-0">
              <SiteHeader />
              <div className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-5 px-4 py-6 md:px-6 lg:px-8">{children}</div>
            </SidebarInset>
          </SidebarProvider>
        </Providers>
      </body>
    </html>
  )
}

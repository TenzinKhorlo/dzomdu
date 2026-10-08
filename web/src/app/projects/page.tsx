"use client"

import Link from "next/link"
import { ArrowRight, Folder, Layers } from "lucide-react"

import { Fade } from "@/components/animate-ui/primitives/effects/fade"
import { EmptyState, PageHeader } from "@/components/common"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import type { Project } from "@/lib/api"
import { colorFor, relative } from "@/lib/format"

export default function ProjectsPage() {
  const { data } = useApi<Project[]>("/api/projects")
  return (
    <div className="@container/main flex flex-col gap-6">
      <PageHeader
        title="Projects"
        description="Each project is a folder in your vault with an overview note, a glossary and its meetings."
      />
      {!data ? (
        <div className="grid gap-4 @3xl/main:grid-cols-2 @6xl/main:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : data.length === 0 ? (
        <EmptyState
          icon={Layers}
          title="No projects yet"
          description="Give a meeting a project name when you record it, and a project folder is created in your vault."
        />
      ) : (
        <div className="grid gap-4 @3xl/main:grid-cols-2 @6xl/main:grid-cols-3">
          {data.map((p, i) => (
            <Fade key={p.name} delay={i * 40}>
              <Link href={`/meetings/?project=${encodeURIComponent(p.name)}`} className="group block h-full">
                <Card className="h-full transition-colors group-hover:border-foreground/20">
                  <CardHeader>
                    <div
                      className="mb-2 flex size-8 items-center justify-center rounded-lg text-white"
                      style={{ backgroundColor: colorFor(p.name) }}
                    >
                      <Folder className="size-4 fill-current" />
                    </div>
                    <CardTitle>{p.name}</CardTitle>
                    <CardDescription>
                      {p.last ? `Last meeting ${relative(p.last).toLowerCase()}` : "No meetings yet"}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="flex-1">
                    <p className="line-clamp-3 text-[13px] text-muted-foreground">
                      {p.overview || "Add goals, scope and a glossary in the project's overview note."}
                    </p>
                  </CardContent>
                  <CardFooter className="justify-between border-t text-[13px]">
                    <span className="tabular-nums text-muted-foreground">
                      {p.meetings} meeting{p.meetings === 1 ? "" : "s"} · {Math.round(p.minutes)} min
                    </span>
                    <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                  </CardFooter>
                </Card>
              </Link>
            </Fade>
          ))}
        </div>
      )}
    </div>
  )
}

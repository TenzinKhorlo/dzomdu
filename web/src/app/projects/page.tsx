"use client"

import Link from "next/link"
import { ArrowRight, Folder, FolderPlus, Layers } from "lucide-react"

import { useChatHistory } from "@/components/chat/provider"
import { Fade } from "@/components/animate-ui/primitives/effects/fade"
import { EmptyState, PageHeader } from "@/components/common"
import { NewProjectDialog } from "@/components/new-project-dialog"
import { ProjectActions } from "@/components/project-actions"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import { projectHref, type Project } from "@/lib/api"
import { colorFor, relative } from "@/lib/format"

export default function ProjectsPage() {
  const { chats } = useChatHistory()
  const { data, reload } = useApi<Project[]>("/api/projects")
  return (
    <div className="@container/main flex flex-col gap-6">
      <PageHeader
        title="Projects"
        description="Each project is a folder in your vault with an overview note, a glossary and its meetings."
      >
        <NewProjectDialog onCreated={reload}>
          <Button>
            <FolderPlus />
            New project
          </Button>
        </NewProjectDialog>
      </PageHeader>
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
          description="Create a project to group related meetings, or name one when you record a meeting."
        >
          <NewProjectDialog onCreated={reload}>
            <Button variant="outline">
              <FolderPlus />
              New project
            </Button>
          </NewProjectDialog>
        </EmptyState>
      ) : (
        <div className="grid gap-4 @3xl/main:grid-cols-2 @6xl/main:grid-cols-3">
          {data.map((p, i) => (
            <Fade key={p.name} delay={i * 40}>
              <Card className="group relative h-full transition-colors hover:border-foreground/20">
                <Link
                  href={projectHref(p.name)}
                  className="absolute inset-0 rounded-xl focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  aria-label={`Open project ${p.name}`}
                />
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div
                      className="mb-2 flex size-8 items-center justify-center rounded-lg text-white"
                      style={{ backgroundColor: colorFor(p.name) }}
                    >
                      <Folder className="size-4 fill-current" />
                    </div>
                    <ProjectActions project={p} onChanged={reload} />
                  </div>
                  <CardTitle>{p.name}</CardTitle>
                  <CardDescription>
                    {p.last ? `Last meeting ${relative(p.last).toLowerCase()}` : "No meetings yet"}
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex-1">
                  <p className="line-clamp-3 text-[13px] text-muted-foreground">
                    {p.overview ||
                      "Add goals, scope and a glossary in the project's overview note."}
                  </p>
                </CardContent>
                <CardFooter className="justify-between border-t text-[13px]">
                  <span className="tabular-nums text-muted-foreground">
                    {p.meetings} meeting{p.meetings === 1 ? "" : "s"} · {Math.round(p.minutes)} min
                  </span>
                  {chats.some((chat) => chat.project === p.name) && (
                    <Link
                      href={`/chat/history/?project=${encodeURIComponent(p.name)}`}
                      className="relative z-10 text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
                    >
                      {chats.filter((chat) => chat.project === p.name).length} chats
                    </Link>
                  )}
                  <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </CardFooter>
              </Card>
            </Fade>
          ))}
        </div>
      )}
    </div>
  )
}

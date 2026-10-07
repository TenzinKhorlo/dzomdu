"use client"

import * as React from "react"
import { Loader2, MoreHorizontal, Pencil, ShieldCheck, Trash2, Users } from "lucide-react"
import { toast } from "sonner"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/animate-ui/components/radix/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/animate-ui/components/radix/dropdown-menu"
import { Fade } from "@/components/animate-ui/primitives/effects/fade"
import { EmptyState, PageHeader, SpeakerAvatar } from "@/components/common"
import { useConfirm } from "@/components/confirm"
import { useInfo } from "@/components/providers"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useApi } from "@/hooks/use-api"
import { api, type Voice } from "@/lib/api"

function ProfileForm({
  voice,
  onClose,
  onSaved,
}: {
  voice: Voice
  onClose: () => void
  onSaved: () => void
}) {
  const [form, setForm] = React.useState({
    name: voice.name,
    role: voice.role,
    organisation: voice.organisation,
    bio: voice.bio,
  })
  const [busy, setBusy] = React.useState(false)

  async function save() {
    setBusy(true)
    try {
      if (form.name.trim() !== voice.name) {
        await api("/api/speakers/rename", {
          method: "POST",
          json: { old: voice.name, new: form.name.trim() },
        })
      }
      await api("/api/people", {
        method: "POST",
        json: {
          name: form.name.trim(),
          role: form.role,
          organisation: form.organisation,
          bio: form.bio,
        },
      })
      toast.success("Profile saved", { description: "Also updated in People/ in your vault." })
      onSaved()
      onClose()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Edit profile</DialogTitle>
        <DialogDescription>
          Role and bio are given to the LLM as context, so summaries know who does what.
        </DialogDescription>
      </DialogHeader>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2 sm:col-span-2">
          <Label htmlFor="p-name">Name</Label>
          <Input
            id="p-name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="p-role">Role</Label>
          <Input
            id="p-role"
            placeholder="e.g. Project manager"
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="p-org">Organisation</Label>
          <Input
            id="p-org"
            value={form.organisation}
            onChange={(e) => setForm({ ...form, organisation: e.target.value })}
          />
        </div>
        <div className="grid gap-2 sm:col-span-2">
          <Label htmlFor="p-bio">Bio</Label>
          <Textarea
            id="p-bio"
            rows={4}
            placeholder="What they work on and are responsible for"
            value={form.bio}
            onChange={(e) => setForm({ ...form, bio: e.target.value })}
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={save} disabled={busy || !form.name.trim()}>
          {busy && <Loader2 className="animate-spin" />}
          Save
        </Button>
      </DialogFooter>
    </>
  )
}

function ProfileDialog({
  voice,
  onClose,
  onSaved,
}: {
  voice: Voice | null
  onClose: () => void
  onSaved: () => void
}) {
  return (
    <Dialog open={voice !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {voice && (
          <ProfileForm key={voice.name} voice={voice} onClose={onClose} onSaved={onSaved} />
        )}
      </DialogContent>
    </Dialog>
  )
}

export default function PeoplePage() {
  const { data, reload } = useApi<Voice[]>("/api/speakers")
  const { reload: reloadInfo } = useInfo()
  const [editing, setEditing] = React.useState<Voice | null>(null)
  const confirm = useConfirm()

  async function forget(v: Voice) {
    const ok = await confirm({
      title: `Forget ${v.name}'s voice?`,
      description:
        "Their voiceprints and clips are deleted, so they won't be recognised next time. Meeting notes and their profile are kept.",
      confirmLabel: "Forget voice",
      destructive: true,
    })
    if (!ok) return
    try {
      await api(`/api/speakers/${encodeURIComponent(v.name)}`, { method: "DELETE" })
      toast.success(`Forgot ${v.name}'s voice`)
      reload()
      reloadInfo()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <div className="@container/main flex flex-col gap-6">
      <PageHeader
        title="People"
        description="Everyone whose voice Dzomdu recognises. Voiceprints are stored only on this computer, outside your notes."
      />
      {!data ? (
        <div className="grid gap-4 @3xl/main:grid-cols-2 @6xl/main:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-48 rounded-xl" />
          ))}
        </div>
      ) : data.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No voices yet"
          description="After a meeting, name each speaker on the review screen. Their voice is remembered and recognised next time."
        />
      ) : (
        <div className="grid gap-4 @3xl/main:grid-cols-2 @6xl/main:grid-cols-3">
          {data.map((v, i) => (
            <Fade key={v.name} delay={i * 40}>
              <Card className="h-full">
                <CardHeader className="flex flex-row items-center gap-3">
                  <SpeakerAvatar name={v.name} size="lg" />
                  <div className="min-w-0 flex-1">
                    <CardTitle className="truncate">{v.name}</CardTitle>
                    <CardDescription className="truncate">
                      {[v.role, v.organisation].filter(Boolean).join(" · ") || "No role yet"}
                    </CardDescription>
                  </div>
                  <CardAction>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" aria-label={`Actions for ${v.name}`}>
                          <MoreHorizontal />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => setEditing(v)}>
                          <Pencil />
                          Edit profile
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem variant="destructive" onClick={() => void forget(v)}>
                          <Trash2 />
                          Forget voice
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </CardAction>
                </CardHeader>
                <CardContent className="flex-1">
                  <p className="line-clamp-3 text-sm text-muted-foreground">
                    {v.bio || "Add a short bio so summaries know what this person works on."}
                  </p>
                </CardContent>
                <CardFooter className="flex flex-wrap gap-2 text-xs">
                  <Badge variant="secondary" className="tabular-nums">
                    {v.meetings} meeting{v.meetings === 1 ? "" : "s"}
                  </Badge>
                  <Badge variant="secondary" className="tabular-nums">
                    {v.minutes} min spoken
                  </Badge>
                  <Badge variant="outline" className="tabular-nums">
                    {v.samples} voice sample{v.samples === 1 ? "" : "s"}
                  </Badge>
                  {v.consent && (
                    <Badge variant="outline" className="gap-1 text-success">
                      <ShieldCheck />
                      Consent
                    </Badge>
                  )}
                </CardFooter>
              </Card>
            </Fade>
          ))}
        </div>
      )}
      <ProfileDialog
        voice={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          reload()
          reloadInfo()
        }}
      />
    </div>
  )
}

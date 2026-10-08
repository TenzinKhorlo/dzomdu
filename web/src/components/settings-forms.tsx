"use client"

import * as React from "react"
import { CheckCircle2, FolderOpen, Loader2, TriangleAlert } from "lucide-react"
import { toast } from "sonner"

import { useInfo } from "@/components/providers"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

type Settings = {
  llm: { api: "ollama" | "openai"; base_url: string; model: string; api_key_set: boolean }
  vault: string
}

const PROVIDERS = {
  local: {
    label: "On this computer",
    hint: "Ollama running locally. Nothing leaves your computer.",
    api: "ollama",
    base_url: "http://localhost:11434",
    model: "qwen3:14b",
  },
  cloud: {
    label: "Ollama Cloud",
    hint: "Runs on Ollama's servers, so there is no model to download. The transcript is sent to Ollama. Create a key at ollama.com/settings/keys.",
    api: "ollama",
    base_url: "https://ollama.com",
    model: "gpt-oss:120b",
  },
  custom: {
    label: "Another server",
    hint: "Any OpenAI-compatible server: LM Studio, mlx-lm, vLLM, or your own Ollama on another machine.",
    api: "openai",
    base_url: "http://localhost:1234/v1",
    model: "",
  },
} as const
type Provider = keyof typeof PROVIDERS

function providerOf(s: Settings["llm"]): Provider {
  if (s.api === "openai") return "custom"
  return s.base_url.includes("ollama.com") ? "cloud" : "local"
}

function Field({
  id,
  label,
  help,
  ...props
}: { id: string; label: string; help?: string } & React.ComponentProps<typeof Input>) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} {...props} />
      {help && <p className="text-xs text-muted-foreground">{help}</p>}
    </div>
  )
}

function LLMForm({ saved, onSaved }: { saved: Settings["llm"]; onSaved: () => void }) {
  const [provider, setProvider] = React.useState<Provider>(providerOf(saved))
  const [baseUrl, setBaseUrl] = React.useState(saved.base_url)
  const [model, setModel] = React.useState(saved.model)
  const [apiKey, setApiKey] = React.useState("")
  const [clearKey, setClearKey] = React.useState(false)
  const [busy, setBusy] = React.useState<"test" | "save" | null>(null)
  const [result, setResult] = React.useState<{ ok: boolean; detail: string } | null>(null)

  function pick(p: Provider) {
    if (p === provider) return
    setProvider(p)
    setBaseUrl(PROVIDERS[p].base_url)
    setModel(p === providerOf(saved) ? saved.model : PROVIDERS[p].model)
    setResult(null)
  }

  const payload = {
    api: PROVIDERS[provider].api,
    base_url: baseUrl,
    model,
    api_key: apiKey || null,
    clear_api_key: clearKey,
  }
  const keyKept = saved.api_key_set && !clearKey
  const needsKey = provider === "cloud" && !apiKey && !keyKept

  async function test() {
    setBusy("test")
    try {
      setResult(await api("/api/settings/llm/test", { method: "POST", json: payload }))
    } catch (e) {
      setResult({ ok: false, detail: (e as Error).message })
    } finally {
      setBusy(null)
    }
  }

  async function save() {
    setBusy("save")
    try {
      await api("/api/settings", { method: "PUT", json: { llm: payload } })
      toast.success("Language model settings saved")
      setApiKey("")
      setClearKey(false)
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Language model</CardTitle>
        <CardDescription>Writes the summary, decisions and action items for each meeting</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div role="radiogroup" aria-label="Where the model runs" className="grid gap-2 sm:grid-cols-3">
          {(Object.keys(PROVIDERS) as Provider[]).map((p) => (
            <button
              key={p}
              type="button"
              role="radio"
              aria-checked={provider === p}
              onClick={() => pick(p)}
              className={cn(
                "rounded-lg border px-3 py-2 text-left text-[13px] transition-colors hover:bg-accent",
                provider === p && "border-foreground/60 bg-accent font-medium",
              )}
            >
              {PROVIDERS[p].label}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">{PROVIDERS[provider].hint}</p>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            id="llm-url"
            label="Server URL"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            spellCheck={false}
            placeholder="http://localhost:11434"
          />
          <Field
            id="llm-model"
            label="Model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            spellCheck={false}
            placeholder="qwen3:14b"
            help={provider === "local" ? "Download it once with: ollama pull <model>" : undefined}
          />
        </div>
        {provider !== "local" && (
          <div className="grid gap-1.5">
            <Field
              id="llm-key"
              label={provider === "cloud" ? "API key" : "API key (if the server needs one)"}
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value)
                setClearKey(false)
              }}
              placeholder={keyKept ? "Saved. Leave blank to keep it" : ""}
            />
            <p className="text-xs text-muted-foreground">
              Stored in your Dzomdu config file on this computer, readable only by you.
              {keyKept && (
                <>
                  {" "}
                  <button
                    type="button"
                    className="underline underline-offset-2 hover:text-foreground"
                    onClick={() => {
                      setClearKey(true)
                      setApiKey("")
                    }}
                  >
                    Remove saved key
                  </button>
                </>
              )}
              {clearKey && " The saved key will be removed when you save."}
            </p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={save} disabled={busy !== null || !baseUrl.trim() || !model.trim()}>
            {busy === "save" && <Loader2 className="animate-spin" />}
            Save
          </Button>
          <Button
            variant="outline"
            onClick={test}
            disabled={busy !== null || !baseUrl.trim() || !model.trim() || needsKey}
          >
            {busy === "test" && <Loader2 className="animate-spin" />}
            Test connection
          </Button>
          {result && (
            <span
              role="status"
              className={cn(
                "inline-flex items-center gap-1.5 text-[13px]",
                result.ok ? "text-success" : "text-warning",
              )}
            >
              {result.ok ? <CheckCircle2 className="size-4" /> : <TriangleAlert className="size-4" />}
              {result.detail}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function VaultForm({ saved, onSaved }: { saved: string; onSaved: () => void }) {
  const [path, setPath] = React.useState(saved)
  const [busy, setBusy] = React.useState(false)

  async function save() {
    setBusy(true)
    try {
      await api("/api/settings", { method: "PUT", json: { vault: path } })
      toast.success("Vault location saved")
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderOpen className="size-4" />
          Vault
        </CardTitle>
        <CardDescription>Where meeting notes, people and projects are saved</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <Field
          id="vault-path"
          label="Folder on this computer"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          spellCheck={false}
          className="font-mono text-xs"
          help="Open this folder in Obsidian with Open folder as vault. It is created if it doesn't exist."
        />
        <p className="text-xs text-muted-foreground">
          New notes go to the new folder. Notes already written stay where they are, so move them
          yourself if you want them together.
        </p>
        <div>
          <Button onClick={save} disabled={busy || !path.trim() || path.trim() === saved}>
            {busy && <Loader2 className="animate-spin" />}
            Save location
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

export function SettingsForms({ children }: { children?: React.ReactNode }) {
  const { data, reload } = useApi<Settings>("/api/settings")
  const { reload: reloadInfo } = useInfo()
  if (!data) return <Skeleton className="h-64 rounded-xl" />
  const saved = () => {
    reload()
    reloadInfo()
  }
  // keyed on the saved values so the forms reset to what the server now holds
  return (
    <>
      <LLMForm key={JSON.stringify(data.llm)} saved={data.llm} onSaved={saved} />
      <div className="grid gap-4 @4xl/main:grid-cols-2">
        <VaultForm key={data.vault} saved={data.vault} onSaved={saved} />
        {children}
      </div>
    </>
  )
}

"use client"

import { Monitor, Moon, Sun } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { useTheme } from "next-themes"
import { flushSync } from "react-dom"

import { Button } from "@/components/ui/button"
import { useMounted } from "@/hooks/use-mounted"
import { springSnappy } from "@/lib/motion"

type Mode = "light" | "dark" | "system"
const ICON = { light: Sun, dark: Moon, system: Monitor }
const LABEL = { light: "Light", dark: "Dark", system: "Match system" }

/**
 * Cycles system → the opposite look → the system's look again, explicitly → system, with a short
 * cross-fade (no abrupt brightness jump). Starting from "system", the first click always changes
 * what you see.
 */
export function ThemeToggle() {
  const { theme, setTheme, systemTheme } = useTheme()
  const mounted = useMounted()
  const sys = systemTheme === "dark" ? "dark" : "light"
  const order: Mode[] = ["system", sys === "dark" ? "light" : "dark", sys]
  const current: Mode = mounted && order.includes(theme as Mode) ? (theme as Mode) : "system"
  const next = order[(order.indexOf(current) + 1) % order.length]
  const Icon = ICON[current]

  function change() {
    const apply = () => flushSync(() => setTheme(next))
    if (typeof document !== "undefined" && "startViewTransition" in document) {
      document.startViewTransition(apply)
    } else {
      apply()
    }
  }

  return (
    <Button
      variant="outline"
      size="icon"
      onClick={change}
      aria-label={`Appearance: ${LABEL[current]}. Switch to ${LABEL[next]}`}
      title={`Appearance: ${LABEL[current]}`}
    >
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={mounted ? current : "placeholder"}
          initial={{ opacity: 0, scale: 0.6, rotate: -45 }}
          animate={{ opacity: 1, scale: 1, rotate: 0 }}
          exit={{ opacity: 0, scale: 0.6, rotate: 45 }}
          transition={springSnappy}
          className="flex"
        >
          <Icon />
        </motion.span>
      </AnimatePresence>
    </Button>
  )
}

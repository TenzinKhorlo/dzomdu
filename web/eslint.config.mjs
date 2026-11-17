import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Third-party registry code (shadcn/ui, Animate UI), managed with `npx shadcn add`
    "src/components/ui/**",
    "src/components/animate-ui/**",
    // Built output of `astryx theme build` (the editable source is src/themes/*/*Theme.ts)
    "src/themes/**/*.d.ts",
    "src/themes/**/*.js",
    "src/themes/**/*.mjs",
    "src/hooks/use-mobile.ts",
    "src/hooks/use-controlled-state.tsx",
    "src/hooks/use-data-state.tsx",
    "src/hooks/use-is-in-view.tsx",
    "src/lib/get-strict-context.tsx",
  ]),
]);

export default eslintConfig;

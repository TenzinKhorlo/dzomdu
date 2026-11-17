import {defineTheme} from '@astryxdesign/core/theme';
import {neutralTheme} from '@astryxdesign/theme-neutral';

import {palette} from './tokens/dzomdu.palette';

/**
 * Dzomdu brand theme: deep blue actions on a warm neutral canvas, compact 8px controls and 12px
 * panels, Geist throughout. Light values come from the shipped brand tokens (primary #004182,
 * canvas #fafaf9, ink #1e1c1b, line #e4e4e2); dark values keep the same hue on a neutral grey ramp.
 */
export const dzomduTheme = defineTheme({
  name: 'dzomdu',
  extends: neutralTheme,
  typography: {
    scale: {base: 13, ratio: 1.2},
    body: {family: 'var(--font-geist-sans)', fallbacks: '-apple-system, BlinkMacSystemFont, system-ui, sans-serif'},
    heading: {family: 'var(--font-geist-sans)', fallbacks: '-apple-system, BlinkMacSystemFont, system-ui, sans-serif'},
    code: {family: 'var(--font-geist-mono)', fallbacks: 'ui-monospace, "SF Mono", Menlo, monospace'},
  },
  radius: {base: 4, multiplier: 1},
  tokens: {
    '--color-accent': ['#004182', palette.brand.dark[75]],
    '--color-on-accent': ['#ffffff', palette.brand.dark[15]],
    '--color-accent-muted': ['#edf3fa', '#1b2a3d'],
    '--color-text-accent': ['#004182', palette.brand.dark[75]],
    '--color-background-body': ['#fafaf9', '#161616'],
    '--color-background-surface': ['#ffffff', '#1c1c1c'],
    '--color-background-card': ['#ffffff', '#1c1c1c'],
    '--color-background-popover': ['#ffffff', '#222222'],
    '--color-background-muted': ['#f3f3f1', '#262626'],
    '--color-text-primary': ['#1e1c1b', '#f5f5f5'],
    '--color-text-secondary': ['#6b6966', '#a3a3a3'],
    '--color-border': ['#e4e4e2', '#2e2e2e'],
    '--color-border-emphasized': ['#d4d4d1', '#3d3d3d'],
    '--color-success': ['#15803d', '#4ade80'],
    '--color-error': ['#c62828', '#f87171'],
    // nothing below 11px: the neutral base goes down to 5px, which no label needs
    '--font-size-3xs': '0.6875rem',
    '--font-size-2xs': '0.6875rem',
    '--font-size-xs': '0.6875rem',
    '--font-size-sm': '0.75rem',
    // hierarchy from size and colour; 600 is kept for rare emphasis only
    '--text-heading-1-weight': 'var(--font-weight-medium)',
    '--text-heading-2-weight': 'var(--font-weight-medium)',
    '--text-heading-3-weight': 'var(--font-weight-medium)',
    '--text-heading-4-weight': 'var(--font-weight-medium)',
    '--focus-outline-color': 'var(--color-accent)',
  },
  // the neutral base keeps its own blue for accent status fills; follow the brand instead
  localTokens: {
    '--astryx-theme-neutral-color-status-fill-accent': ['#004182', palette.brand.dark[75]],
  },
  components: {
    card: {base: {padding: '20px'}},
    token: {base: {borderRadius: 'var(--radius-inner)'}},
    'table-header-cell': {base: {fontWeight: 'var(--font-weight-medium)'}},
    'side-nav-item': {selected: {fontWeight: 'var(--font-weight-medium)'}},
  },
});

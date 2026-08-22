// Top-level information architecture for the dashboard.
//
// The app opens on a landing page of cards — one per simulation component. Each
// card drills into that component's default view, and the top bar then shows a
// sub-nav scoped to just that component (the landing itself shows no nav). This
// module is the single source of truth for that structure, shared by App (the
// render switch), TopBar (the sub-nav) and HomeView (the cards).
//
// Optional modules (see ./modules.ts) contribute sections of their own, so the
// view and section keys are open: the built-in ones stay literal for
// autocomplete and exhaustive switches, and a module's key is any other string.

import { MODULES, moduleForView } from "./modules";

export type CoreView =
  | "home"
  | "fleet"
  | "system"
  | "validation"
  | "build"
  | "wires"
  | "wiresvalidation"
  | "lights"
  | "lightsvalidation"
  | "learn";

// `string & {}` keeps the literals in autocomplete while admitting module keys.
export type View = CoreView | (string & {});

export type CoreSectionKey = "batteries" | "wires" | "lights" | "learn";

export type SectionKey = CoreSectionKey | (string & {});

// A navigable destination within a section's sub-nav. "system" (the per-system
// detail view) is reached by drilling into a card, not from the sub-nav.
export interface NavItem {
  key: Exclude<View, "home" | "system">;
  label: string;
}

// Re-exported so a module can type its manifest against the same contract the
// built-in sections use, without reaching past this file.
export type { DashboardModule } from "./modules";

export interface Section {
  key: SectionKey;
  label: string;
  tagline: string; // one line shown on the card
  description: string; // supporting sentence on the card
  contents: string[]; // what lives inside, listed on the card
  accent: string; // card + sub-nav accent color
  icon: string; // emoji glyph for the card
  landing: View; // the view a card opens
  nav: NavItem[]; // the section's sub-nav
}

export const SECTIONS: Section[] = [
  {
    key: "batteries",
    label: "Batteries",
    tagline: "BESS digital twin",
    description:
      "Design a battery system, run it as a live twin, and validate the physics against real open datasets.",
    contents: ["Fleet", "Build", "Validation"],
    accent: "#0ca30c",
    icon: "🔋",
    landing: "fleet",
    nav: [
      { key: "fleet", label: "Fleet" },
      { key: "build", label: "Build" },
      { key: "validation", label: "Validation" },
    ],
  },
  {
    key: "wires",
    label: "Wires",
    tagline: "Wiring planner",
    description:
      "Physics-based wire sizing — check a run against ampacity, voltage drop and temperature, size the smallest adequate gauge, and validate the model against published conductor standards.",
    contents: ["Wiring planner", "Wire catalog", "Validation"],
    accent: "#eda100",
    icon: "🔌",
    landing: "wires",
    nav: [
      { key: "wires", label: "Wiring planner" },
      { key: "wiresvalidation", label: "Validation" },
    ],
  },
  {
    key: "lights",
    label: "Lights",
    tagline: "Lighting designer",
    description:
      "Every light source from LED to sodium arc, simulated from its spectrum up — then designed into a room, checked against the lux a task needs, and validated against published photometry and the live sky.",
    contents: ["Lighting planner", "Spectra & lamps", "Validation"],
    accent: "#4fc3f7",
    icon: "💡",
    landing: "lights",
    nav: [
      { key: "lights", label: "Lighting planner" },
      { key: "lightsvalidation", label: "Validation" },
    ],
  },
  // Not a physics component — the reading room for all three of them. It earns
  // a landing card of its own because "what does this mean" is a thing people
  // arrive wanting, not only a thing they need mid-task.
  {
    key: "learn",
    label: "Learn",
    tagline: "Plain language",
    description:
      "Every model in Simura and every setting it takes, explained for someone who works in a different field — including, plainly, what each model cannot tell you.",
    contents: ["Model cards", "Glossary", "Settings"],
    accent: "#9085e9",
    icon: "📘",
    landing: "learn",
    nav: [{ key: "learn", label: "Model cards" }],
  },
];

// Which section a view belongs to. The per-system detail view lives under Batteries.
const VIEW_SECTION: Record<Exclude<CoreView, "home">, CoreSectionKey> = {
  fleet: "batteries",
  build: "batteries",
  validation: "batteries",
  system: "batteries",
  wires: "wires",
  wiresvalidation: "wires",
  lights: "lights",
  lightsvalidation: "lights",
  learn: "learn",
};

// Every section the app can show: the built-ins, then whatever modules are
// installed. This is what the landing page renders.
export const ALL_SECTIONS: Section[] = [...SECTIONS, ...MODULES.map((m) => m.section)];

// The section a view belongs to, or null on the landing page.
export function sectionOf(view: View): Section | null {
  if (view === "home") return null;
  const key = VIEW_SECTION[view as Exclude<CoreView, "home">];
  if (key) return SECTIONS.find((s) => s.key === key) ?? null;
  return moduleForView(view)?.section ?? null;
}

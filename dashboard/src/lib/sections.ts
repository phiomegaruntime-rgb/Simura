// Top-level information architecture for the dashboard.
//
// The app opens on a landing page of cards — one per simulation component. Each
// card drills into that component's default view, and the top bar then shows a
// sub-nav scoped to just that component (the landing itself shows no nav). This
// module is the single source of truth for that structure, shared by App (the
// render switch), TopBar (the sub-nav) and HomeView (the cards).

export type View =
  | "home"
  | "fleet"
  | "system"
  | "validation"
  | "build"
  | "wires"
  | "wiresvalidation"
  | "lights"
  | "lightsvalidation";

export type SectionKey = "batteries" | "wires" | "lights";

// A navigable destination within a section's sub-nav. "system" (the per-system
// detail view) is reached by drilling into a card, not from the sub-nav.
export interface NavItem {
  key: Exclude<View, "home" | "system">;
  label: string;
}

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
];

// Which section a view belongs to. The per-system detail view lives under Batteries.
const VIEW_SECTION: Record<Exclude<View, "home">, SectionKey> = {
  fleet: "batteries",
  build: "batteries",
  validation: "batteries",
  system: "batteries",
  wires: "wires",
  wiresvalidation: "wires",
  lights: "lights",
  lightsvalidation: "lights",
};

// The section a view belongs to, or null on the landing page.
export function sectionOf(view: View): Section | null {
  if (view === "home") return null;
  const key = VIEW_SECTION[view];
  return SECTIONS.find((s) => s.key === key) ?? null;
}

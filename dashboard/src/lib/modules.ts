// Optional dashboard modules.
//
// Everything in `src/modules/` is discovered at build time and merged into the
// app's information architecture: each module contributes a landing card, a
// sub-nav, and the view behind it, exactly as if it were built in. Nothing here
// names a particular module, and no core file imports one — a module is present
// or it isn't, and the dashboard is complete either way.
//
// `import.meta.glob` resolves to `{}` when the directory is empty, so a checkout
// with no modules type-checks and builds with no missing-import error and no
// dead code in the bundle. Modules stay lazy for the same reason they always
// were: a heavy dependency (three.js, a map engine) must not touch the 2D
// dashboard's first paint.

import type { ComponentType, LazyExoticComponent } from "react";
import { lazy } from "react";
import type { Section } from "./sections";

/** What the app hands a module's root view. */
export interface ModuleViewProps {
  /**
   * Leave the module and go back to the landing cards.
   *
   * Every view gets it; an `immersive` one depends on it, because it has hidden
   * the top bar that would otherwise be the way out.
   */
  onExit: () => void;
}

export interface DashboardModule {
  /** The landing card and sub-nav this module adds. */
  section: Section;
  /** Loader for the module's root view — passed straight to `React.lazy`. */
  load: () => Promise<{ default: ComponentType<ModuleViewProps> }>;
  /**
   * True if the view wants the whole viewport rather than the dashboard's
   * reading measure. A 3D canvas does; a form does not.
   */
  fullBleed?: boolean;
  /**
   * True if the view replaces the dashboard's own chrome — the top bar and the
   * footer — and takes the whole browser window. Implies `fullBleed`.
   *
   * For a view whose interface is itself (a scene with its own menus), where a
   * header across the top is a second interface competing with the first. Such
   * a view must offer its own way back, through `onExit`.
   */
  immersive?: boolean;
}

/** A module as the app consumes it: manifest plus its resolved lazy component. */
export interface LoadedModule extends DashboardModule {
  view: LazyExoticComponent<ComponentType<ModuleViewProps>>;
}

const found = import.meta.glob<{ default: DashboardModule }>("../modules/*/index.ts", {
  eager: true,
});

export const MODULES: LoadedModule[] = Object.values(found)
  .map((m) => m.default)
  .filter(Boolean)
  .map((mod) => ({ ...mod, view: lazy(mod.load) }));

/** The module owning a view key, or null when a core view is showing. */
export function moduleForView(view: string): LoadedModule | null {
  return MODULES.find((m) => m.section.nav.some((n) => n.key === view)) ?? null;
}

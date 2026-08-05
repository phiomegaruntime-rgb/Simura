import type { TwinEvent } from "../lib/events";
import { LEVEL_COLOR, LEVEL_ICON } from "../lib/status";

interface Props {
  events: TwinEvent[];
}

export default function EventLog({ events }: Props) {
  return (
    <div className="rounded-lg bg-surface border border-hairline p-4 flex flex-col min-h-0">
      <h3 className="text-sm font-semibold text-ink mb-3">Fault timeline</h3>
      {events.length === 0 ? (
        <p className="text-sm text-muted">No events yet — pack is nominal.</p>
      ) : (
        <ul className="flex flex-col gap-2 overflow-y-auto pr-1">
          {events.map((e) => (
            <li key={e.id} className="flex items-start gap-2.5 text-sm">
              <span
                className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                style={{ backgroundColor: LEVEL_COLOR[e.level], color: "#0d0d0d" }}
              >
                {LEVEL_ICON[e.level]}
              </span>
              <div className="min-w-0">
                <div className="text-ink-secondary">{e.message}</div>
                <div className="text-xs text-muted tnums">
                  {new Date(e.time).toLocaleTimeString([], { hour12: false })}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

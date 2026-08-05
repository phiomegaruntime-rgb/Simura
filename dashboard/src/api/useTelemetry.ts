import { useEffect, useRef, useState } from "react";
import { fetchHistory } from "./client";
import type {
  AnomalyPoint,
  AnomalyReport,
  AssessmentReport,
  TelemetryEnvelope,
  TrendPoint,
} from "./types";
import {
  deriveAnomalyEvents,
  deriveAssessmentEvents,
  deriveEvents,
  EventTracker,
  newTracker,
  TwinEvent,
} from "../lib/events";

const MAX_POINTS = 600; // rolling trend window
const MAX_EVENTS = 100;

export interface TelemetryState {
  connected: boolean;
  latest: TelemetryEnvelope | null;
  series: TrendPoint[];
  events: TwinEvent[];
  anomaly: AnomalyReport | null;
  anomalySeries: AnomalyPoint[];
  assessment: AssessmentReport | null;
}

/**
 * Subscribe to one system's live telemetry.
 *
 * Seeds the trend charts from REST history, then keeps them (and the live frame
 * and fault timeline) updated from the WebSocket. Reconnects automatically.
 */
export function useTelemetry(systemId: string | null): TelemetryState {
  const [connected, setConnected] = useState(false);
  const [latest, setLatest] = useState<TelemetryEnvelope | null>(null);
  const [series, setSeries] = useState<TrendPoint[]>([]);
  const [events, setEvents] = useState<TwinEvent[]>([]);
  const [anomaly, setAnomaly] = useState<AnomalyReport | null>(null);
  const [anomalySeries, setAnomalySeries] = useState<AnomalyPoint[]>([]);
  const [assessment, setAssessment] = useState<AssessmentReport | null>(null);
  const trackerRef = useRef<EventTracker>(newTracker());

  useEffect(() => {
    if (!systemId) return;

    let closed = false;
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;

    // Reset per-system state.
    setLatest(null);
    setSeries([]);
    setEvents([]);
    setAnomaly(null);
    setAnomalySeries([]);
    setAssessment(null);
    trackerRef.current = newTracker();

    fetchHistory(systemId)
      .then((points) => {
        if (!closed) setSeries(points);
      })
      .catch(() => {
        /* history is best-effort; live stream will fill in */
      });

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/systems/${encodeURIComponent(systemId)}`);

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws?.close();
      ws.onmessage = (ev) => {
        let env: any;
        try {
          env = JSON.parse(ev.data);
        } catch {
          return;
        }

        // The per-system socket carries two frame kinds; tell them apart by shape.
        if (env.anomaly) {
          const report: AnomalyReport = env.anomaly;
          const at = new Date(env.timestamp).getTime();
          setAnomaly(report);
          setAnomalySeries((prev) => {
            const point: AnomalyPoint = { t: at, maxScore: report.max_score };
            const next = prev.length && prev[prev.length - 1].t === at ? prev : [...prev, point];
            return next.length > MAX_POINTS ? next.slice(next.length - MAX_POINTS) : next;
          });
          const anomEvents = deriveAnomalyEvents(trackerRef.current, report, at);
          if (anomEvents.length) setEvents((prev) => [...anomEvents, ...prev].slice(0, MAX_EVENTS));
          return;
        }
        if (env.assessment) {
          const report: AssessmentReport = env.assessment;
          const at = new Date(env.timestamp).getTime();
          setAssessment(report);
          const asmtEvents = deriveAssessmentEvents(trackerRef.current, report, at);
          if (asmtEvents.length) setEvents((prev) => [...asmtEvents, ...prev].slice(0, MAX_EVENTS));
          return;
        }
        if (!env.telemetry) return;

        setLatest(env as TelemetryEnvelope);

        const tel = env.telemetry;
        const t = new Date(env.timestamp).getTime();
        setSeries((prev) => {
          const point: TrendPoint = {
            t,
            soc: tel.pack_soc * 100,
            maxTemp: tel.max_temp_c,
            power: tel.pack_power_w,
            voltage: tel.pack_voltage_v,
            imbalance: tel.voltage_imbalance_v,
          };
          const next = prev.length && prev[prev.length - 1].t === t ? prev : [...prev, point];
          return next.length > MAX_POINTS ? next.slice(next.length - MAX_POINTS) : next;
        });

        const newEvents = deriveEvents(trackerRef.current, tel, t);
        if (newEvents.length) {
          setEvents((prev) => [...newEvents, ...prev].slice(0, MAX_EVENTS));
        }
      };
    };

    connect();

    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, [systemId]);

  return { connected, latest, series, events, anomaly, anomalySeries, assessment };
}

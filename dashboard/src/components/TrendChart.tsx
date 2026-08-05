import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
interface Props {
  title: string;
  data: any[];
  dataKey: string;
  color: string;
  unit: string;
  domain?: [number | "auto", number | "auto"];
  precision?: number;
}

// A single-series area chart. One measure per chart (never a dual axis); the
// title names the series, so no legend is needed. Crosshair tooltip on hover.
export default function TrendChart({
  title,
  data,
  dataKey,
  color,
  unit,
  domain = ["auto", "auto"],
  precision = 1,
}: Props) {
  const gradId = `grad-${String(dataKey)}`;
  return (
    <div className="rounded-lg bg-surface border border-hairline p-4">
      <h3 className="text-sm font-semibold text-ink mb-2">{title}</h3>
      <div style={{ width: "100%", height: 150 }}>
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#2c2c2a" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(t) => new Date(t).toLocaleTimeString([], { hour12: false })}
              tick={{ fill: "#898781", fontSize: 11 }}
              stroke="#383835"
              minTickGap={40}
            />
            <YAxis
              domain={domain}
              tick={{ fill: "#898781", fontSize: 11 }}
              stroke="#383835"
              width={44}
              tickFormatter={(v) => v.toFixed(precision === 0 ? 0 : 0)}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#232322",
                border: "1px solid rgba(255,255,255,0.10)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "#898781" }}
              itemStyle={{ color: "#ffffff" }}
              labelFormatter={(t) => new Date(t as number).toLocaleTimeString([], { hour12: false })}
              formatter={(value: number) => [`${value.toFixed(precision)} ${unit}`, title]}
            />
            <Area
              type="monotone"
              dataKey={dataKey}
              stroke={color}
              strokeWidth={2}
              fill={`url(#${gradId})`}
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

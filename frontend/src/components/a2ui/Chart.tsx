"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, type DotItemDotProps } from "recharts";

import { ChartFrame } from "@/components/ui/ChartFrame";
import { useThemeColors } from "@/lib/useThemeColors";

export type ChartProps = {
  kind: "bar" | "line";
  title: string;
  points: unknown;
  x: string;
  series: { key: string; label: string }[];
  unit?: string;
};

type Row = Record<string, string | number | null>;

const COLORS = ["chart-1", "chart-2", "chart-3", "chart-4"] as const;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** A bar or line chart of a panel's data, with a table view (loaded lazily by Surface). */
export default function Chart({ kind, title, points, x, series, unit }: ChartProps) {
  const c = useThemeColors();
  if (!c) return null;
  const rows: Row[] = (Array.isArray(points) ? points : []).filter(isPlainObject).map((p) => ({
    [x]: String(p[x]),
    ...Object.fromEntries(series.map((s) => [s.key, finite(p[s.key])])),
  }));
  const colorOf = (n: number) => c[COLORS[n % COLORS.length]];
  const axisTick = { fill: c.muted, fontSize: 11 };
  const grid = <CartesianGrid stroke={c.line} strokeOpacity={0.5} vertical={false} />;
  const xAxis = <XAxis dataKey={x} tick={axisTick} axisLine={{ stroke: c.line }} tickLine={false} />;
  const yAxis = <YAxis domain={kind === "bar" ? [0, "auto"] : ["auto", "auto"]} tick={axisTick} axisLine={false} tickLine={false} />;
  const tooltip = (
    <Tooltip
      cursor={kind === "bar" ? { fill: c.line, fillOpacity: 0.25 } : { stroke: c.muted, strokeDasharray: "3 3" }}
      contentStyle={{ background: c.surface, border: `1px solid ${c.line}`, borderRadius: 4, color: c.fg, fontSize: 12 }}
      labelStyle={{ color: c.fg }}
      formatter={(value) => (unit ? `${String(value)} ${unit}` : String(value))}
    />
  );
  const margin = { top: 8, right: 16, bottom: 0, left: -16 };
  return (
    <div className="min-w-0 flex-[1_1_18rem]">
      <ChartFrame
        title={title}
        legend={series.length >= 2 ? series.map((s, n) => ({ label: s.label, color: colorOf(n) })) : []}
        table={{
          headers: [x, ...series.map((s) => (unit ? `${s.label} (${unit})` : s.label))],
          rows: rows.map((r) => [r[x] as string, ...series.map((s) => r[s.key] ?? "—")]),
        }}
      >
        {rows.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">No data to draw.</p>
        ) : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              {kind === "line" ? (
                <LineChart data={rows} margin={margin}>
                  {grid}
                  {xAxis}
                  {yAxis}
                  {tooltip}
                  {series.map((s, n) => (
                    <Line
                      key={s.key}
                      name={s.label}
                      type="monotone"
                      dataKey={s.key}
                      stroke={colorOf(n)}
                      strokeWidth={2}
                      connectNulls={false}
                      // a dot on the latest point only; the tooltip and table carry the rest
                      dot={(props: DotItemDotProps) =>
                        props.index === rows.length - 1 ? (
                          <circle key={props.key ?? undefined} cx={props.cx} cy={props.cy} r={3} fill={colorOf(n)} />
                        ) : (
                          <g key={props.key ?? undefined} />
                        )
                      }
                      isAnimationActive={false}
                    />
                  ))}
                </LineChart>
              ) : (
                <BarChart data={rows} margin={margin}>
                  {grid}
                  {xAxis}
                  {yAxis}
                  {tooltip}
                  {series.map((s, n) => (
                    <Bar key={s.key} name={s.label} dataKey={s.key} fill={colorOf(n)} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
                  ))}
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>
        )}
      </ChartFrame>
    </div>
  );
}

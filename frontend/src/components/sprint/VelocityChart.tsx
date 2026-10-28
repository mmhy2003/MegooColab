"use client";

import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { VelocityPoint } from "@/lib/types";
import { useThemeColors } from "@/lib/useThemeColors";

import { ChartFrame } from "./ChartFrame";

export function VelocityChart({ points }: { points: VelocityPoint[] }) {
  const c = useThemeColors();
  if (!c) return null;
  const last = points.length - 1;
  // direct-label only the latest sprint's bars; the tooltip and table carry the rest
  const latestOnly = (props: { index?: number; x?: number | string; y?: number | string; width?: number | string; value?: unknown }) =>
    props.index === last ? (
      <text x={Number(props.x) + Number(props.width) / 2} y={Number(props.y) - 6} textAnchor="middle" fontSize={11} fill={c.fg}>
        {String(props.value)}
      </text>
    ) : null;
  return (
    <ChartFrame
      title="Velocity"
      legend={[
        { label: "Committed", color: c["chart-2"] },
        { label: "Completed", color: c["chart-1"] },
      ]}
      table={{
        headers: ["Sprint", "Committed", "Completed"],
        rows: points.map((p) => [p.name, p.committed_points, p.completed_points]),
      }}
    >
      {points.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Velocity appears after the first completed sprint.</p>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={points} barGap={2} barCategoryGap="30%" margin={{ top: 20, right: 16, bottom: 0, left: -16 }}>
              <CartesianGrid stroke={c.line} strokeOpacity={0.5} vertical={false} />
              <XAxis dataKey="name" tick={{ fill: c.muted, fontSize: 11 }} axisLine={{ stroke: c.line }} tickLine={false} />
              <YAxis allowDecimals={false} tick={{ fill: c.muted, fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                cursor={{ fill: c.line, fillOpacity: 0.25 }}
                contentStyle={{ background: c.surface, border: `1px solid ${c.line}`, borderRadius: 4, color: c.fg, fontSize: 12 }}
                labelStyle={{ color: c.fg }}
              />
              <Bar name="Committed" dataKey="committed_points" fill={c["chart-2"]} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false}>
                <LabelList dataKey="committed_points" content={latestOnly} />
              </Bar>
              <Bar name="Completed" dataKey="completed_points" fill={c["chart-1"]} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false}>
                <LabelList dataKey="completed_points" content={latestOnly} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartFrame>
  );
}

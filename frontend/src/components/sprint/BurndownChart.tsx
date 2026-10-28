"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { BurndownPoint } from "@/lib/types";
import { useThemeColors } from "@/lib/useThemeColors";

import { ChartFrame } from "./ChartFrame";

function shortDay(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function BurndownChart({ points, sprintName }: { points: BurndownPoint[]; sprintName: string }) {
  const c = useThemeColors();
  if (!c) return null;
  const data = points.map((p) => ({ ...p, label: shortDay(p.day) }));
  return (
    <ChartFrame
      title={`Burndown · ${sprintName}`}
      legend={[
        { label: "Remaining points", color: c["chart-1"] },
        { label: "Ideal", color: c.muted, dashed: true },
      ]}
      table={{
        headers: ["Day", "Remaining", "Ideal"],
        rows: points.map((p) => [p.day, p.remaining_points, p.ideal_points]),
      }}
    >
      {points.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">The burndown starts once the sprint is active.</p>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
              <CartesianGrid stroke={c.line} strokeOpacity={0.5} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: c.muted, fontSize: 11 }} axisLine={{ stroke: c.line }} tickLine={false} />
              <YAxis allowDecimals={false} tick={{ fill: c.muted, fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                cursor={{ stroke: c.muted, strokeDasharray: "3 3" }}
                contentStyle={{ background: c.surface, border: `1px solid ${c.line}`, borderRadius: 4, color: c.fg, fontSize: 12 }}
                labelStyle={{ color: c.fg }}
              />
              <Line name="Ideal" type="linear" dataKey="ideal_points" stroke={c.muted} strokeWidth={2} strokeDasharray="5 4" dot={false} activeDot={false} isAnimationActive={false} />
              <Line
                name="Remaining"
                type="stepAfter"
                dataKey="remaining_points"
                stroke={c["chart-1"]}
                strokeWidth={2}
                dot={{ r: 4, fill: c["chart-1"], stroke: c.surface, strokeWidth: 2 }}
                activeDot={{ r: 5, stroke: c.surface, strokeWidth: 2 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartFrame>
  );
}

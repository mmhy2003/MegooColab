"use client";

import { useState } from "react";

/** Card with a title, a legend, and a "Show table" toggle so every chart has a text equivalent. */
export function ChartFrame({
  title,
  legend,
  table,
  children,
}: {
  title: string;
  legend: { label: string; color: string; dashed?: boolean }[];
  table: { headers: string[]; rows: (string | number)[][] };
  children: React.ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <section className="card space-y-3 p-4" aria-label={title}>
      <header className="flex flex-wrap items-center gap-4">
        <h2 className="text-sm text-fg">{title}</h2>
        <ul className="flex gap-3 text-xs text-muted-foreground" aria-label="Legend">
          {legend.map((l) => (
            <li key={l.label} className="flex items-center gap-1.5">
              <svg width="18" height="8" aria-hidden>
                <line x1="1" y1="4" x2="17" y2="4" stroke={l.color} strokeWidth="2" strokeLinecap="round" strokeDasharray={l.dashed ? "4 3" : undefined} />
              </svg>
              {l.label}
            </li>
          ))}
        </ul>
        <span className="flex-1" />
        <button type="button" className="text-xs text-cyan-ink" aria-pressed={showTable} onClick={() => setShowTable((v) => !v)}>
          {showTable ? "Show chart" : "Show table"}
        </button>
      </header>
      {showTable ? (
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr>{table.headers.map((h) => <th key={h} className="py-1 font-normal">{h}</th>)}</tr>
          </thead>
          <tbody>
            {table.rows.map((r, i) => (
              <tr key={i} className="border-t border-line">
                {r.map((c, j) => <td key={j} className="py-1">{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        children
      )}
    </section>
  );
}

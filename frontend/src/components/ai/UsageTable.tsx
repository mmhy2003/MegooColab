"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { AiUsageRow } from "@/lib/types";

const DAYS = 30;
const num = new Intl.NumberFormat("en-US");

function cost(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `$${v.toFixed(4)}`;
}

/** AI calls, tokens and cost per day, job and model (NFR-9). */
export function UsageTable() {
  const usage = useQuery({
    queryKey: qk.aiUsage(DAYS),
    queryFn: () => api<AiUsageRow[]>(`/api/admin/ai/usage?days=${DAYS}`),
  });
  const rows = usage.data ?? [];
  const priced = rows.filter((r) => r.cost_usd !== null && r.cost_usd !== undefined);
  const total = {
    calls: rows.reduce((n, r) => n + r.calls, 0),
    failures: rows.reduce((n, r) => n + r.failures, 0),
    input: rows.reduce((n, r) => n + r.input_tokens, 0),
    output: rows.reduce((n, r) => n + r.output_tokens, 0),
    cost: priced.length ? priced.reduce((n, r) => n + (r.cost_usd ?? 0), 0) : null,
  };
  return (
    <section className="card p-4">
      <h2 className="mb-1 font-display text-sm font-semibold tracking-wider uppercase">Usage, last {DAYS} days</h2>
      <p className="mb-3 text-xs text-muted">Cost is LiteLLM&apos;s estimate; “—” means the model has no known price.</p>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">No AI calls yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs tracking-wider text-muted uppercase">
              <tr>
                <th className="py-1 pr-3">Day</th>
                <th className="py-1 pr-3">Job</th>
                <th className="py-1 pr-3">Model</th>
                <th className="py-1 pr-3 text-right">Calls</th>
                <th className="py-1 pr-3 text-right">Failures</th>
                <th className="py-1 pr-3 text-right">Input tokens</th>
                <th className="py-1 pr-3 text-right">Output tokens</th>
                <th className="py-1 text-right">Cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((r) => (
                <tr key={`${r.day}-${r.job}-${r.model}`}>
                  <td className="py-1 pr-3 font-mono text-xs">{r.day}</td>
                  <td className="py-1 pr-3">{r.job}</td>
                  <td className="py-1 pr-3 font-mono text-xs break-all">{r.model}</td>
                  <td className="py-1 pr-3 text-right">{num.format(r.calls)}</td>
                  <td className={`py-1 pr-3 text-right ${r.failures ? "text-pink" : ""}`}>{num.format(r.failures)}</td>
                  <td className="py-1 pr-3 text-right">{num.format(r.input_tokens)}</td>
                  <td className="py-1 pr-3 text-right">{num.format(r.output_tokens)}</td>
                  <td className="py-1 text-right">{cost(r.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t-2 border-line font-semibold">
              <tr>
                <td className="py-1 pr-3" colSpan={3}>
                  Total
                </td>
                <td className="py-1 pr-3 text-right">{num.format(total.calls)}</td>
                <td className="py-1 pr-3 text-right">{num.format(total.failures)}</td>
                <td className="py-1 pr-3 text-right">{num.format(total.input)}</td>
                <td className="py-1 pr-3 text-right">{num.format(total.output)}</td>
                <td className="py-1 text-right">{cost(total.cost)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </section>
  );
}

"use client";

import { Bar, BarChart, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Adjustment, CompareResult } from "@/lib/api";
import { BUCKET_COLORS, inr, lakh, pct } from "@/lib/format";

/** Stable colour per bucket label so the same slice has the same colour everywhere. */
const BUCKET_ORDER = [
  "Take-home (fixed pay)",
  "Take-home (variable, post-tax)",
  "Income tax",
  "Employee PF",
  "Professional tax",
  "Employer PF + NPS",
  "Gratuity",
  "Insurance & benefits",
  "Variable not paid out",
  "Joining bonus (one-time)",
  "Retention bonus (conditional)",
  "ESOPs / RSUs",
  "Unallocated",
];
export const bucketColor = (label: string) => BUCKET_COLORS[Math.max(0, BUCKET_ORDER.indexOf(label)) % BUCKET_COLORS.length];

const tooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 14,
  fontSize: 12,
  fontWeight: 300,
  color: "var(--text)",
};

export function CtcDonut({ buckets, ctc }: { buckets: Adjustment[]; ctc: number }) {
  return (
    <div className="grid items-center gap-10 sm:grid-cols-[200px_minmax(0,1fr)] lg:grid-cols-1 xl:grid-cols-[200px_minmax(0,1fr)]">
      <div className="relative mx-auto h-[200px] w-[200px]">
        <ResponsiveContainer>
          <PieChart>
            <Pie data={buckets} dataKey="amount" nameKey="label" innerRadius={84} outerRadius={98} paddingAngle={1} stroke="none" isAnimationActive={false}>
              {buckets.map((b) => (
                <Cell key={b.label} fill={bucketColor(b.label)} />
              ))}
            </Pie>
            <Tooltip formatter={(v) => inr(Number(v))} contentStyle={tooltipStyle} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
          <div>
            <p className="eyebrow">CTC</p>
            <p className="serif mt-1 text-3xl">{lakh(ctc)}</p>
          </div>
        </div>
      </div>
      <ul className="min-w-0 divide-y divide-line text-sm">
        {buckets.map((b) => (
          <li key={b.label} className="flex items-center gap-3 py-2">
            <span className="size-2 shrink-0 rounded-full" style={{ background: bucketColor(b.label) }} />
            <span className="min-w-0 flex-1 truncate text-muted">{b.label}</span>
            <span className="tabular">{inr(b.amount)}</span>
            <span className="tabular w-11 text-right text-xs text-muted">{pct(b.amount / ctc)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function CompareStack({ data }: { data: CompareResult }) {
  const labels = BUCKET_ORDER.filter((l) => data.rows.some((r) => r.result.ctc_buckets.some((b) => b.label === l)));
  const rows = data.rows.map((r) => ({
    name: r.label.length > 22 ? r.label.slice(0, 21) + "…" : r.label,
    ...Object.fromEntries(r.result.ctc_buckets.map((b) => [b.label, b.amount])),
  }));
  return (
    <div className="h-[300px]">
      <ResponsiveContainer>
        <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16 }}>
          <XAxis type="number" tickFormatter={(v) => lakh(v)} stroke="#a1a1a6" fontSize={11} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey="name" width={150} stroke="#6e6e73" fontSize={12} tickLine={false} axisLine={false} />
          <Tooltip formatter={(v) => inr(Number(v))} contentStyle={tooltipStyle} cursor={{ fill: "rgba(139,147,167,0.12)" }} />
          <Legend iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 11, paddingTop: 16, color: "#6e6e73" }} />
          {labels.map((l) => (
            <Bar key={l} dataKey={l} stackId="ctc" fill={bucketColor(l)} barSize={28} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

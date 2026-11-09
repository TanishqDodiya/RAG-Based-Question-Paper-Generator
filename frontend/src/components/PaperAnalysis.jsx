import React, { useEffect, useRef, useState } from 'react';
import { BarChart3, Loader2, AlertCircle, Flag } from 'lucide-react';
import { fetchAnalytics } from '../services/api';

const COMPONENT_LABELS = {
  syllabus_coverage: 'Syllabus Coverage', source_grounding: 'Source Grounding',
  answer_support: 'Answer Support', bloom_distribution: 'Bloom Distribution',
  difficulty_balance: 'Difficulty Balance', question_diversity: 'Question Diversity',
};

function Bar({ pct }) {
  const v = Math.max(0, Math.min(100, pct || 0));
  const color = v >= 80 ? 'bg-emerald-500' : v >= 60 ? 'bg-amber-500' : 'bg-rose-500';
  return (
    <div className="h-2.5 rounded-full bg-slate-800 overflow-hidden min-w-[80px] flex-1">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${v}%` }} />
    </div>
  );
}

export default function PaperAnalysis({ paper, blueprint, validation, duplicates, qualityToken }) {
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const hasAnalyzed = useRef(false);
  const requestId = useRef(0);

  const runAnalysis = async () => {
    const id = requestId.current + 1;
    requestId.current = id;
    setError(null);
    setIsLoading(true);
    try {
      const res = await fetchAnalytics(paper, blueprint?.payload || null, validation, duplicates);
      if (id === requestId.current) {
        setData(res);
        hasAnalyzed.current = true;
      }
    } catch (err) {
      if (id === requestId.current) {
        setData(null);
        setError(err.message || 'Analytics failed.');
      }
    } finally {
      if (id === requestId.current) setIsLoading(false);
    }
  };

  // H-04: an edited/rejected paper must never keep analytics computed from the
  // previous content. Clear immediately when the paper object changes and
  // cancel any request that was started for the old content.
  useEffect(() => {
    requestId.current += 1;
    setData(null);
    setError(null);
    setIsLoading(false);
  }, [paper]);

  // H-04: App bumps qualityToken once revalidation + duplicate detection have
  // settled, so a previously opened analysis refreshes with the latest inputs.
  useEffect(() => {
    if (!hasAnalyzed.current) return;
    runAnalysis();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qualityToken]);

  if (!paper) return null;

  const handleAnalyze = runAnalysis;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-indigo-400" />
            Paper Analysis
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Target vs actual coverage + heuristic quality score (deterministic)
          </p>
        </div>
        <button
          onClick={handleAnalyze}
          disabled={isLoading}
          className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold shadow-lg transition-all flex items-center gap-2 disabled:opacity-50"
        >
          {isLoading ? (<><Loader2 className="w-4 h-4 animate-spin" /> Analyzing...</>) : (<><BarChart3 className="w-4 h-4" /> Analyze Paper</>)}
        </button>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs text-rose-300 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" /><span>{error}</span>
        </div>
      )}

      {data && (
        <div className="space-y-5 text-xs">
          {/* Quality score */}
          <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-slate-200 uppercase tracking-wider text-[11px]">Question Paper Quality</h3>
              {data.quality.overall !== null ? (
                <span className="text-2xl font-bold text-white">{data.quality.overall}%</span>
              ) : (
                <span className="text-slate-500 italic">Run validation + duplicate check first</span>
              )}
            </div>
            {data.quality.overall !== null && (
              <div className="space-y-2">
                {Object.entries(data.quality.components).map(([key, val]) => (
                  <div key={key} className="flex items-center gap-3">
                    <span className="w-36 shrink-0 text-slate-400">{COMPONENT_LABELS[key]}</span>
                    {val !== null ? (<><Bar pct={val} /><span className="w-12 text-right font-bold text-slate-200">{val}%</span></>) : (
                      <span className="text-slate-600 italic">needs input</span>)}
                  </div>
                ))}
                <div className="flex items-center gap-3 pt-1 text-slate-400">
                  <span className="w-36 shrink-0">Duplicate Risk</span>
                  <span className={`font-bold ${data.quality.duplicate_risk === 'Low' ? 'text-emerald-300' : data.quality.duplicate_risk === 'High' ? 'text-rose-300' : 'text-amber-300'}`}>
                    {data.quality.duplicate_risk} ({data.quality.duplicate_pairs} pairs)
                  </span>
                </div>
              </div>
            )}
            <p className="text-[11px] text-slate-500 italic">{data.quality.label}</p>
          </div>

          {/* Target vs actual */}
          {data.comparison ? (
            Object.entries(data.comparison).map(([axis, rows]) => (
              <div key={axis} className="space-y-2">
                <h3 className="font-bold text-slate-200 uppercase tracking-wider text-[11px] capitalize">{axis} — target vs actual</h3>
                <div className="space-y-1.5">
                  {rows.map((r, i) => (
                    <div key={i} className="flex items-center gap-3 p-2 rounded-lg bg-slate-950 border border-slate-800">
                      <span className="w-28 shrink-0 text-slate-300 font-medium truncate" title={r.label}>{r.label}</span>
                      <Bar pct={r.actual_pct} />
                      <span className="text-slate-400 whitespace-nowrap">T {r.target_pct}% · A {r.actual_pct}%</span>
                      {r.flagged && (
                        <span className="flex items-center gap-1 text-amber-300 font-bold whitespace-nowrap">
                          <Flag className="w-3 h-3" /> Δ{r.delta > 0 ? '+' : ''}{r.delta}%
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))
          ) : (
            <p className="text-slate-500 italic">Validate a blueprint to compare target vs actual distributions. Actual marks: {Object.entries(data.actual.units).map(([k, v]) => `${k} ${v}m`).join(' · ') || '—'}</p>
          )}
        </div>
      )}

      {!data && !error && (
        <p className="text-xs text-slate-500 italic">Analyze to see syllabus coverage, distribution deltas and the heuristic quality score.</p>
      )}
    </div>
  );
}

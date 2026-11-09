import React, { useEffect, useRef, useState } from 'react';
import { ShieldCheck, Loader2, AlertCircle, CheckCircle2, Eye } from 'lucide-react';
import { validatePaper } from '../services/api';

const CHECK_LABELS = {
  syllabus: 'Syllabus', grounding: 'Grounding', answer_support: 'Answer Support',
  difficulty: 'Difficulty', marks: 'Marks', bloom: 'Bloom Level',
  qtype: 'Question Type', quality: 'Quality',
};

function statusStyle(status) {
  if (status === 'PASS') return 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30';
  if (status === 'FAIL') return 'bg-rose-500/10 text-rose-300 border-rose-500/30';
  return 'bg-amber-500/10 text-amber-300 border-amber-500/30';
}

function overallStyle(overall) {
  if (overall === 'APPROVED') return 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10';
  if (overall === 'NEEDS_REGENERATION') return 'text-rose-300 border-rose-500/30 bg-rose-500/10';
  return 'text-amber-300 border-amber-500/30 bg-amber-500/10';
}

export default function ValidationPanel({ paper, validation, onValidation }) {
  const [isValidating, setIsValidating] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const requestId = useRef(0);

  // H-04: a manual validation started before an edit must not publish verdicts
  // for the previous paper content after the edit has landed.
  useEffect(() => {
    requestId.current += 1;
  }, [paper]);

  if (!paper) return null;

  // Defensive rendering: a malformed validation payload must not crash the UI.
  const summary = validation?.summary && typeof validation.summary === 'object'
    ? validation.summary
    : {};
  const results = Array.isArray(validation?.results) ? validation.results : [];

  const handleValidate = async () => {
    const id = requestId.current + 1;
    requestId.current = id;
    setError(null);
    setIsValidating(true);
    try {
      const data = await validatePaper(paper);
      if (id === requestId.current && onValidation) onValidation(data);
    } catch (err) {
      if (id === requestId.current) setError(err.message || 'Validation failed.');
    } finally {
      if (id === requestId.current) setIsValidating(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-indigo-400" />
            Question Validation
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Deterministic critic — every question checked against your material (no extra AI calls)
          </p>
        </div>
        <button
          onClick={handleValidate}
          disabled={isValidating}
          className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold shadow-lg transition-all flex items-center gap-2 disabled:opacity-50"
        >
          {isValidating ? (<><Loader2 className="w-4 h-4 animate-spin" /> Validating...</>) : (<><ShieldCheck className="w-4 h-4" /> Validate Paper</>)}
        </button>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs text-rose-300 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" /><span>{error}</span>
        </div>
      )}

      {validation && (
        <>
          <div className="grid grid-cols-4 gap-2 text-center text-xs">
            <div className="p-2.5 rounded-xl bg-slate-950 border border-slate-800">
              <div className="text-lg font-bold text-white">{summary.total ?? 0}</div>
              <div className="text-slate-500">Questions</div>
            </div>
            <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
              <div className="text-lg font-bold text-emerald-300">{summary.approved ?? 0}</div>
              <div className="text-emerald-400/70">Approved</div>
            </div>
            <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20">
              <div className="text-lg font-bold text-amber-300">{summary.needs_review ?? 0}</div>
              <div className="text-amber-400/70">Review</div>
            </div>
            <div className="p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/20">
              <div className="text-lg font-bold text-rose-300">{summary.needs_regeneration ?? 0}</div>
              <div className="text-rose-400/70">Regenerate</div>
            </div>
          </div>

          <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
            {results.map((r, idx) => (
              <div key={idx} className="p-3 rounded-xl bg-slate-950 border border-slate-800 text-xs space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-slate-200">{r.id}</span>
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold ${overallStyle(r.overall)}`}>
                      {r.overall === 'APPROVED' ? '✓ APPROVED' : r.overall === 'NEEDS_REGENERATION' ? '✗ NEEDS REGENERATION' : '⚠ NEEDS REVIEW'}
                    </span>
                    <button onClick={() => setExpanded(expanded === idx ? null : idx)}
                      className="text-slate-400 hover:text-white flex items-center gap-1">
                      <Eye className="w-3.5 h-3.5" /> {expanded === idx ? 'Hide' : 'Why?'}
                    </button>
                  </div>
                </div>
                {Array.isArray(r.reasons) && r.reasons.length > 0 && (
                  <div className="text-slate-400">{r.reasons.join(' ')}</div>
                )}
                {expanded === idx && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 pt-1">
                    {Object.entries(r.checks && typeof r.checks === 'object' ? r.checks : {}).map(([key, c]) => (
                      <div key={key} className={`px-2.5 py-1.5 rounded-lg border ${statusStyle(c?.status)}`}>
                        <span className="font-bold">{CHECK_LABELS[key] || key}: {c?.status}</span>
                        <span className="opacity-80"> — {c?.detail}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {!validation && !error && (
        <div className="text-xs text-slate-500 italic flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" /> Run validation to inspect grounding, Bloom match, marks fit and answer support per question.
        </div>
      )}
    </div>
  );
}

// Helper for M8 (single-question lookup without another API call).
export function findResultForQuestion(validation, qid) {
  const results = Array.isArray(validation?.results) ? validation.results : [];
  return results.find((result) => result.id === qid) || null;
}

import React, { useEffect, useRef, useState } from 'react';
import { Copy, Loader2, AlertCircle, CheckCircle2, RefreshCw, Trash2 } from 'lucide-react';
import { checkDuplicates, regenerateQuestion as regenerateQuestionApi } from '../services/api';
import {
  safeText, safeSections, safeQuestions,
  findQuestion, removeQuestionFromPaper, replaceQuestionInPaper,
  questionWithSlotDefaults,
} from '../utils/paperState.js';

function allQuestions(paper) {
  const out = [];
  safeSections(paper).forEach((section) => {
    safeQuestions(section).forEach((question) => out.push(question));
  });
  return out;
}

export default function DuplicatePanel({ paper, subject, onPaperChange, pairs, onPairs }) {
  const [dismissed, setDismissed] = useState([]);
  const [isChecking, setIsChecking] = useState(false);
  const [regenId, setRegenId] = useState(null);
  const [removingId, setRemovingId] = useState(null);
  const [error, setError] = useState(null);
  // H-04: an in-flight check/regeneration describes the paper it started with.
  // Never let its late response overwrite results for a newer paper.
  const paperRef = useRef(paper);
  paperRef.current = paper;
  const checkId = useRef(0);

  useEffect(() => {
    checkId.current += 1; // invalidate checks started for the previous paper
  }, [paper]);

  if (!paper) return null;

  const pairKey = (pair) => `${pair?.q1}↔${pair?.q2}`;
  const pairList = Array.isArray(pairs?.pairs) ? pairs.pairs : [];
  const visible = pairList.filter((pair) => !dismissed.includes(pairKey(pair)));

  const handleCheck = async () => {
    const id = checkId.current + 1;
    checkId.current = id;
    setError(null);
    setIsChecking(true);
    try {
      const data = await checkDuplicates(paper);
      if (id !== checkId.current) return;
      if (onPairs) onPairs(data);
      setDismissed([]);
    } catch (err) {
      if (id === checkId.current) setError(err.message || 'Duplicate check failed.');
    } finally {
      if (id === checkId.current) setIsChecking(false);
    }
  };

  const removeQuestion = async (qid) => {
    setError(null);
    setRemovingId(qid);
    try {
      const next = removeQuestionFromPaper(paper, qid);
      if (next === paper) throw new Error(`${qid} is no longer in the paper.`);
      if (onPaperChange) {
        const result = await onPaperChange(next);
        if (result?.errors?.length) setError(result.errors.join(' · '));
      }
      setDismissed([]);
    } catch (err) {
      setError(err.message || 'Remove failed.');
    } finally {
      setRemovingId(null);
    }
  };

  const regenQuestion = async (qid) => {
    const entry = findQuestion(paper, qid);
    if (!entry) {
      setError(`${qid} is no longer in the paper.`);
      return;
    }
    const sourcePaper = paper;
    setError(null);
    setRegenId(qid);
    try {
      const avoid = allQuestions(paper)
        .filter((question) => question.id !== qid)
        .map((question) => safeText(question.question))
        .filter(Boolean);
      const slotQuestion = questionWithSlotDefaults(entry.question, entry.section);
      const data = await regenerateQuestionApi(subject || safeText(paper.subject) || 'General', slotQuestion, avoid);
      // H-04: the teacher edited/rejected while this request was in flight;
      // the newer paper wins and this replacement is discarded.
      if (paperRef.current !== sourcePaper) return;
      const next = replaceQuestionInPaper(paper, qid, data.question);
      if (next === paper) throw new Error(`${qid} is no longer in the paper.`);
      if (onPaperChange) {
        const result = await onPaperChange(next);
        if (result?.errors?.length) setError(result.errors.join(' · '));
      }
      if (paperRef.current === sourcePaper) setDismissed([]);
    } catch (err) {
      if (paperRef.current === sourcePaper) setError(err.message || 'Regeneration failed.');
    } finally {
      setRegenId(null);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Copy className="w-5 h-5 text-indigo-400" />
            Duplicate Detection
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Semantic similarity over question texts (deterministic, offline) — threshold 75%
          </p>
        </div>
        <button
          onClick={handleCheck}
          disabled={isChecking}
          className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold shadow-lg transition-all flex items-center gap-2 disabled:opacity-50"
        >
          {isChecking ? (<><Loader2 className="w-4 h-4 animate-spin" /> Checking...</>) : (<><Copy className="w-4 h-4" /> Check Duplicates</>)}
        </button>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs text-rose-300 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" /><span>{error}</span>
        </div>
      )}

      {pairs && visible.length === 0 && (
        <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" /><span>No duplicates detected — all questions are distinct.</span>
        </div>
      )}

      {visible.length > 0 && (
        <div className="space-y-2">
          {visible.map((pair, idx) => (
            <div key={idx} className="p-3 rounded-xl bg-amber-500/5 border border-amber-500/20 text-xs space-y-2">
              <div className="font-bold text-amber-300">
                Possible duplicate — {safeText(pair?.q1, '?')} ↔ {safeText(pair?.q2, '?')} · Similarity {safeText(pair?.similarity_pct, '—')}%
              </div>
              <div className="flex flex-wrap gap-2">
                <button onClick={() => setDismissed([...dismissed, pairKey(pair)])}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-medium">
                  Keep both
                </button>
                <button onClick={() => removeQuestion(pair?.q1)} disabled={removingId !== null || regenId !== null}
                  className="px-3 py-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-600 text-rose-300 hover:text-white border border-rose-500/20 font-medium flex items-center gap-1 disabled:opacity-50">
                  {removingId === pair?.q1 ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />} Remove {safeText(pair?.q1, '?')}
                </button>
                <button onClick={() => removeQuestion(pair?.q2)} disabled={removingId !== null || regenId !== null}
                  className="px-3 py-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-600 text-rose-300 hover:text-white border border-rose-500/20 font-medium flex items-center gap-1 disabled:opacity-50">
                  {removingId === pair?.q2 ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />} Remove {safeText(pair?.q2, '?')}
                </button>
                <button onClick={() => regenQuestion(pair?.q2)} disabled={regenId !== null || removingId !== null}
                  className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold flex items-center gap-1 disabled:opacity-50">
                  {regenId === pair?.q2 ? (<Loader2 className="w-3.5 h-3.5 animate-spin" />) : (<RefreshCw className="w-3.5 h-3.5" />)}
                  Regenerate {safeText(pair?.q2, '?')}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {!pairs && !error && (
        <p className="text-xs text-slate-500 italic">Run the check to compare every question pair semantically.</p>
      )}
    </div>
  );
}

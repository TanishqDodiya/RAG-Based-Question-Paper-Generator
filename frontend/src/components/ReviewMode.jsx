import React, { useRef, useState } from 'react';
import { ClipboardCheck, Pencil, Trash2, RefreshCw, Loader2, AlertCircle, Check, X, FileText } from 'lucide-react';
import { regenerateQuestion } from '../services/api';
import { findResultForQuestion } from './ValidationPanel';
import {
  DIFFICULTY_VALUES, BLOOM_VALUES, QUESTION_TYPES,
  safeText, safeNumber, safeSections, safeQuestions,
  findQuestion, removeQuestionFromPaper, updateQuestionInPaper,
  replaceQuestionInPaper, questionDraft, buildQuestionPatch,
  validateQuestionDraft, questionWithSlotDefaults,
} from '../utils/paperState.js';

const DIFFS = DIFFICULTY_VALUES;
const BLOOMS = BLOOM_VALUES;
const TYPES = QUESTION_TYPES;

export default function ReviewMode({ paper, validation, subject, onPaperChange }) {
  const [decisions, setDecisions] = useState({});
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState(null);
  // M-03: rejection removes the question from the paper. Keep a session counter
  // so the header still tells the teacher how many were rejected.
  const [rejectedCount, setRejectedCount] = useState(0);
  // H-04: regeneration is slow; a late response must not replace a paper that
  // was edited/rejected in the meantime.
  const paperRef = useRef(paper);
  paperRef.current = paper;

  if (!paper) return null;

  const pushPaper = async (next) => {
    if (!onPaperChange) return { errors: [] };
    const result = await onPaperChange(next);
    if (result?.errors?.length) {
      setError(result.errors.join(' · '));
    }
    return result || { errors: [] };
  };

  const clearDecision = (qid) => {
    setDecisions((prev) => {
      if (!(qid in prev)) return prev;
      const next = { ...prev };
      delete next[qid];
      return next;
    });
  };

  const startEdit = (question, section) => {
    const nextDraft = questionDraft(question, section);
    if (nextDraft.type === 'MCQ') {
      const options = nextDraft.options.slice(0, 4);
      while (options.length < 4) options.push('');
      nextDraft.options = options;
    }
    setEditing(question.id);
    setDraft(nextDraft);
    setError(null);
  };

  const saveEdit = async (qid) => {
    setError(null);
    const check = validateQuestionDraft(draft);
    if (!check.ok) {
      setError(check.errors.join(' '));
      return;
    }
    setBusyId(qid);
    try {
      const patch = buildQuestionPatch(draft);
      const next = updateQuestionInPaper(paper, qid, patch);
      if (next === paper) throw new Error(`${qid} is no longer in the paper.`);
      clearDecision(qid);
      setEditing(null);
      await pushPaper(next);
    } catch (err) {
      setError(err.message || 'Save failed.');
    } finally {
      setBusyId(null);
    }
  };

  const removeQuestion = async (qid, { rejected = false } = {}) => {
    setError(null);
    setBusyId(qid);
    try {
      const next = removeQuestionFromPaper(paper, qid);
      if (next === paper) throw new Error(`${qid} is no longer in the paper.`);
      clearDecision(qid);
      if (rejected) setRejectedCount((count) => count + 1);
      await pushPaper(next);
    } catch (err) {
      setError(err.message || 'Remove failed.');
    } finally {
      setBusyId(null);
    }
  };

  const deleteQ = async (qid) => {
    if (!window.confirm(`Delete ${qid}?`)) return;
    await removeQuestion(qid);
  };

  const rejectQ = async (qid) => {
    if (!window.confirm(`Reject and remove ${qid} from the paper?`)) return;
    await removeQuestion(qid, { rejected: true });
  };

  const regenQ = async (qid) => {
    const entry = findQuestion(paper, qid);
    if (!entry) {
      setError(`${qid} is no longer in the paper.`);
      return;
    }
    const sourcePaper = paper;
    setBusyId(qid);
    setError(null);
    try {
      const avoid = [];
      safeSections(paper).forEach((section) => {
        safeQuestions(section).forEach((question) => {
          if (question.id !== qid) {
            const text = safeText(question.question);
            if (text) avoid.push(text);
          }
        });
      });
      const slotQuestion = questionWithSlotDefaults(entry.question, entry.section);
      const data = await regenerateQuestion(subject || safeText(paper.subject) || 'General', slotQuestion, avoid);
      if (paperRef.current !== sourcePaper) return;
      const next = replaceQuestionInPaper(paper, qid, data.question);
      if (next === paper) throw new Error(`${qid} is no longer in the paper.`);
      clearDecision(qid);
      await pushPaper(next);
    } catch (err) {
      if (paperRef.current === sourcePaper) setError(err.message || 'Regeneration failed.');
    } finally {
      setBusyId(null);
    }
  };

  const accepted = Object.values(decisions).filter((decision) => decision === 'accepted').length;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
      <div className="border-b border-slate-800 pb-4 flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <ClipboardCheck className="w-5 h-5 text-indigo-400" />
            Teacher Review
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Accept / reject / edit / regenerate — every change revalidates automatically
          </p>
        </div>
        <div className="text-xs flex items-center gap-2">
          <span className="px-2.5 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 font-bold">{accepted} accepted</span>
          <span className="px-2.5 py-1 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 font-bold">{rejectedCount} rejected</span>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs text-rose-300 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" /><span>{error}</span>
        </div>
      )}

      <div className="space-y-3 max-h-[32rem] overflow-y-auto pr-1">
        {safeSections(paper).map((sec, sIdx) => (
          <div key={sIdx} className="space-y-2">
            <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
              {safeText(sec.section_title) || `Section ${sIdx + 1}`} · {safeText(sec.type, 'Section')}
            </h3>
            {safeQuestions(sec).map((q, qIdx) => {
              const qid = safeText(q.id);
              const displayId = qid || `Q?${sIdx + 1}.${qIdx + 1}`;
              const canAct = qid.length > 0;
              const verdict = findResultForQuestion(validation, qid);
              const decision = decisions[qid];
              const isEditing = canAct && editing === qid;
              const busy = canAct && busyId === qid;
              const sources = Array.isArray(q.source_documents)
                ? q.source_documents.map((source) => safeText(source)).filter(Boolean)
                : [];
              return (
                <div key={qid || `${sIdx}-${qIdx}`} className={`p-3.5 rounded-xl border text-xs space-y-2.5 transition-colors ${
                  decision === 'accepted' ? 'bg-emerald-500/5 border-emerald-500/30'
                  : 'bg-slate-950 border-slate-800'}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1">
                      <span className="font-bold text-slate-100">{displayId}.</span>
                      {isEditing ? (
                        <textarea value={draft.question} onChange={(e) => setDraft({ ...draft, question: e.target.value })} rows={3}
                          className="w-full mt-1 px-3 py-2 rounded-lg bg-slate-900 border border-indigo-500 text-slate-100 focus:outline-none" />
                      ) : (
                        <span className="text-slate-200"> {safeText(q.question) || '[Question text unavailable]'}</span>
                      )}
                      <div className="flex flex-wrap gap-1.5 text-[10px] text-slate-400">
                        <span>{safeNumber(q.marks, 0)}m · {safeText(q.difficulty, '—')} · {safeText(q.bloom_level, '—')} · {safeText(q.unit, '—')}</span>
                        {sources.length > 0 && (
                          <span className="flex items-center gap-1" title={sources.join(', ')}>
                            <FileText className="w-3 h-3" /> {sources.join(', ')}
                          </span>
                        )}
                        {verdict && (
                          <span className={`font-bold ${verdict.overall === 'APPROVED' ? 'text-emerald-400' : verdict.overall === 'NEEDS_REGENERATION' ? 'text-rose-400' : 'text-amber-400'}`}>
                            · {verdict.overall}
                          </span>
                        )}
                      </div>
                      {isEditing && (
                        <div className="space-y-2 pt-1">
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                            <label className="space-y-1">Marks<input type="number" min="1" value={draft.marks} onChange={(e) => setDraft({ ...draft, marks: e.target.value })}
                              className="w-full px-2 py-1 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 text-center" /></label>
                            <label className="space-y-1">Difficulty<select value={draft.difficulty} onChange={(e) => setDraft({ ...draft, difficulty: e.target.value })}
                              className="w-full px-2 py-1 rounded-lg bg-slate-900 border border-slate-700 text-slate-200">{DIFFS.map((d) => <option key={d} value={d}>{d}</option>)}</select></label>
                            <label className="space-y-1">Bloom<select value={draft.bloom_level} onChange={(e) => setDraft({ ...draft, bloom_level: e.target.value })}
                              className="w-full px-2 py-1 rounded-lg bg-slate-900 border border-slate-700 text-slate-200">{BLOOMS.map((b) => <option key={b} value={b}>{b}</option>)}</select></label>
                            <label className="space-y-1">Type<select value={draft.type} onChange={(e) => {
                              const type = e.target.value;
                              const options = type === 'MCQ' ? [...(draft.options || [])] : [];
                              while (type === 'MCQ' && options.length < 4) options.push('');
                              setDraft({ ...draft, type, options });
                            }}
                              className="w-full px-2 py-1 rounded-lg bg-slate-900 border border-slate-700 text-slate-200">{TYPES.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
                          </div>
                          <label className="block space-y-1">Answer
                            <textarea value={draft.answer} onChange={(e) => setDraft({ ...draft, answer: e.target.value })} rows={2}
                              className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200" />
                          </label>
                          {draft.type === 'MCQ' && (
                            <div className="space-y-1">
                              <span className="text-slate-400">Options (exactly 4)</span>
                              {[0, 1, 2, 3].map((index) => (
                                <input key={index} type="text" value={(draft.options || [])[index] || ''}
                                  onChange={(e) => {
                                    const options = [...(draft.options || [])];
                                    while (options.length < 4) options.push('');
                                    options[index] = e.target.value;
                                    setDraft({ ...draft, options });
                                  }}
                                  placeholder={`Option ${String.fromCharCode(65 + index)}`}
                                  className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200" />
                              ))}
                            </div>
                          )}
                          <label className="block space-y-1">Explanation
                            <textarea value={draft.explanation} onChange={(e) => setDraft({ ...draft, explanation: e.target.value })} rows={2}
                              className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200" />
                          </label>
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {isEditing ? (
                      <>
                        <button onClick={() => saveEdit(qid)} disabled={busy}
                          className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold flex items-center gap-1 disabled:opacity-50">
                          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />} Save + revalidate
                        </button>
                        <button onClick={() => setEditing(null)} className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700">Cancel</button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => setDecisions({ ...decisions, [qid]: decision === 'accepted' ? null : 'accepted' })}
                          disabled={!canAct}
                          className={`px-3 py-1.5 rounded-lg font-bold flex items-center gap-1 border disabled:opacity-40 ${decision === 'accepted' ? 'bg-emerald-600 text-white border-emerald-600' : 'bg-slate-800 text-emerald-300 border-slate-700 hover:bg-slate-700'}`}>
                          <Check className="w-3.5 h-3.5" /> Accept
                        </button>
                        <button onClick={() => rejectQ(qid)} disabled={busy || !canAct}
                          title="Reject removes this question from the paper and refreshes totals"
                          className="px-3 py-1.5 rounded-lg bg-slate-800 text-rose-300 border border-slate-700 hover:bg-rose-600 hover:text-white font-bold flex items-center gap-1 disabled:opacity-40">
                          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <X className="w-3.5 h-3.5" />} Reject
                        </button>
                        <button onClick={() => startEdit(q, sec)} disabled={!canAct}
                          className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center gap-1 disabled:opacity-40">
                          <Pencil className="w-3.5 h-3.5" /> Edit
                        </button>
                        <button onClick={() => regenQ(qid)} disabled={busy || !canAct}
                          className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold flex items-center gap-1 disabled:opacity-50">
                          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />} Regenerate
                        </button>
                        <button onClick={() => deleteQ(qid)} disabled={busy || !canAct}
                          className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-rose-600 text-slate-400 hover:text-white border border-slate-700 flex items-center gap-1 disabled:opacity-40">
                          <Trash2 className="w-3.5 h-3.5" /> Delete
                        </button>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

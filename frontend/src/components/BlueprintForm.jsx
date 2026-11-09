import React, { useEffect, useRef, useState } from 'react';
import { ClipboardList, Plus, Trash2, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { validateBlueprint } from '../services/api';
import { blueprintFormState } from '../utils/blueprintState.js';

const BLOOM_KEYS = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'];
const BLOOM_LABELS = { remember: 'Remember', understand: 'Understand', apply: 'Apply', analyze: 'Analyze', evaluate: 'Evaluate', create: 'Create' };
const QTYPE_OPTIONS = ['MCQ', 'Short', 'Long', 'True/False', 'Fill-in-blanks'];

export default function BlueprintForm({ onValidated, onInvalid, activeBlueprint, restoreToken = 0 }) {
  const [examName, setExamName] = useState('Mid-Semester Examination');
  const [institution, setInstitution] = useState('');
  const [subject, setSubject] = useState('Operating Systems');
  const [totalMarks, setTotalMarks] = useState(30);
  const [duration, setDuration] = useState(120);
  const [topics, setTopics] = useState([
    { name: 'Unit 1', percentage: 20 },
    { name: 'Unit 2', percentage: 20 },
    { name: 'Unit 3', percentage: 25 },
    { name: 'Unit 4', percentage: 20 },
    { name: 'Unit 5', percentage: 15 },
  ]);
  const [difficulty, setDifficulty] = useState({ easy: 30, medium: 50, hard: 20 });
  const [types, setTypes] = useState([
    { type: 'MCQ', marks: 5 },
    { type: 'Short', marks: 15 },
    { type: 'Long', marks: 10 },
  ]);
  const [bloom, setBloom] = useState({ remember: 15, understand: 25, apply: 25, analyze: 15, evaluate: 10, create: 10 });
  // Header-only exam details for the Symbiosis paper layout (blanks render when empty).
  const [examMeta, setExamMeta] = useState({ exam_type: 'mid', programme: '', semester: '', batch: '', course_code: '', exam_date: '', day: '', time_slot: '' });
  const setMeta = (k, v) => setExamMeta((m) => ({ ...m, [k]: v }));
  const [isValidating, setIsValidating] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  // M-04: hydrate the form only when App explicitly restores a snapshot (or
  // when the component mounts with an already-active blueprint). A successful
  // validation from this form must not overwrite the inputs/result box.
  const lastHydratedToken = useRef(null);

  useEffect(() => {
    if (lastHydratedToken.current === restoreToken) return;
    lastHydratedToken.current = restoreToken;
    // H-05/M-04: a restore either hydrates the saved structured blueprint or,
    // for legacy/invalid snapshots, resets to the form defaults. The previous
    // paper's blueprint fields must never look like the newly loaded one.
    const next = blueprintFormState(
      activeBlueprint?.payload || null,
      activeBlueprint?.exam_meta || null,
    );
    setExamName(next.examName);
    setInstitution(next.institution);
    setSubject(next.subject);
    setTotalMarks(next.totalMarks);
    setDuration(next.duration);
    setTopics(next.topics);
    setDifficulty(next.difficulty);
    setTypes(next.types);
    setBloom(next.bloom);
    setExamMeta(next.examMeta);
    setResult(null);
    setError(null);
  }, [activeBlueprint, restoreToken]);

  // Live local sums (instant feedback before backend call)
  const topicSum = topics.reduce((s, t) => s + (parseFloat(t.percentage) || 0), 0);
  const diffSum = (parseFloat(difficulty.easy) || 0) + (parseFloat(difficulty.medium) || 0) + (parseFloat(difficulty.hard) || 0);
  const bloomSum = BLOOM_KEYS.reduce((s, k) => s + (parseFloat(bloom[k]) || 0), 0);
  const typeSum = types.reduce((s, t) => s + (parseInt(t.marks) || 0), 0);
  const pctOk = (v) => Math.abs(v - 100) <= 1.0;

  const updateTopic = (idx, field, value) => {
    const next = [...topics];
    next[idx] = { ...next[idx], [field]: field === 'name' ? value : Math.max(0, parseFloat(value) || 0) };
    setTopics(next);
  };
  const addTopic = () => setTopics([...topics, { name: `Unit ${topics.length + 1}`, percentage: 0 }]);
  const removeTopic = (idx) => { if (topics.length > 1) setTopics(topics.filter((_, i) => i !== idx)); };

  const updateType = (idx, field, value) => {
    const next = [...types];
    next[idx] = { ...next[idx], [field]: field === 'type' ? value : Math.max(1, parseInt(value) || 1) };
    setTypes(next);
  };
  const addType = () => setTypes([...types, { type: 'MCQ', marks: 5 }]);
  const removeType = (idx) => { if (types.length > 1) setTypes(types.filter((_, i) => i !== idx)); };

  const handleValidate = async () => {
    setError(null);
    setResult(null);
    // H-12: a re-validation must not leave the previous blueprint active while
    // the request is in flight (or after it fails).
    if (onInvalid) onInvalid();
    setIsValidating(true);
    const payload = {
      subject: subject.trim(),
      exam_name: examName.trim() || 'Mid-Semester Examination',
      institution: institution.trim() || null,
      total_marks: parseInt(totalMarks) || 0,
      duration_minutes: parseInt(duration) || 0,
      topics: topics.map((t) => ({ name: t.name.trim(), percentage: parseFloat(t.percentage) || 0 })),
      difficulty: { easy: parseFloat(difficulty.easy) || 0, medium: parseFloat(difficulty.medium) || 0, hard: parseFloat(difficulty.hard) || 0 },
      types: types.map((t) => ({ type: t.type, marks: parseInt(t.marks) || 0 })),
      bloom: Object.fromEntries(BLOOM_KEYS.map((k) => [k, parseFloat(bloom[k]) || 0])),
    };
    const meta = Object.fromEntries(Object.entries(examMeta).map(([k, v]) => [
      k,
      typeof v === 'string' ? v.trim() : String(v ?? '').trim(),
    ]));
    try {
      const data = await validateBlueprint(payload);
      setResult(data);
      if (onValidated) onValidated({ payload, expanded: data.expanded, exam_meta: meta });
    } catch (err) {
      setError(err.message || 'Blueprint validation failed.');
      if (onInvalid) onInvalid();
    } finally {
      setIsValidating(false);
    }
  };

  const sumBadge = (sum, okLabel = 'sums to 100') =>
    pctOk(sum) ? (
      <span className="text-emerald-400 font-bold">Σ {sum.toFixed(0)}% ✓ {okLabel}</span>
    ) : (
      <span className="text-amber-400 font-bold">Σ {sum.toFixed(1)}% — must sum to 100</span>
    );

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
      <div className="border-b border-slate-800 pb-4">
        <h2 className="text-lg font-bold text-white flex items-center gap-2">
          <ClipboardList className="w-5 h-5 text-indigo-400" />
          Exam Blueprint
        </h2>
        <p className="text-xs text-slate-400 mt-0.5">
          Define target distributions first — generation (Milestone 4) will follow this plan
        </p>
      </div>

      {/* Basic settings */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-slate-300">Subject</label>
          <input type="text" value={subject} onChange={(e) => setSubject(e.target.value)}
            className="w-full px-3.5 py-2 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm focus:outline-none focus:border-indigo-500" />
        </div>
        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-slate-300">Exam Name</label>
          <input type="text" value={examName} onChange={(e) => setExamName(e.target.value)}
            className="w-full px-3.5 py-2 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm focus:outline-none focus:border-indigo-500" />
        </div>
        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-slate-300">Institution (optional)</label>
          <input type="text" value={institution} onChange={(e) => setInstitution(e.target.value)} placeholder="e.g. PCCOE, Pune"
            className="w-full px-3.5 py-2 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm focus:outline-none focus:border-indigo-500" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-300">Total Marks</label>
            <input type="number" min="1" max="1000" value={totalMarks} onChange={(e) => setTotalMarks(e.target.value)}
              className="w-full px-3.5 py-2 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm text-center focus:outline-none focus:border-indigo-500" />
          </div>
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-300">Duration (min)</label>
            <input type="number" min="15" max="600" value={duration} onChange={(e) => setDuration(e.target.value)}
              className="w-full px-3.5 py-2 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm text-center focus:outline-none focus:border-indigo-500" />
          </div>
        </div>
      </div>

      {/* Header-only exam details (printed on the Symbiosis header; blanks when empty) */}
      <div className="space-y-3">
        <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
          Exam Details for Paper Header <span className="text-slate-500 normal-case">(optional — blank fields print as empty lines)</span>
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="space-y-1">
            <span className="block text-xs text-slate-400">Examination Type</span>
            <select value={examMeta.exam_type} onChange={(e) => setMeta('exam_type', e.target.value)}
              className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-200 text-xs focus:outline-none focus:border-indigo-500">
              <option value="mid">Mid-Semester Examination</option>
              <option value="end">End-Semester Examination</option>
            </select>
          </label>
          {[
            ['programme', 'Programme (e.g. B.Tech CSE)'],
            ['semester', 'Semester (e.g. III)'],
            ['batch', 'Batch (e.g. 2023-27)'],
            ['course_code', 'Course Code (e.g. 0705210303)'],
            ['exam_date', 'Date (e.g. 02/12/2025)'],
            ['day', 'Day (e.g. Tuesday)'],
            ['time_slot', 'Time (e.g. 10:00 - 11:30)'],
          ].map(([k, ph]) => (
            <input key={k} type="text" value={examMeta[k]} onChange={(e) => setMeta(k, e.target.value)} placeholder={ph}
              className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-200 text-xs focus:outline-none focus:border-indigo-500" />
          ))}
        </div>
      </div>

      {/* Topic distribution */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
            Topic / Unit Distribution &nbsp;{sumBadge(topicSum)}
          </label>
          <button type="button" onClick={addTopic}
            className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-indigo-400 text-xs font-medium border border-slate-700 flex items-center gap-1">
            <Plus className="w-3.5 h-3.5" /> Add Unit
          </button>
        </div>
        <div className="space-y-2">
          {topics.map((t, idx) => (
            <div key={idx} className="grid grid-cols-12 gap-2 items-center p-2.5 rounded-xl bg-slate-950/80 border border-slate-800/80 text-xs">
              <input type="text" value={t.name} onChange={(e) => updateTopic(idx, 'name', e.target.value)}
                className="col-span-7 px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 focus:outline-none focus:border-indigo-500" />
              <div className="col-span-4 flex items-center gap-1.5">
                <input type="number" min="0" max="100" value={t.percentage} onChange={(e) => updateTopic(idx, 'percentage', e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 text-center focus:outline-none focus:border-indigo-500" />
                <span className="text-slate-500">%</span>
              </div>
              <div className="col-span-1 text-right">
                <button type="button" onClick={() => removeTopic(idx)} disabled={topics.length <= 1}
                  className="p-1.5 text-slate-500 hover:text-rose-400 disabled:opacity-30">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Difficulty distribution */}
      <div className="space-y-3">
        <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
          Difficulty Distribution &nbsp;{sumBadge(diffSum)}
        </label>
        <div className="grid grid-cols-3 gap-3">
          {['easy', 'medium', 'hard'].map((k) => (
            <div key={k} className="space-y-1.5">
              <label className="block text-xs text-slate-400 capitalize">{k} (%)</label>
              <input type="number" min="0" max="100" value={difficulty[k]}
                onChange={(e) => setDifficulty({ ...difficulty, [k]: Math.max(0, parseFloat(e.target.value) || 0) })}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-100 text-sm text-center focus:outline-none focus:border-indigo-500" />
            </div>
          ))}
        </div>
      </div>

            {/* Question-type marks */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
            Question-Type Marks &nbsp;
            {parseInt(typeSum) === parseInt(totalMarks || 0) ? (
              <span className="text-emerald-400 font-bold">Σ {typeSum} = {totalMarks} ✓</span>
            ) : (
              <span className="text-amber-400 font-bold">Σ {typeSum} — must equal {totalMarks}</span>
            )}
          </label>
          <button type="button" onClick={addType}
            className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-indigo-400 text-xs font-medium border border-slate-700 flex items-center gap-1">
            <Plus className="w-3.5 h-3.5" /> Add Type
          </button>
        </div>
        <div className="space-y-2">
          {types.map((t, idx) => (
            <div key={idx} className="grid grid-cols-12 gap-2 items-center p-2.5 rounded-xl bg-slate-950/80 border border-slate-800/80 text-xs">
              <select value={t.type} onChange={(e) => updateType(idx, 'type', e.target.value)}
                className="col-span-7 px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 focus:outline-none focus:border-indigo-500">
                {QTYPE_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
              <div className="col-span-4 flex items-center gap-1.5">
                <input type="number" min="1" value={t.marks} onChange={(e) => updateType(idx, 'marks', e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 text-center focus:outline-none focus:border-indigo-500" />
                <span className="text-slate-500">marks</span>
              </div>
              <div className="col-span-1 text-right">
                <button type="button" onClick={() => removeType(idx)} disabled={types.length <= 1}
                  className="p-1.5 text-slate-500 hover:text-rose-400 disabled:opacity-30">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
        {/* FIX 4: documents the division of responsibility — sections own counts,
            blueprint type-marks are the analytics target. */}
        <p className="text-[11px] text-slate-500 italic">
          Note: the section configuration controls the actual number and type of generated
          questions. This type-mark distribution is the target used for analytics validation.
        </p>
      </div>

      {/* Bloom distribution */}
      <div className="space-y-3">
        <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
          Bloom&apos;s Taxonomy Distribution &nbsp;{sumBadge(bloomSum)}
        </label>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {BLOOM_KEYS.map((k) => (
            <div key={k} className="space-y-1.5">
              <label className="block text-xs text-slate-400">{BLOOM_LABELS[k]} (%)</label>
              <input type="number" min="0" max="100" value={bloom[k]}
                onChange={(e) => setBloom({ ...bloom, [k]: Math.max(0, parseFloat(e.target.value) || 0) })}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-100 text-sm text-center focus:outline-none focus:border-indigo-500" />
            </div>
          ))}
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-xs text-rose-200 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div><span className="font-bold text-rose-300 block mb-0.5">Blueprint Invalid</span><span>{error}</span></div>
        </div>
      )}

      {result?.ok && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-200 space-y-2">
          <div className="flex items-center gap-2 font-bold text-emerald-300">
            <CheckCircle2 className="w-4 h-4" /> Blueprint Valid — marks breakdown
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
            <div>Topics: {result.expanded.topics.map((t) => `${t.name} ${t.marks}m`).join(' · ')}</div>
            <div>Difficulty: {result.expanded.difficulty.map((t) => `${t.level} ${t.marks}m`).join(' · ')}</div>
            <div>Types: {result.expanded.types.map((t) => `${t.type} ${t.marks}m`).join(' · ')}</div>
            <div>Bloom: {result.expanded.bloom.filter((t) => t.marks > 0).map((t) => `${t.level} ${t.marks}m`).join(' · ')}</div>
          </div>
        </div>
      )}

      <button type="button" onClick={handleValidate} disabled={isValidating}
        className="w-full py-3 px-6 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold text-sm shadow-xl transition-all flex items-center justify-center gap-2 disabled:opacity-50">
        {isValidating ? (<><Loader2 className="w-5 h-5 animate-spin" /> Validating Blueprint...</>) : (<><CheckCircle2 className="w-5 h-5" /> Validate Blueprint</>)}
      </button>
    </div>
  );
}

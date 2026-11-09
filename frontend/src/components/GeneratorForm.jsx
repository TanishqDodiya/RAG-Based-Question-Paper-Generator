import React, { useEffect, useState } from 'react';
import { Sliders, Plus, Trash2, Sparkles, Loader2, Award, FileQuestion, AlertCircle, UploadCloud } from 'lucide-react';
import { generatePaper, generateStructured } from '../services/api';
import { safeText, sectionsFromPaper } from '../utils/paperState.js';

export default function GeneratorForm({ onPaperGenerated, isOllamaConnected, onRefreshStatus, docCount, blueprint, paper, paperIdentity = 0 }) {
  const [subject, setSubject] = useState('Operating Systems');
  const [difficulty, setDifficulty] = useState('Medium');
  const [sections, setSections] = useState([
    { type: 'MCQ', count: 5, marks_per_q: 1 },
    { type: 'Short', count: 3, marks_per_q: 5 },
    { type: 'Long', count: 1, marks_per_q: 10 }
  ]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState(null);

  // H-05: a reopened snapshot restores the subject and the actual section
  // distribution. Keyed by paper identity so review edits do not overwrite
  // configuration the teacher is currently editing.
  useEffect(() => {
    if (!paper || typeof paper !== 'object') return;
    const restoredSections = sectionsFromPaper(paper);
    if (restoredSections.length > 0) setSections(restoredSections);
    const restoredSubject = safeText(paper.subject).trim();
    if (restoredSubject) setSubject(restoredSubject);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperIdentity]);

  // Compute calculated total marks dynamically
  const calculatedTotalMarks = sections.reduce(
    (sum, sec) => sum + (parseInt(sec.count) || 0) * (parseInt(sec.marks_per_q) || 0),
    0
  );

  const addSection = () => {
    setSections([...sections, { type: 'MCQ', count: 5, marks_per_q: 1 }]);
  };

  const removeSection = (index) => {
    if (sections.length <= 1) return;
    setSections(sections.filter((_, i) => i !== index));
  };

  const updateSection = (index, field, value) => {
    const updated = [...sections];
    updated[index][field] = field === 'type' ? value : Math.max(1, parseInt(value) || 1);
    setSections(updated);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    if (onRefreshStatus) {
      await onRefreshStatus();
    }

    if (!subject.trim()) {
      setError('Please enter a valid subject or topic name.');
      return;
    }

    if (docCount === 0) {
      setError('No study material is available yet for this session. Please upload valid notes, PDF, PPT, or reference material before generating a question paper.');
      return;
    }

    setIsGenerating(true);

    // M4: blueprint-aware path — same sections, plus validated blueprint for
    // per-question unit/difficulty/Bloom assignment + source traceability.
    const useStructured = blueprint?.payload && blueprint?.expanded;
    // Header-only metadata for the Symbiosis layout (never affects generation).
    const examMeta = blueprint?.exam_meta || undefined;

    const payload = useStructured
      ? {
          subject: subject.trim(),
          total_marks: calculatedTotalMarks,
          difficulty,
          sections,
          exam_name: blueprint.payload.exam_name,
          institution: blueprint.payload.institution,
          duration_minutes: blueprint.payload.duration_minutes,
          blueprint: blueprint.payload,
          ...(examMeta ? { exam_meta: examMeta } : {}),
        }
      : {
          subject: subject.trim(),
          total_marks: calculatedTotalMarks,
          difficulty,
          sections,
          ...(examMeta ? { exam_meta: examMeta } : {}),
        };

    try {
      const generatedData = useStructured
        ? await generateStructured(payload)
        : await generatePaper(payload);
      onPaperGenerated(generatedData);
    } catch (err) {
      console.error('Generation error:', err);
      setError(err.message || 'Failed to generate question paper.');
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
      
      {/* Form Header */}
      <div className="border-b border-slate-800 pb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Sliders className="w-5 h-5 text-indigo-400" />
            Exam Paper Configuration
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Configure question types, mark weightages, and difficulty level
            {blueprint?.expanded ? (
              <span className="text-emerald-400 font-medium"> · Blueprint-linked (structured generation with per-question metadata)</span>
            ) : (
              <span className="text-slate-500"> · Validate a blueprint above for metadata-rich generation</span>
            )}
          </p>
        </div>

        <div className="px-3 py-1.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 font-bold text-xs flex items-center gap-1.5">
          <Award className="w-4 h-4" />
          <span>Total Marks: {calculatedTotalMarks}</span>
        </div>
      </div>

      {/* Basic Controls Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Subject Title Input */}
        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-slate-300">
            Subject / Topic Name
          </label>
          <input
            type="text"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="e.g. Data Structures, Physics, World History"
            required
            className="w-full px-3.5 py-2 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm focus:outline-none focus:border-indigo-500 transition-colors"
          />
        </div>

        {/* Difficulty Dropdown */}
        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-slate-300">
            Difficulty Level
          </label>
          <select
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value)}
            className="w-full px-3.5 py-2 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm focus:outline-none focus:border-indigo-500 transition-colors"
          >
            <option value="Easy">Easy (Conceptual & Basic)</option>
            <option value="Medium">Medium (Balanced Standards)</option>
            <option value="Hard">Hard (Analytical & Complex)</option>
          </select>
        </div>
      </div>

      {/* Question Sections Breakdown Manager */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider">
            Sections Breakdown & Marks Allocation
          </label>
          <button
            type="button"
            onClick={addSection}
            className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-indigo-400 hover:text-white text-xs font-medium border border-slate-700 transition-colors flex items-center gap-1"
          >
            <Plus className="w-3.5 h-3.5" />
            Add Section
          </button>
        </div>

        <div className="space-y-2.5">
          {sections.map((sec, idx) => (
            <div
              key={idx}
              className="grid grid-cols-12 gap-2 items-center p-3 rounded-xl bg-slate-950/80 border border-slate-800/80 text-xs"
            >
              {/* Question Type */}
              <div className="col-span-5 sm:col-span-4">
                <select
                  value={sec.type}
                  onChange={(e) => updateSection(idx, 'type', e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  <option value="MCQ">MCQ (Multiple Choice)</option>
                  <option value="Short">Short Answer</option>
                  <option value="Long">Long Answer</option>
                  <option value="True/False">True / False</option>
                  <option value="Fill-in-blanks">Fill in the Blanks</option>
                </select>
              </div>

              {/* Count */}
              <div className="col-span-3 sm:col-span-3 flex items-center gap-1.5">
                <span className="text-slate-400 hidden sm:inline">Qty:</span>
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={sec.count}
                  onChange={(e) => updateSection(idx, 'count', e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 text-center focus:outline-none focus:border-indigo-500"
                />
              </div>

              {/* Marks per Question */}
              <div className="col-span-3 sm:col-span-4 flex items-center gap-1.5">
                <span className="text-slate-400 hidden sm:inline">Marks/q:</span>
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={sec.marks_per_q}
                  onChange={(e) => updateSection(idx, 'marks_per_q', e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 text-center focus:outline-none focus:border-indigo-500"
                />
                <span className="text-indigo-400 font-bold text-xs shrink-0">
                  = {sec.count * sec.marks_per_q}m
                </span>
              </div>

              {/* Delete Button */}
              <div className="col-span-1 text-right">
                <button
                  type="button"
                  onClick={() => removeSection(idx)}
                  disabled={sections.length <= 1}
                  className="p-1.5 text-slate-500 hover:text-rose-400 disabled:opacity-30 transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Warning if no documents uploaded */}
      {docCount === 0 && (
        <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-300 flex items-center gap-2.5">
          <UploadCloud className="w-4 h-4 text-amber-400 shrink-0" />
          <span>
            No study material uploaded yet. Please click <strong>"2. Reference Notes & RAG Store"</strong> above to upload notes, PDFs, or PPTs before generating a question paper.
          </span>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-xs text-rose-200 space-y-1 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div>
            <span className="font-bold text-rose-300 block mb-0.5">RAG Generation Refused / Error</span>
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Generate Action Button */}
      <button
        type="submit"
        disabled={isGenerating || !isOllamaConnected || docCount === 0}
        className="w-full py-3.5 px-6 rounded-xl bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-500 hover:to-blue-500 text-white font-bold text-sm shadow-xl shadow-indigo-600/30 transition-all flex items-center justify-center gap-2.5 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isGenerating ? (
          <>
            <Loader2 className="w-5 h-5 animate-spin" />
            Synthesizing Question Paper via Ollama (llama3.2)...
          </>
        ) : (
          <>
            <Sparkles className="w-5 h-5 text-amber-300" />
            Generate Question Paper (Offline RAG)
          </>
        )}
      </button>

    </form>
  );
}


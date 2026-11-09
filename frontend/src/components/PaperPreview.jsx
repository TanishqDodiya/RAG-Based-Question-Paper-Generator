import React, { useState } from 'react';
import { Printer, Eye, EyeOff, FileText, Download } from 'lucide-react';
import { exportPdf } from '../services/api';
import ExamHeader from './ExamHeader';
import {
  safeText, safeSections, safeQuestions, safeOptions, questionMarks, paperShapeIssues,
} from '../utils/paperState.js';

// Academic presentation helpers (student-facing: no internal AI metadata).
export function defaultExamTitle(examMeta) {
  if (String(examMeta?.exam_type || '').trim().toLowerCase().startsWith('end')) {
    return 'End-Semester Examination';
  }
  return 'Mid-Semester Examination';
}

export function traditionalInstructions(extra) {
  const base = [
    'Attempt all questions.',
    'Figures to the right indicate maximum marks.',
    'Make suitable assumptions wherever necessary and state them clearly.',
  ];
  const seen = new Set(base.map((s) => s.toLowerCase()));
  const extraInstructions = Array.isArray(extra) ? extra : [];
  for (const inst of extraInstructions) {
    const s = String(inst || '').trim();
    if (!s) continue;
    const low = s.toLowerCase();
    if (low.includes('attempt all') || low.includes('figures to the right') || low.includes('assumption')) continue;
    if (seen.has(low)) continue;
    seen.add(low);
    base.push(s);
  }
  return base;
}

export function plainOption(opt, idx) {
  const s = String(opt ?? '').trim().replace(/^[A-Za-z][.)]\s*/, '');
  const letters = 'abcdefgh';
  const tag = letters[idx] || `${idx + 1}`;
  return `${tag})  ${s}`;
}

export default function PaperPreview({ paperData, validation }) {
  const [showAnswerKey, setShowAnswerKey] = useState(false);
  const [isExporting, setIsExporting] = useState(null);

  if (!paperData) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-12 text-center shadow-xl space-y-4">
        <div className="w-16 h-16 rounded-2xl bg-slate-800 border border-slate-700/80 mx-auto flex items-center justify-center text-slate-500">
          <FileText className="w-8 h-8" />
        </div>
        <div className="max-w-md mx-auto">
          <h3 className="text-base font-semibold text-slate-200">No Question Paper Generated Yet</h3>
          <p className="text-xs text-slate-400 mt-1">
            Configure your subject and section preferences on the left, then click 
            <span className="text-indigo-400 font-medium"> "Generate Question Paper"</span> to synthesize an exam paper offline.
          </p>
        </div>
      </div>
    );
  }

  // M-02: never trust model output to have the expected arrays. Malformed
  // entries are skipped for rendering and reported instead of crashing the UI.
  const sections = safeSections(paperData);
  const shapeIssues = paperShapeIssues(paperData);

  const handlePrint = () => {
    window.print();
  };

  const handleExport = async (withKey) => {
    setIsExporting(withKey ? 'key' : 'paper');
    try {
      const blob = await exportPdf(paperData, withKey);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${(safeText(paperData.subject, 'paper') || 'paper').replace(/[^a-z0-9-_]+/gi, '_')}${withKey ? '_with_key' : ''}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`PDF export failed: ${err.message}`);
    } finally {
      setIsExporting(null);
    }
  };

  return (
    <div className="space-y-4">
      
      {/* Top Action Toolbar (Hidden during print) */}
      <div className="no-print bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
          <h3 className="text-sm font-bold text-white">Generated Exam Paper Ready</h3>
        </div>

        <div className="flex items-center gap-3">
          {/* Answer Key Toggle Button */}
          <button
            onClick={() => setShowAnswerKey(!showAnswerKey)}
            className={`px-3.5 py-2 rounded-xl text-xs font-semibold border transition-all flex items-center gap-2 ${
              showAnswerKey
                ? 'bg-amber-500/10 border-amber-500/30 text-amber-400 hover:bg-amber-500/20'
                : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700'
            }`}
          >
            {showAnswerKey ? (
              <>
                <EyeOff className="w-4 h-4" />
                Hide Answer Key
              </>
            ) : (
              <>
                <Eye className="w-4 h-4 text-amber-400" />
                Show Answer Key & Solutions
              </>
            )}
          </button>

          {/* Backend PDF export buttons (M9) + browser print (kept) */}
          <button
            onClick={() => handleExport(false)}
            disabled={isExporting !== null}
            className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold border border-slate-700 transition-all flex items-center gap-2 disabled:opacity-50"
            title="Generate PDF on the server"
          >
            <Download className="w-4 h-4" />
            {isExporting === 'paper' ? 'Exporting...' : 'Export PDF'}
          </button>
          <button
            onClick={() => handleExport(true)}
            disabled={isExporting !== null}
            className="px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-bold transition-all flex items-center gap-2 disabled:opacity-50"
            title="Generate PDF with answer key on the server"
          >
            <Download className="w-4 h-4" />
            {isExporting === 'key' ? 'Exporting...' : 'PDF + Key'}
          </button>
          {/* Browser print (kept) */}
          <button
            onClick={handlePrint}
            className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold shadow-lg shadow-indigo-600/30 transition-all flex items-center gap-2"
          >
            <Printer className="w-4 h-4" />
            Print
          </button>
        </div>
      </div>

      {/* Actual Question Paper Sheet (Print container) — academic Times/A4 layout.
          Student-facing: no badges, no internal metadata (those live in Review/Analytics). */}
      <div
        className="print-paper-container bg-white text-black rounded-none p-8 sm:p-12 shadow-2xl space-y-6 leading-relaxed"
        style={{ fontFamily: "'Times New Roman', Times, serif" }}
      >

        {/* Symbiosis examination header (layout only; blanks for missing data) */}
        <ExamHeader paperData={paperData} />

        {/* M-02: surface malformed model output instead of presenting it as a
            valid paper. The preview still renders every safe question below. */}
        {shapeIssues.length > 0 && (
          <div className="border border-black bg-red-50 text-red-900 p-3 text-[12px] space-y-1">
            <p className="font-bold">Paper data is incomplete or malformed</p>
            <ul className="list-disc pl-5">
              {shapeIssues.slice(0, 5).map((issue, index) => (
                <li key={index}>{issue}</li>
              ))}
            </ul>
            {shapeIssues.length > 5 && (
              <p>…and {shapeIssues.length - 5} more issue(s).</p>
            )}
          </div>
        )}

        {/* Examination title (mid/end per configuration; never shows difficulty) */}
        <div className="text-center">
          <h2 className="text-base font-bold tracking-widest">
            {(safeText(paperData.exam_name) || defaultExamTitle(paperData.exam_meta)).toUpperCase()}
          </h2>
          <hr className="border-black mt-1" />
        </div>

        {/* Traditional instructions */}
        <div className="text-[13px]">
          <p className="font-bold">Instructions:</p>
          <div className="pl-2 space-y-0.5">
            {traditionalInstructions(paperData.instructions).map((line, i) => (
              <p key={i}>{`${'abcdefghijklmnopqrstuvwxyz'[i] || i + 1})'}  ${line}`}</p>
            ))}
          </div>
        </div>

        {/* Question Sections — plain academic flow, running Q numbers, marks right */}
        <div className="space-y-6">
          {sections.length === 0 && (
            <p className="text-[13px] italic">No question sections are available in this paper.</p>
          )}
          {(() => {
            let qNo = 0;
            return sections.map((section, sIdx) => {
              const questions = safeQuestions(section);
              const secTotal = questions.reduce(
                (sum, question) => sum + questionMarks(question, section), 0);
              return (
                <div key={sIdx} className="space-y-3">
                  <div className="flex items-baseline justify-between border-b border-black pb-1">
                    <h2 className="text-[15px] font-bold tracking-wide">
                      {(safeText(section.section_title) || `Section ${String.fromCharCode(65 + sIdx)}`).toUpperCase()}
                    </h2>
                    {questions.length > 0 && (
                      <span className="text-[13px] font-bold shrink-0">[{secTotal} Marks]</span>
                    )}
                  </div>
                  <p className="text-[13px] italic">Answer all questions.</p>
                  <div className="space-y-4">
                    {questions.map((q, qIdx) => {
                      qNo += 1;
                      const marks = questionMarks(q, section);
                      const options = safeOptions(q);
                      const answer = safeText(q.answer);
                      const explanation = safeText(q.explanation);
                      return (
                        <div key={qIdx} className="text-[14px] leading-relaxed">
                          <div className="flex items-start justify-between gap-4">
                            <p className="flex-1 text-justify">
                              <strong>Q.{qNo}</strong>&nbsp;&nbsp;
                              {safeText(q.question) || <em>[Question text unavailable]</em>}
                            </p>
                            <span className="font-bold shrink-0 w-10 text-right">{marks > 0 ? marks : ''}</span>
                          </div>
                          {options.length > 0 && (
                            <div className="pl-10 mt-1 space-y-0.5">
                              {options.map((opt, optIdx) => (
                                <p key={optIdx}>{plainOption(opt, optIdx)}</p>
                              ))}
                            </div>
                          )}
                          {showAnswerKey && (
                            <div className="answer-key pl-10 mt-1 text-[13px]">
                              <p><strong>Answer:</strong> {answer || <em>Not provided</em>}</p>
                              {explanation && (
                                <p><em>Explanation:</em> {explanation}</p>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            });
          })()}
        </div>

        {/* Paper Footer */}
        <div className="border-t border-black pt-4 text-center text-[13px] font-bold">
          *** END OF QUESTION PAPER ***
        </div>

        {/* Print-only running footer with page numbers (screen-hidden) */}
        <div className="print-footer">
          <span>SYMBIOSIS INSTITUTE OF TECHNOLOGY, NAGPUR</span>
          <span className="page-counter" />
        </div>

      </div>

    </div>
  );
}

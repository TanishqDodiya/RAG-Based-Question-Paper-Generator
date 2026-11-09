import React from 'react';
import { isPlainObject, safeText } from '../utils/paperState.js';

// Symbiosis-style examination header (layout only).
// Reads paper metadata + exam_meta; every unprovided field renders as a blank
// underline/box so nothing is ever invented. Used by the print sheet and
// mirrored in the server PDF export (backend/export_pdf.py).
function Field({ label, value, wide }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="font-bold shrink-0">{label}:</span>
      <span className={`border-b border-black inline-block ${wide ? 'flex-1' : 'min-w-[10rem]'} px-1`}>
        {safeText(value) || '\u00A0'}
      </span>
    </div>
  );
}

export function formatDuration(minutes) {
  const m = parseInt(minutes, 10);
  if (!m || m <= 0) return '';
  const h = Math.floor(m / 60);
  const r = m % 60;
  const parts = [];
  if (h) parts.push(`${h} Hour${h !== 1 ? 's' : ''}`);
  if (r) parts.push(`${r} Minutes`);
  return parts.join(' ');
}

export default function ExamHeader({ paperData }) {
  const paper = isPlainObject(paperData) ? paperData : {};
  const meta = isPlainObject(paper.exam_meta) ? paper.exam_meta : {};
  const institute = safeText(paper.institution) || safeText(meta.institute);
  const programme = safeText(meta.programme);
  const batch = safeText(meta.batch);
  const semester = safeText(meta.semester);
  const course = safeText(paper.subject);
  const courseCode = safeText(meta.course_code);
  const date = safeText(meta.exam_date);
  const day = safeText(meta.day);
  const maxMarks = safeText(paper.total_marks);
  const time = safeText(meta.time_slot) || formatDuration(paper.duration_minutes);

  return (
    <div className="exam-header text-black" style={{ fontFamily: "'Times New Roman', Times, serif" }}>
      {/* University band */}
      <div className="flex items-start gap-3 border border-black p-2">
        {/* Text crest (no logo asset in project; nothing fetched from the internet) */}
        <div className="shrink-0 w-12 h-12 border border-black flex flex-col items-center justify-center leading-none">
          <span className="text-lg font-bold">S</span>
          <span className="text-[6px] tracking-tight">SYMBIOSIS</span>
        </div>
        <div className="flex-1 text-center">
          <h1 className="text-[17px] font-bold tracking-wide leading-tight">SYMBIOSIS INTERNATIONAL (DEEMED UNIVERSITY)</h1>
          <p className="text-[10px]">(Established under section 3 of the UGC Act, 1956)</p>
          <p className="text-[10px]">Re-accredited by NAAC with &apos;A++&apos; Grade Awarded Category - I by UGC</p>
          <p className="text-[12px] font-bold mt-0.5">SYMBIOSIS INSTITUTE OF TECHNOLOGY, NAGPUR</p>
        </div>
        {/* Seat No. boxes */}
        <div className="shrink-0 text-center">
          <div className="text-[10px] font-bold mb-1">Seat No.</div>
          <div className="flex gap-[2px]">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <span key={i} className="w-4 h-5 border border-black inline-block bg-white" />
            ))}
          </div>
        </div>
      </div>

      {/* Exam meta fields */}
      <div className="border border-t-0 border-black px-2 py-1.5 space-y-1 text-[12px]">
        <Field label="Institute" value={institute} wide />
        <Field label="Programme" value={programme} wide />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
          <Field label="Batch" value={batch} />
          <Field label="Semester" value={semester} />
        </div>
        <Field label="Course" value={course} wide />
        <Field label="Course Code" value={courseCode} />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
          <Field label="Date" value={date} />
          <div className="flex items-baseline gap-2">
            <span className="font-bold shrink-0">Maximum Marks:</span>
            <span className="border-b border-black min-w-[4rem] px-1">{maxMarks}</span>
          </div>
          <Field label="Day" value={day} />
          <Field label="Time" value={time} />
        </div>
      </div>

      {/* Student information */}
      <div className="border border-t-0 border-black px-2 py-1.5 text-[12px]">
        <h2 className="text-center font-bold tracking-widest text-[11px] mb-1">STUDENT INFORMATION</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5">
          <Field label="Student Name" value="" wide />
          <Field label="PRN Number" value="" />
          <Field label="Seat No." value="" />
          <Field label="Roll No." value="" />
          <Field label="Division / Class" value="" />
          <Field label="Date" value={date} />
        </div>
        <div className="flex justify-end mt-2">
          <div className="text-center">
            <div className="border-b border-black w-40 h-5" />
            <div className="text-[10px] font-bold mt-0.5">Signature of Student</div>
          </div>
        </div>
      </div>

      <p className="text-center font-bold text-[11px] tracking-wider border border-t-0 border-black py-1">
        NOTE : DO NOT WRITE ANYTHING ON THE QUESTION PAPER
      </p>
    </div>
  );
}

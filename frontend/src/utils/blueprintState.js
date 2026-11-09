// Phase 3: pure helpers for restoring/synchronising the exam blueprint.
//
// Saved history stores the validated BlueprintRequest payload (no "expanded"
// breakdown). On reopen we validate that payload again to rebuild the
// structured { payload, expanded } state instead of downgrading it to a legacy
// generation payload. Missing/legacy data is never invented.

import { isPlainObject, safeNumber, safeText } from './paperState.js';

export const DEFAULT_EXAM_META = {
  exam_type: 'mid',
  programme: '',
  semester: '',
  batch: '',
  course_code: '',
  exam_date: '',
  day: '',
  time_slot: '',
};

export const DEFAULT_TOPICS = [
  { name: 'Unit 1', percentage: 20 },
  { name: 'Unit 2', percentage: 20 },
  { name: 'Unit 3', percentage: 25 },
  { name: 'Unit 4', percentage: 20 },
  { name: 'Unit 5', percentage: 15 },
];

export const DEFAULT_DIFFICULTY = { easy: 30, medium: 50, hard: 20 };

export const DEFAULT_TYPES = [
  { type: 'MCQ', marks: 5 },
  { type: 'Short', marks: 15 },
  { type: 'Long', marks: 10 },
];

export const DEFAULT_BLOOM = {
  remember: 15,
  understand: 25,
  apply: 25,
  analyze: 15,
  evaluate: 10,
  create: 10,
};

export const DEFAULT_FORM = {
  examName: 'Mid-Semester Examination',
  institution: '',
  subject: 'Operating Systems',
  totalMarks: 30,
  duration: 120,
  topics: DEFAULT_TOPICS,
  difficulty: DEFAULT_DIFFICULTY,
  types: DEFAULT_TYPES,
  bloom: DEFAULT_BLOOM,
  examMeta: DEFAULT_EXAM_META,
};

function pickExamMeta(value) {
  const meta = isPlainObject(value) ? value : {};
  return Object.fromEntries(
    Object.keys(DEFAULT_EXAM_META).map((key) => [key, safeText(meta[key], DEFAULT_EXAM_META[key])]),
  );
}

export function blueprintFormState(payload, examMeta) {
  const p = isPlainObject(payload) ? payload : {};

  const topics = Array.isArray(p.topics) && p.topics.length > 0
    ? p.topics.filter(isPlainObject).map((topic) => ({
        name: safeText(topic.name),
        percentage: safeNumber(topic.percentage, 0),
      }))
    : DEFAULT_TOPICS.map((topic) => ({ ...topic }));

  const difficulty = isPlainObject(p.difficulty)
    ? {
        easy: safeNumber(p.difficulty.easy, 0),
        medium: safeNumber(p.difficulty.medium, 0),
        hard: safeNumber(p.difficulty.hard, 0),
      }
    : { ...DEFAULT_DIFFICULTY };

  const types = Array.isArray(p.types) && p.types.length > 0
    ? p.types.filter(isPlainObject).map((entry) => ({
        type: safeText(entry.type, 'MCQ') || 'MCQ',
        marks: safeNumber(entry.marks, 0),
      }))
    : DEFAULT_TYPES.map((entry) => ({ ...entry }));

  const bloom = isPlainObject(p.bloom)
    ? {
        remember: safeNumber(p.bloom.remember, 0),
        understand: safeNumber(p.bloom.understand, 0),
        apply: safeNumber(p.bloom.apply, 0),
        analyze: safeNumber(p.bloom.analyze, 0),
        evaluate: safeNumber(p.bloom.evaluate, 0),
        create: safeNumber(p.bloom.create, 0),
      }
    : { ...DEFAULT_BLOOM };

  return {
    examName: safeText(p.exam_name, DEFAULT_FORM.examName) || DEFAULT_FORM.examName,
    institution: safeText(p.institution, ''),
    subject: safeText(p.subject, DEFAULT_FORM.subject),
    totalMarks: safeNumber(p.total_marks, DEFAULT_FORM.totalMarks),
    duration: safeNumber(p.duration_minutes, DEFAULT_FORM.duration),
    topics,
    difficulty,
    types,
    bloom,
    examMeta: pickExamMeta(examMeta),
  };
}

export function isStructuredBlueprintPayload(value) {
  if (!isPlainObject(value)) return false;
  if (typeof value.subject !== 'string' || value.subject.trim().length === 0) return false;
  if (!Number.isFinite(safeNumber(value.total_marks, NaN))) return false;
  if (!Array.isArray(value.topics) || value.topics.length === 0) return false;
  if (!isPlainObject(value.difficulty)) return false;
  if (!Array.isArray(value.types) || value.types.length === 0) return false;
  if (!isPlainObject(value.bloom)) return false;
  return true;
}

export function examMetaFromPaper(paper) {
  return isPlainObject(paper?.exam_meta) ? paper.exam_meta : null;
}

export function examMetaFromBlueprint(blueprint) {
  return isPlainObject(blueprint?.exam_meta) ? blueprint.exam_meta : null;
}

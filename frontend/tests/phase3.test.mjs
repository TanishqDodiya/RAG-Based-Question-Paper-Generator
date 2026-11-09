// Phase 3 deterministic frontend-state tests (Node built-in runner, no deps).
//
// Run: node --test frontend/tests/phase3.test.mjs
//
// These cover the pure helpers used by PaperPreview, ReviewMode, DuplicatePanel,
// BlueprintForm and App. The React wiring itself is checked by
// backend/test_phase3_fixes.py (static wiring, matching the existing project
// test style; no browser automation framework is added).

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  safeSections, safeQuestions, safeOptions, paperShapeIssues, paperStats,
  removeQuestionFromPaper, updateQuestionInPaper, replaceQuestionInPaper,
  sectionsFromPaper, questionDraft, buildQuestionPatch, validateQuestionDraft,
  questionWithSlotDefaults,
} from '../src/utils/paperState.js';
import {
  blueprintFormState, isStructuredBlueprintPayload,
  examMetaFromPaper, examMetaFromBlueprint,
} from '../src/utils/blueprintState.js';

function makePaper() {
  return {
    subject: 'Operating Systems',
    total_marks: 6,
    exam_meta: { exam_type: 'mid', programme: 'B.Tech CSE' },
    sections: [{
      section_title: 'Section A',
      type: 'MCQ',
      marks_per_question: 1,
      questions: [
        {
          id: 'Q1',
          question: 'Which CPU scheduling algorithm uses a time quantum?',
          type: 'MCQ',
          marks: 1,
          difficulty: 'Easy',
          bloom_level: 'Remember',
          unit: 'Unit 1',
          options: ['A. FCFS', 'B. Round Robin', 'C. SJF', 'D. Priority'],
          answer: 'B. Round Robin',
          explanation: 'Round Robin uses a quantum.',
        },
        {
          id: 'Q2',
          question: 'Explain how process scheduling works.',
          type: 'Short',
          marks: 5,
          difficulty: 'Medium',
          bloom_level: 'Understand',
          unit: 'Unit 2',
          options: [],
          answer: 'The scheduler selects a ready process.',
          explanation: 'Model answer.',
        },
      ],
    }],
  };
}

test('rejecting a question removes it and updates the real paper totals', () => {
  const paper = makePaper();
  const next = removeQuestionFromPaper(paper, 'Q1');
  assert.equal(next.sections[0].questions.length, 1);
  assert.equal(next.sections[0].questions[0].id, 'Q2');
  assert.equal(next.total_marks, 5);
  // Original object is untouched (no shared-array mutation).
  assert.equal(paper.sections[0].questions.length, 2);
  assert.equal(paper.total_marks, 6);
});

test('rejecting the last question updates totals to zero', () => {
  const paper = makePaper();
  let next = removeQuestionFromPaper(paper, 'Q1');
  next = removeQuestionFromPaper(next, 'Q2');
  assert.deepEqual(next.sections, []);
  assert.equal(next.total_marks, 0);
});

test('editing question text, options and marks persists and recalculates totals', () => {
  const paper = makePaper();
  const next = updateQuestionInPaper(paper, 'Q1', {
    question: 'Updated question?',
    options: ['A. One', 'B. Two', 'C. Three', 'D. Four'],
    answer: 'B. Two',
    marks: 3,
  });
  const updated = next.sections[0].questions[0];
  assert.equal(updated.id, 'Q1');
  assert.equal(updated.question, 'Updated question?');
  assert.equal(updated.marks, 3);
  assert.deepEqual(updated.options, ['A. One', 'B. Two', 'C. Three', 'D. Four']);
  assert.equal(next.total_marks, 8);
  assert.equal(paper.sections[0].questions[0].question,
    'Which CPU scheduling algorithm uses a time quantum?');
});

test('regeneration replacement keeps the original question id', () => {
  const paper = makePaper();
  const next = replaceQuestionInPaper(paper, 'Q2', {
    question: 'Replacement?', marks: 5, type: 'Short', answer: 'New answer',
  });
  assert.equal(next.sections[0].questions[1].id, 'Q2');
  assert.equal(next.sections[0].questions[1].question, 'Replacement?');
});

test('question draft validation rejects malformed marks and options', () => {
  const valid = {
    question: 'Which option is correct?',
    marks: 1,
    difficulty: 'Easy',
    bloom_level: 'Remember',
    type: 'MCQ',
    answer: 'B. Two',
    explanation: '',
    options: ['A. One', 'B. Two', 'C. Three', 'D. Four'],
  };
  assert.equal(validateQuestionDraft(valid).ok, true);

  for (const marks of [null, '', 'abc', -1, 0, 2.5, undefined]) {
    const result = validateQuestionDraft({ ...valid, marks });
    assert.equal(result.ok, false, `marks ${String(marks)} should be rejected`);
    assert.ok(result.errors.some((error) => error.includes('Marks')));
  }

  assert.equal(validateQuestionDraft({ ...valid, options: ['A. One', 'B. Two'] }).ok, false);
  assert.equal(validateQuestionDraft({ ...valid, answer: 'Z. Nope' }).ok, false);
});

test('question patch clears options for non-MCQ types', () => {
  const draft = {
    question: 'Explain scheduling.',
    marks: 5,
    difficulty: 'Medium',
    bloom_level: 'Understand',
    type: 'Short',
    answer: 'A scheduler picks a process.',
    explanation: 'Marking scheme.',
    options: ['A. stale', 'B. stale'],
  };
  const patch = buildQuestionPatch(draft);
  assert.deepEqual(patch.options, []);
  assert.equal(patch.marks, 5);
});

test('safe helpers tolerate malformed sections, questions and options', () => {
  assert.deepEqual(safeSections(null), []);
  assert.deepEqual(safeSections({ sections: 'not-an-array' }), []);
  assert.deepEqual(safeSections({ sections: [null, 4, { questions: 'bad' }] }), [{ questions: 'bad' }]);

  assert.deepEqual(safeQuestions({ questions: 'bad' }), []);
  assert.deepEqual(safeQuestions({ questions: [null, 'x', { question: 'Q' }] }), [{ question: 'Q' }]);

  assert.deepEqual(safeOptions({ options: 'bad' }), []);
  assert.deepEqual(safeOptions({ options: [null, { bad: true }, ' A ', ''] }), ['A']);

  const issues = paperShapeIssues({ sections: [{ questions: 'bad' }, { questions: [null] }] });
  assert.ok(issues.some((issue) => issue.includes('no questions array')));
  assert.ok(issues.some((issue) => issue.includes('malformed')));
  assert.deepEqual(paperShapeIssues(null), ['Paper data is not an object.']);
});

test('paper stats and restored generator sections reflect actual content', () => {
  const paper = makePaper();
  assert.deepEqual(paperStats(paper), { totalMarks: 6, questionCount: 2, numericMarks: 2 });
  assert.deepEqual(sectionsFromPaper(paper), [{ type: 'MCQ', count: 2, marks_per_q: 1 }]);
});

test('question draft/slot defaults use section metadata without inventing marks', () => {
  const section = { type: 'MCQ', marks_per_question: 2 };
  const draft = questionDraft({ id: 'Q9', question: 'Q?' }, section);
  assert.equal(draft.type, 'MCQ');
  assert.equal(draft.marks, 2);

  const slot = questionWithSlotDefaults({ id: 'Q9' }, section);
  assert.equal(slot.type, 'MCQ');
  assert.equal(slot.marks, 2);
  assert.equal(slot.unit, 'General');

  const noMarks = questionWithSlotDefaults({ id: 'Q9' }, { type: 'Short' });
  assert.equal(noMarks.marks, null);
});

test('structured blueprint restoration keeps payload and exam metadata', () => {
  const payload = {
    subject: 'Operating Systems',
    exam_name: 'End-Semester Examination',
    institution: 'SIT Nagpur',
    total_marks: 30,
    duration_minutes: 120,
    topics: [{ name: 'Unit 1', percentage: 50 }, { name: 'Unit 2', percentage: 50 }],
    difficulty: { easy: 30, medium: 50, hard: 20 },
    types: [{ type: 'MCQ', marks: 10 }, { type: 'Short', marks: 20 }],
    bloom: { remember: 20, understand: 20, apply: 20, analyze: 20, evaluate: 10, create: 10 },
  };
  assert.equal(isStructuredBlueprintPayload(payload), true);

  const state = blueprintFormState(payload, { exam_type: 'end', programme: 'B.Tech CSE' });
  assert.equal(state.subject, 'Operating Systems');
  assert.equal(state.examName, 'End-Semester Examination');
  assert.equal(state.institution, 'SIT Nagpur');
  assert.equal(state.totalMarks, 30);
  assert.equal(state.duration, 120);
  assert.deepEqual(state.topics, payload.topics);
  assert.deepEqual(state.types, payload.types);
  assert.equal(state.examMeta.exam_type, 'end');
  assert.equal(state.examMeta.programme, 'B.Tech CSE');
});

test('legacy snapshots never masquerade as structured blueprints', () => {
  const legacy = {
    subject: 'Operating Systems',
    total_marks: 6,
    difficulty: 'Medium',
    sections: [{ type: 'MCQ', count: 1, marks_per_q: 1 }],
  };
  assert.equal(isStructuredBlueprintPayload(legacy), false);
  assert.equal(isStructuredBlueprintPayload(null), false);

  // Missing fields fall back to defaults instead of throwing.
  const state = blueprintFormState(legacy, null);
  assert.equal(state.subject, 'Operating Systems');
  assert.ok(Array.isArray(state.topics) && state.topics.length > 0);
  assert.ok(Array.isArray(state.types) && state.types.length > 0);

  // A restore without any blueprint resets the form to fresh defaults.
  const blank = blueprintFormState(null, null);
  assert.equal(blank.subject, 'Operating Systems');
  assert.equal(blank.examName, 'Mid-Semester Examination');
  assert.equal(blank.totalMarks, 30);
  assert.notEqual(blank.topics, state.topics);
});

test('exam metadata is read from the paper first and blueprint second', () => {
  const paper = makePaper();
  assert.deepEqual(examMetaFromPaper(paper), { exam_type: 'mid', programme: 'B.Tech CSE' });
  assert.equal(examMetaFromPaper({ exam_meta: 'bad' }), null);
  assert.deepEqual(examMetaFromBlueprint({ exam_meta: { exam_type: 'end' } }), { exam_type: 'end' });
  assert.equal(examMetaFromBlueprint({ exam_meta: [] }), null);
});

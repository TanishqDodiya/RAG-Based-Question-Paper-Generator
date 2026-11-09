// Phase 3: pure, defensive paper-state helpers.
//
// These functions are deliberately framework-free so the review workflow can be
// unit-tested with Node's built-in test runner (no new browser-test dependency).
// Components use them so malformed LLM output and legacy snapshots can never
// throw during render or state updates.

export const QUESTION_TYPES = ['MCQ', 'Short', 'Long', 'True/False', 'Fill-in-blanks'];
export const DIFFICULTY_VALUES = ['Easy', 'Medium', 'Hard'];
export const BLOOM_VALUES = ['Remember', 'Understand', 'Apply', 'Analyze', 'Evaluate', 'Create'];

export function isPlainObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

export function safeText(value, fallback = '') {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'boolean') return String(value);
  return fallback;
}

export function safeNumber(value, fallback = 0) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : fallback;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

export function safeSections(paper) {
  const sections = isPlainObject(paper) ? paper.sections : null;
  if (!Array.isArray(sections)) return [];
  return sections.filter(isPlainObject);
}

export function safeQuestions(section) {
  const questions = isPlainObject(section) ? section.questions : null;
  if (!Array.isArray(questions)) return [];
  return questions.filter(isPlainObject);
}

export function safeOptions(question) {
  const options = isPlainObject(question) ? question.options : null;
  if (!Array.isArray(options)) return [];
  return options.map((option) => safeText(option).trim()).filter((option) => option !== '');
}

export function questionMarks(question, section) {
  const q = isPlainObject(question) ? question : {};
  const sec = isPlainObject(section) ? section : {};
  const raw = q.marks !== undefined && q.marks !== null ? q.marks : sec.marks_per_question;
  const marks = safeNumber(raw, NaN);
  return Number.isFinite(marks) && marks >= 0 ? marks : 0;
}

export function paperStats(paper) {
  let totalMarks = 0;
  let questionCount = 0;
  let numericMarks = 0;
  for (const section of safeSections(paper)) {
    for (const question of safeQuestions(section)) {
      questionCount += 1;
      const q = isPlainObject(question) ? question : {};
      const raw = q.marks !== undefined && q.marks !== null ? q.marks : section.marks_per_question;
      const marks = safeNumber(raw, NaN);
      if (Number.isFinite(marks) && marks >= 0) {
        totalMarks += marks;
        numericMarks += 1;
      }
    }
  }
  return { totalMarks, questionCount, numericMarks };
}

export function recalculatePaperTotals(paper) {
  if (!isPlainObject(paper)) return paper;
  const stats = paperStats(paper);
  const fallback = safeNumber(paper.total_marks, 0);
  const total = stats.questionCount === 0
    ? 0
    : (stats.numericMarks > 0 ? stats.totalMarks : fallback);
  return { ...paper, total_marks: total };
}

export function findQuestion(paper, qid) {
  const sections = safeSections(paper);
  for (let sectionIndex = 0; sectionIndex < sections.length; sectionIndex += 1) {
    const section = sections[sectionIndex];
    const questions = safeQuestions(section);
    for (let questionIndex = 0; questionIndex < questions.length; questionIndex += 1) {
      if (questions[questionIndex].id === qid) {
        return { section, question: questions[questionIndex], sectionIndex, questionIndex };
      }
    }
  }
  return null;
}

export function removeQuestionFromPaper(paper, qid) {
  if (!isPlainObject(paper) || !Array.isArray(paper.sections)) return paper;
  let removed = false;
  const sections = paper.sections
    .map((section) => {
      if (!isPlainObject(section) || !Array.isArray(section.questions)) return section;
      const questions = section.questions.filter((question) => {
        const keep = !(isPlainObject(question) && question.id === qid);
        if (!keep) removed = true;
        return keep;
      });
      return { ...section, questions };
    })
    .filter((section) => {
      // Keep malformed sections (they are surfaced by the preview) but drop a
      // valid section once its last question has been removed.
      if (!isPlainObject(section) || !Array.isArray(section.questions)) return true;
      return section.questions.length > 0;
    });
  if (!removed) return paper;
  return recalculatePaperTotals({ ...paper, sections });
}

export function updateQuestionInPaper(paper, qid, patch) {
  if (!isPlainObject(paper) || !Array.isArray(paper.sections) || !isPlainObject(patch)) return paper;
  let updated = false;
  const sections = paper.sections.map((section) => {
    if (!isPlainObject(section) || !Array.isArray(section.questions)) return section;
    const questions = section.questions.map((question) => {
      if (!isPlainObject(question) || question.id !== qid) return question;
      updated = true;
      return { ...question, ...patch, id: question.id };
    });
    return { ...section, questions };
  });
  if (!updated) return paper;
  return recalculatePaperTotals({ ...paper, sections });
}

export function replaceQuestionInPaper(paper, qid, replacement) {
  if (!isPlainObject(paper) || !Array.isArray(paper.sections) || !isPlainObject(replacement)) return paper;
  let updated = false;
  const sections = paper.sections.map((section) => {
    if (!isPlainObject(section) || !Array.isArray(section.questions)) return section;
    const questions = section.questions.map((question) => {
      if (!isPlainObject(question) || question.id !== qid) return question;
      updated = true;
      return { ...replacement, id: question.id };
    });
    return { ...section, questions };
  });
  if (!updated) return paper;
  return recalculatePaperTotals({ ...paper, sections });
}

export function sectionsFromPaper(paper) {
  return safeSections(paper).map((section) => {
    const questions = safeQuestions(section);
    const sectionMarks = safeNumber(section.marks_per_question, NaN);
    const firstQuestionMarks = questions.length ? safeNumber(questions[0].marks, NaN) : NaN;
    const marksPerQ = Number.isFinite(sectionMarks)
      ? sectionMarks
      : (Number.isFinite(firstQuestionMarks) ? firstQuestionMarks : 1);
    const rawType = safeText(section.type, 'Short');
    const type = QUESTION_TYPES.includes(rawType) ? rawType : 'Short';
    const count = questions.length > 0
      ? questions.length
      : Math.max(1, safeNumber(section.count, 1));
    return {
      type,
      count,
      marks_per_q: marksPerQ > 0 ? marksPerQ : 1,
    };
  });
}

export function paperShapeIssues(paper) {
  const issues = [];
  if (!isPlainObject(paper)) {
    return ['Paper data is not an object.'];
  }
  if (!Array.isArray(paper.sections)) {
    return ['Paper has no sections array.'];
  }
  if (paper.sections.length === 0) {
    issues.push('Paper has no sections.');
  }
  paper.sections.forEach((section, sectionIndex) => {
    if (!isPlainObject(section)) {
      issues.push(`Section ${sectionIndex + 1} is not a valid section object.`);
      return;
    }
    if (!Array.isArray(section.questions)) {
      issues.push(`Section ${sectionIndex + 1} has no questions array.`);
      return;
    }
    section.questions.forEach((question, questionIndex) => {
      if (!isPlainObject(question)) {
        issues.push(`Question ${questionIndex + 1} in section ${sectionIndex + 1} is malformed.`);
        return;
      }
      if (!safeText(question.question).trim()) {
        issues.push(`Question ${questionIndex + 1} in section ${sectionIndex + 1} has no readable text.`);
      }
    });
  });
  return issues;
}

export function questionDraft(question, section) {
  const q = isPlainObject(question) ? question : {};
  const sec = isPlainObject(section) ? section : {};
  const rawMarks = q.marks !== undefined && q.marks !== null ? q.marks : sec.marks_per_question;
  const marks = (typeof rawMarks === 'number' || typeof rawMarks === 'string') ? rawMarks : '';
  return {
    question: safeText(q.question),
    marks,
    difficulty: safeText(q.difficulty, 'Medium') || 'Medium',
    bloom_level: safeText(q.bloom_level, 'Understand') || 'Understand',
    type: safeText(q.type, safeText(sec.type, 'Short')) || 'Short',
    answer: safeText(q.answer),
    explanation: safeText(q.explanation),
    options: safeOptions(q),
  };
}

function normalizeOption(value) {
  return safeText(value).trim().replace(/^[A-Za-z][.)]\s*/, '').trim().toLowerCase();
}

export function optionMatchesAnswer(option, answer) {
  return normalizeOption(option) === normalizeOption(answer);
}

export function validateQuestionDraft(draft) {
  const errors = [];
  const question = safeText(draft?.question).trim();
  if (!question) errors.push('Question text is required.');

  const marks = Number(draft?.marks);
  if (!Number.isInteger(marks) || marks <= 0) {
    errors.push('Marks must be a positive whole number.');
  }

  const type = safeText(draft?.type).trim();
  if (!QUESTION_TYPES.includes(type)) {
    errors.push(`Type must be one of: ${QUESTION_TYPES.join(', ')}.`);
  }
  const difficulty = safeText(draft?.difficulty).trim();
  if (!DIFFICULTY_VALUES.includes(difficulty)) {
    errors.push('Difficulty must be Easy, Medium or Hard.');
  }
  const bloom = safeText(draft?.bloom_level).trim();
  if (!BLOOM_VALUES.includes(bloom)) {
    errors.push('Bloom level is invalid.');
  }

  const answer = safeText(draft?.answer).trim();
  if (!answer) errors.push('Answer is required.');

  const options = Array.isArray(draft?.options)
    ? draft.options.map((option) => safeText(option).trim()).filter(Boolean)
    : [];

  if (type === 'MCQ') {
    if (options.length !== 4) {
      errors.push('MCQ requires exactly 4 non-empty options.');
    } else if (answer && !options.some((option) => optionMatchesAnswer(option, answer))) {
      errors.push('Answer must match one of the MCQ options.');
    }
  } else if (type === 'True/False') {
    if (answer && !/^(true|false)\b/i.test(answer)) {
      errors.push('True/False answer must start with True or False.');
    }
  } else if (type === 'Fill-in-blanks') {
    if (!question.includes('___') && !question.includes('...')) {
      errors.push('Fill-in-the-blanks question needs ___ or ... markers.');
    }
  }

  return { ok: errors.length === 0, errors };
}

export function buildQuestionPatch(draft) {
  const type = safeText(draft?.type).trim();
  const options = type === 'MCQ' && Array.isArray(draft?.options)
    ? draft.options.map((option) => safeText(option).trim()).filter(Boolean)
    : [];
  return {
    question: safeText(draft?.question).trim(),
    marks: Number(draft?.marks),
    difficulty: safeText(draft?.difficulty).trim(),
    bloom_level: safeText(draft?.bloom_level).trim(),
    type,
    answer: safeText(draft?.answer).trim(),
    explanation: safeText(draft?.explanation).trim(),
    options,
  };
}

export function questionWithSlotDefaults(question, section) {
  const q = isPlainObject(question) ? question : {};
  const sec = isPlainObject(section) ? section : {};
  const rawMarks = q.marks !== undefined && q.marks !== null ? q.marks : sec.marks_per_question;
  return {
    ...q,
    type: safeText(q.type, safeText(sec.type, 'Short')) || 'Short',
    marks: safeNumber(rawMarks, null),
    difficulty: safeText(q.difficulty, 'Medium') || 'Medium',
    bloom_level: safeText(q.bloom_level, 'Understand') || 'Understand',
    unit: safeText(q.unit, 'General') || 'General',
    topic: safeText(q.topic, '') || '',
  };
}

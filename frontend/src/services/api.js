import { getSessionId } from './session';

const API_BASE = '';
// C-01: optional shared secret for local deployments that set APP_AUTH_TOKEN.
// Empty by default so existing development flow is unchanged.
const API_TOKEN = (import.meta.env.VITE_API_TOKEN || '').trim();

function getHeaders(extraHeaders = {}) {
  const headers = {
    'X-Session-ID': getSessionId(),
    ...extraHeaders,
  };
  if (API_TOKEN) {
    headers['X-API-Key'] = API_TOKEN;
  }
  return headers;
}

export async function fetchStatus() {
  try {
    const res = await fetch('/api/status', {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`Status HTTP Error ${res.status}`);
    return await res.json();
  } catch (err) {
    return {
      status: 'offline',
      ollama_connected: false,
      message: err.message || 'Cannot reach FastAPI backend server',
      models_installed: [],
      required_models: {
        llm: { name: 'llama3.2', installed: false },
        embedding: { name: 'nomic-embed-text', installed: false }
      },
      chromadb: { status: 'offline', document_count: 0 }
    };
  }
}

export async function uploadNotes(files, unitLabel) {
  const formData = new FormData();
  for (let i = 0; i < files.length; i++) {
    formData.append('files', files[i]);
  }
  // M3: optional teacher-supplied unit tag for all files in this request
  if (unitLabel && unitLabel.trim()) {
    formData.append('unit_label', unitLabel.trim());
  }

  const res = await fetch('/upload-notes', {
    method: 'POST',
    headers: getHeaders(),
    body: formData,
    cache: 'no-store',
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(errorData.detail || `Upload failed with HTTP ${res.status}`);
  }

  return await res.json();
}

export async function fetchNotes() {
  const res = await fetch('/api/notes', {
    headers: getHeaders(),
    cache: 'no-store',
  });
  if (!res.ok) throw new Error('Failed to fetch notes metadata');
  return await res.json();
}

export async function clearNotes() {
  const res = await fetch('/api/notes', {
    method: 'DELETE',
    headers: getHeaders(),
    cache: 'no-store',
  });
  if (!res.ok) throw new Error('Failed to clear vector store');
  return await res.json();
}

export async function generatePaper(configData) {
  const res = await fetch('/generate-paper', {
    method: 'POST',
    headers: getHeaders({
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify(configData),
    cache: 'no-store',
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: 'Generation failed' }));
    throw new Error(errorData.detail || `Generation failed with HTTP ${res.status}`);
  }

  return await res.json();
}

export async function validateBlueprint(blueprintData) {
  const res = await fetch('/api/blueprint/validate', {
    method: 'POST',
    headers: getHeaders({
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify(blueprintData),
    cache: 'no-store',
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Blueprint validation failed with HTTP ${res.status}`);
  }

  return data;
}

export async function previewRetrieval(query, unit, topK = 5) {
  const res = await fetch('/api/retrieval/preview', {
    method: 'POST',
    headers: getHeaders({
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify({ query, unit: unit || null, top_k: topK }),
    cache: 'no-store',
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Retrieval preview failed with HTTP ${res.status}`);
  }

  return data;
}

export async function generateStructured(structuredData) {
  const res = await fetch('/api/generate-structured', {
    method: 'POST',
    headers: getHeaders({
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify(structuredData),
    cache: 'no-store',
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Structured generation failed with HTTP ${res.status}`);
  }

  return data;
}

export async function validatePaper(paper) {
  const res = await fetch('/api/validate', {
    method: 'POST',
    headers: getHeaders({
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify({ paper }),
    cache: 'no-store',
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Validation failed with HTTP ${res.status}`);
  }

  return data;
}

export async function checkDuplicates(paper) {
  const res = await fetch('/api/duplicates', {
    method: 'POST',
    headers: getHeaders({
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify({ paper }),
    cache: 'no-store',
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Duplicate check failed with HTTP ${res.status}`);
  }

  return data;
}

export async function regenerateQuestion(subject, question, avoid = []) {
  const res = await fetch('/api/questions/regenerate', {
    method: 'POST',
    headers: getHeaders({
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify({ subject, question, avoid }),
    cache: 'no-store',
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Regeneration failed with HTTP ${res.status}`);
  }

  return data;
}

export async function fetchAnalytics(paper, blueprint, validation, duplicates) {
  const res = await fetch('/api/analytics', {
    method: 'POST',
    headers: getHeaders({
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify({ paper, blueprint: blueprint || null, validation: validation || null, duplicates: duplicates || null }),
    cache: 'no-store',
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Analytics failed with HTTP ${res.status}`);
  }

  return data;
}

export async function exportPdf(paper, includeAnswers = false) {
  const res = await fetch(`/api/export/pdf?include_answers=${includeAnswers ? 'true' : 'false'}`, {
    method: 'POST',
    headers: getHeaders({
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify({ paper }),
    cache: 'no-store',
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `PDF export failed with HTTP ${res.status}`);
  }

  return await res.blob();
}

export async function savePaperSnapshot(title, paper, blueprint, validation) {
  const res = await fetch('/api/papers', {
    method: 'POST',
    headers: getHeaders({
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify({ title: title || null, paper, blueprint: blueprint || null, validation: validation || null }),
    cache: 'no-store',
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Save failed with HTTP ${res.status}`);
  }

  return data;
}

export async function listPaperSnapshots() {
  const res = await fetch('/api/papers', { headers: getHeaders(), cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to list saved papers');
  return await res.json();
}

export async function getPaperSnapshot(id) {
  const res = await fetch(`/api/papers/${id}`, { headers: getHeaders(), cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to load saved paper');
  return await res.json();
}

export async function deletePaperSnapshot(id) {
  const res = await fetch(`/api/papers/${id}`, { method: 'DELETE', headers: getHeaders(), cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to delete saved paper');
  return await res.json();
}



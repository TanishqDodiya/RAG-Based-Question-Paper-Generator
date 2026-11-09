import React, { useState, useEffect } from 'react';
import { History, Save, FolderOpen, Copy, Trash2, Loader2, AlertCircle } from 'lucide-react';
import { savePaperSnapshot, listPaperSnapshots, getPaperSnapshot, deletePaperSnapshot } from '../services/api';

export default function HistoryList({ paper, blueprint, validation, onLoad }) {
  const [items, setItems] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [savedNote, setSavedNote] = useState(null);

  const refresh = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await listPaperSnapshots();
      setItems(data.papers || []);
    } catch (err) {
      setError(err.message || 'Failed to load history.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const handleSave = async () => {
    if (!paper) return;
    setBusy('save');
    setError(null);
    setSavedNote(null);
    try {
      // H-05: keep the structured blueprint intact and persist exam metadata
      // alongside it so a reopened snapshot can restore both safely.
      const savedBlueprint = blueprint?.payload
        ? { ...blueprint.payload, ...(blueprint.exam_meta ? { exam_meta: blueprint.exam_meta } : {}) }
        : null;
      const data = await savePaperSnapshot(null, paper, savedBlueprint, validation);
      setSavedNote(`Saved as #${data.id} — ${data.title}`);
      await refresh();
    } catch (err) {
      setError(err.message || 'Save failed.');
    } finally {
      setBusy(null);
    }
  };

  const handleOpen = async (id) => {
    setBusy(`open-${id}`);
    setError(null);
    try {
      const data = await getPaperSnapshot(id);
      if (onLoad) await onLoad(data);
    } catch (err) {
      setError(err.message || 'Open failed.');
    } finally {
      setBusy(null);
    }
  };

  const handleDuplicate = async (id) => {
    setBusy(`dup-${id}`);
    setError(null);
    try {
      const data = await getPaperSnapshot(id);
      await savePaperSnapshot(`${data.title} (copy)`, data.paper, data.blueprint, data.validation);
      await refresh();
    } catch (err) {
      setError(err.message || 'Duplicate failed.');
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm(`Delete saved paper #${id}?`)) return;
    setBusy(`del-${id}`);
    try {
      await deletePaperSnapshot(id);
      await refresh();
    } catch (err) {
      setError(err.message || 'Delete failed.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4 flex-wrap gap-2">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <History className="w-5 h-5 text-indigo-400" />
            Paper History
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Snapshots with blueprint + validation — reopen, duplicate, or regenerate questions
          </p>
        </div>
        <button
          onClick={handleSave}
          disabled={!paper || busy !== null}
          className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition-all flex items-center gap-2 disabled:opacity-50"
          title={paper ? 'Snapshot the current paper' : 'Generate a paper first'}
        >
          {busy === 'save' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Save Current Paper
        </button>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs text-rose-300 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" /><span>{error}</span>
        </div>
      )}
      {savedNote && (
        <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300">
          {savedNote}
        </div>
      )}

      {isLoading ? (
        <div className="text-xs text-slate-500 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading history...</div>
      ) : items.length === 0 ? (
        <p className="text-xs text-slate-500 italic">No saved papers yet. Generate a paper, then snapshot it here.</p>
      ) : (
        <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
          {items.map((it) => (
            <div key={it.id} className="p-3 rounded-xl bg-slate-950 border border-slate-800 text-xs flex items-center justify-between gap-3 flex-wrap">
              <div className="space-y-0.5">
                <div className="font-bold text-slate-100">#{it.id} — {it.title}</div>
                <div className="text-slate-500">{it.subject} · {it.total_marks} marks · {it.n_questions} questions · {it.created_at?.replace('T', ' ')}</div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <button onClick={() => handleOpen(it.id)} disabled={busy !== null}
                  className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold flex items-center gap-1 disabled:opacity-50">
                  {busy === `open-${it.id}` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FolderOpen className="w-3.5 h-3.5" />} Reopen
                </button>
                <button onClick={() => handleDuplicate(it.id)} disabled={busy !== null}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center gap-1 disabled:opacity-50">
                  <Copy className="w-3.5 h-3.5" /> Duplicate
                </button>
                <button onClick={() => handleDelete(it.id)} disabled={busy !== null}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-rose-600 text-slate-400 hover:text-white border border-slate-700 flex items-center gap-1 disabled:opacity-50">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

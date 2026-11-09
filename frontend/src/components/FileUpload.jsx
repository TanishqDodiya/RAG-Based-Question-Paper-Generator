import React, { useState, useEffect } from 'react';
import { UploadCloud, FileText, CheckCircle, Trash2, Database, Loader2, AlertCircle } from 'lucide-react';
import { uploadNotes, fetchNotes, clearNotes } from '../services/api';

export default function FileUpload({ onNotesUpdated }) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [notesMeta, setNotesMeta] = useState({ documents_count: 0, files: [] });
  const [uploadStatus, setUploadStatus] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  // M3: optional teacher-supplied unit tag applied to all files in this upload
  const [unitLabel, setUnitLabel] = useState('');

  const loadNotesMeta = async () => {
    try {
      const data = await fetchNotes();
      setNotesMeta(data);
      if (onNotesUpdated) onNotesUpdated(data.documents_count);
    } catch (err) {
      console.error('Failed to load notes metadata:', err);
    }
  };

  useEffect(() => {
    loadNotesMeta();
  }, []);

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const filesArr = Array.from(e.dataTransfer.files);
      setSelectedFiles((prev) => [...prev, ...filesArr]);
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      const filesArr = Array.from(e.target.files);
      setSelectedFiles((prev) => [...prev, ...filesArr]);
    }
  };

  const removeSelectedFile = (index) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleUpload = async () => {
    if (selectedFiles.length === 0) return;
    setIsUploading(true);
    setErrorMsg(null);
    setUploadStatus('Uploading & chunking notes via nomic-embed-text into ChromaDB...');

    try {
      const res = await uploadNotes(selectedFiles, unitLabel);
      const skipped = res.skipped_files?.length
        ? ` Skipped ${res.skipped_files.length}: ${res.skipped_files.map((s) => `${s.filename} (${s.reason})`).join('; ')}`
        : '';
      const unitsNote = res.processed_files?.some((f) => f.units?.length)
        ? ` Units: ${[...new Set(res.processed_files.flatMap((f) => f.units || []))].join(', ')}.`
        : '';
      setUploadStatus(`Success! Processed ${res.processed_files?.length || 0} file(s).${unitsNote}${skipped}`);
      setSelectedFiles([]);
      await loadNotesMeta();
    } catch (err) {
      setErrorMsg(err.message || 'Error uploading files');
    } finally {
      setIsUploading(false);
    }
  };

  const handleClear = async () => {
    if (!window.confirm('Are you sure you want to clear all stored reference notes from ChromaDB?')) return;
    try {
      await clearNotes();
      await loadNotesMeta();
      setUploadStatus('Vector database cleared.');
    } catch (err) {
      setErrorMsg(err.message || 'Failed to clear collection');
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
      
      {/* Title & Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <UploadCloud className="w-5 h-5 text-indigo-400" />
            Reference Notes & PDF Ingestion
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Upload PDF textbook chapters or lecture notes for ChromaDB semantic retrieval (RAG)
          </p>
        </div>

        {notesMeta.documents_count > 0 && (
          <button
            onClick={handleClear}
            className="px-3 py-1.5 text-xs font-medium text-rose-400 hover:text-white bg-rose-500/10 hover:bg-rose-600 rounded-lg border border-rose-500/20 transition-all flex items-center gap-1.5"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Clear Collection
          </button>
        )}
      </div>

      {/* Drag and Drop Zone */}
      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer ${
          dragActive
            ? 'border-indigo-500 bg-indigo-500/10 scale-[0.99]'
            : 'border-slate-700 hover:border-slate-600 bg-slate-950/50 hover:bg-slate-950'
        }`}
      >
        <input
          type="file"
          id="file-input"
          multiple
          accept=".pdf,.pptx,.docx,.txt,.md"
          onChange={handleFileChange}
          className="hidden"
        />
        <label htmlFor="file-input" className="cursor-pointer flex flex-col items-center gap-3">
          <div className="w-12 h-12 rounded-full bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
            <UploadCloud className="w-6 h-6" />
          </div>
          <div>
            <span className="text-sm font-semibold text-indigo-400 hover:underline">Click to browse</span>
            <span className="text-sm text-slate-400"> or drag and drop reference notes</span>
          </div>
          <p className="text-xs text-slate-500">Supports PDF, PPTX, DOCX, TXT, MD files (Chunks: 1000 tokens, 100 overlap)</p>
        </label>
      </div>

      {/* M3: Unit tag for this upload (overrides auto-detection) */}
      <div className="flex items-center gap-3 text-xs">
        <label htmlFor="unit-label" className="text-slate-400 font-medium shrink-0">
          Unit tag <span className="text-slate-500">(optional)</span>:
        </label>
        <input
          id="unit-label"
          type="text"
          value={unitLabel}
          onChange={(e) => setUnitLabel(e.target.value)}
          placeholder="e.g. Unit 3 — overrides auto-detection"
          className="flex-1 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-200 focus:outline-none focus:border-indigo-500"
        />
      </div>

      {/* Selected File Queue */}
      {selectedFiles.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Files Ready for Vectorization ({selectedFiles.length})
          </h3>
          <div className="space-y-2 max-h-40 overflow-y-auto pr-1">
            {selectedFiles.map((file, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between p-3 rounded-lg bg-slate-800/80 border border-slate-700/60 text-xs"
              >
                <div className="flex items-center gap-2.5 truncate">
                  <FileText className="w-4 h-4 text-indigo-400 shrink-0" />
                  <span className="text-slate-200 font-medium truncate">{file.name}</span>
                  <span className="text-slate-500 shrink-0">({(file.size / 1024 / 1024).toFixed(2)} MB)</span>
                </div>
                <button
                  onClick={() => removeSelectedFile(idx)}
                  className="text-slate-400 hover:text-rose-400 p-1"
                >
                  &times;
                </button>
              </div>
            ))}
          </div>

          <button
            onClick={handleUpload}
            disabled={isUploading}
            className="w-full py-2.5 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm shadow-lg shadow-indigo-600/30 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {isUploading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Processing Embeddings...
              </>
            ) : (
              <>
                <UploadCloud className="w-4 h-4" />
                Ingest Files into Vector Store
              </>
            )}
          </button>
        </div>
      )}

      {/* Status Messages */}
      {uploadStatus && (
        <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300 flex items-center gap-2">
          <CheckCircle className="w-4 h-4 shrink-0 text-emerald-400" />
          <span>{uploadStatus}</span>
        </div>
      )}
      {errorMsg && (
        <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs text-rose-300 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Currently Ingested Notes Inventory */}
      <div className="border-t border-slate-800 pt-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
          <Database className="w-3.5 h-3.5 text-indigo-400" />
          Indexed Knowledge Base ({notesMeta.files?.length || 0} Files / {notesMeta.documents_count} Chunks)
        </h3>

        {notesMeta.files?.length === 0 ? (
          <p className="text-xs text-slate-500 italic">
            No reference notes uploaded yet for this session. Upload notes, PDFs, or PPTs to enable RAG question paper generation.
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-36 overflow-y-auto pr-1">
            {notesMeta.files.map((file, idx) => (
              <div key={idx} className="p-2.5 rounded-lg bg-slate-950 border border-slate-800 text-xs space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-slate-300 font-medium truncate mr-2" title={file.filename}>
                    {file.filename}
                  </span>
                  <span className="px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 font-bold text-[10px] shrink-0">
                    {file.chunks} chunks
                  </span>
                </div>
                {(file.units?.length > 0 || file.pages?.length > 0) && (
                  <div className="text-[10px] text-slate-500 leading-relaxed">
                    {file.units?.length > 0 && <span>Units: {file.units.join(', ')}</span>}
                    {file.units?.length > 0 && file.pages?.length > 0 && <span> · </span>}
                    {file.pages?.length > 0 && (
                      <span>
                        Locators: {file.pages.slice(0, 6).join(', ')}
                        {file.pages.length > 6 && ` +${file.pages.length - 6} more`}
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
  );
}

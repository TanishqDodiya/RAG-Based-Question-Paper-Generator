import React, { useState, useEffect, useRef } from 'react';
import Header from './components/Header';
import FileUpload from './components/FileUpload';
import GeneratorForm from './components/GeneratorForm';
import BlueprintForm from './components/BlueprintForm';
import ValidationPanel from './components/ValidationPanel';
import DuplicatePanel from './components/DuplicatePanel';
import PaperAnalysis from './components/PaperAnalysis';
import ReviewMode from './components/ReviewMode';
import HistoryList from './components/HistoryList';
import WorkflowSteps from './components/WorkflowSteps';
import PaperPreview from './components/PaperPreview';
import PaperErrorBoundary from './components/PaperErrorBoundary';
import { fetchStatus, validatePaper, checkDuplicates, validateBlueprint } from './services/api';
import { isPlainObject } from './utils/paperState.js';
import {
  isStructuredBlueprintPayload, examMetaFromPaper, examMetaFromBlueprint,
} from './utils/blueprintState.js';

export default function App() {
  const [status, setStatus] = useState(null);
  const [activeTab, setActiveTab] = useState('generator'); // 'generator' | 'upload' | 'history'
  const [generatedPaper, setGeneratedPaper] = useState(null);
  // M2: validated exam blueprint (shared with M4 generation later)
  const [blueprint, setBlueprint] = useState(null);
  // M5: deterministic validation result for the current paper
  const [validation, setValidation] = useState(null);
  // M6/M7: duplicate pairs for the current paper (lifted for analytics)
  const [duplicates, setDuplicates] = useState(null);
  // FIX 2: paper identity — bumped on every NEW paper so panel-local state
  // (analysis data, review decisions/editing, dismissed pairs, expanded rows)
  // from Q-ids like "Q1" can never leak into the next paper. Review edits keep
  // the same identity so unrelated review selections survive.
  const [paperGen, setPaperGen] = useState(0);
  // H-04: bumped once an edit's validation + duplicate refresh has settled.
  // PaperAnalysis uses it to refresh analytics that the teacher already opened.
  const [qualityToken, setQualityToken] = useState(0);
  // M-04: bumped only when a saved snapshot is restored, so BlueprintForm can
  // distinguish an external restore from its own successful validation.
  const [blueprintRestoreToken, setBlueprintRestoreToken] = useState(0);
  const editTokenRef = useRef(0);
  const loadTokenRef = useRef(0);

  const loadStatus = async () => {
    const data = await fetchStatus();
    setStatus(data);
  };

  useEffect(() => {
    loadStatus();
    // M1: reduced polling (4s → 8s) + pause when tab hidden to cut Ollama/Chroma load
    const interval = setInterval(() => {
      if (!document.hidden) loadStatus();
    }, 8000);
    return () => clearInterval(interval);
  }, []);

  const handleNotesUpdated = () => {
    loadStatus();
  };

  const handlePaperGenerated = (paperData) => {
    editTokenRef.current += 1; // cancel any in-flight edit refresh
    setGeneratedPaper(paperData);
    setValidation(null); // M5: stale verdicts never apply to a new paper
    setDuplicates(null); // M6: stale pairs never apply to a new paper
    setPaperGen((g) => g + 1); // FIX 2: new identity resets panel-local state
  };

  // H-04: one central path for every review edit (edit/reject/delete/regenerate).
  // The paper changes immediately; all derived results are invalidated at once
  // and then recalculated against the latest content.
  const handlePaperEdited = async (nextPaper) => {
    const editToken = editTokenRef.current + 1;
    editTokenRef.current = editToken;
    setGeneratedPaper(nextPaper);
    // Never show verdicts or duplicate pairs that describe the previous text.
    setValidation(null);
    setDuplicates(null);

    const [validationResult, duplicateResult] = await Promise.allSettled([
      validatePaper(nextPaper),
      checkDuplicates(nextPaper),
    ]);
    if (editToken !== editTokenRef.current) {
      // A newer edit superseded this refresh; let the newer call publish.
      return { stale: true, errors: [] };
    }

    const errors = [];
    if (validationResult.status === 'fulfilled') {
      setValidation(validationResult.value);
    } else {
      errors.push(`Validation: ${validationResult.reason?.message || 'failed'}`);
    }
    if (duplicateResult.status === 'fulfilled') {
      setDuplicates(duplicateResult.value);
    } else {
      errors.push(`Duplicate check: ${duplicateResult.reason?.message || 'failed'}`);
    }
    // Refresh analytics only after both derived inputs have settled.
    setQualityToken((token) => token + 1);
    return { stale: false, errors };
  };

  // M10/H-05: reopen a snapshot — restore paper + structured blueprint +
  // validation together. Saved history stores the blueprint payload only, so
  // validate it again to rebuild the structured {payload, expanded} state.
  const handleLoadSnapshot = async (snapshot) => {
    const loadToken = loadTokenRef.current + 1;
    loadTokenRef.current = loadToken;
    editTokenRef.current += 1; // cancel any in-flight edit refresh

    const paper = isPlainObject(snapshot?.paper) ? snapshot.paper : null;
    const savedMeta = examMetaFromPaper(paper) || examMetaFromBlueprint(snapshot?.blueprint);

    if (paper) {
      const restoredPaper = savedMeta && !isPlainObject(paper.exam_meta)
        ? { ...paper, exam_meta: savedMeta }
        : paper;
      setGeneratedPaper(restoredPaper);
      setValidation(isPlainObject(snapshot?.validation) ? snapshot.validation : null);
    } else {
      setGeneratedPaper(null);
      setValidation(null);
    }
    setDuplicates(null);
    setPaperGen((g) => g + 1); // FIX 2: loaded paper is a new identity
    setActiveTab('generator');

    const savedBlueprint = snapshot?.blueprint;
    if (!isStructuredBlueprintPayload(savedBlueprint)) {
      // Legacy snapshots may carry a legacy generation payload or no blueprint.
      // Never invent the missing structured fields.
      setBlueprint(null);
      setBlueprintRestoreToken((token) => token + 1);
      return;
    }

    try {
      const data = await validateBlueprint(savedBlueprint);
      if (loadToken !== loadTokenRef.current) return;
      if (data?.ok && data?.expanded) {
        setBlueprint({ payload: savedBlueprint, expanded: data.expanded, exam_meta: savedMeta || {} });
      } else {
        setBlueprint(null);
      }
    } catch (err) {
      if (loadToken !== loadTokenRef.current) return;
      // Invalid restored blueprint: keep the paper, but never activate a
      // blueprint that the validator would reject.
      setBlueprint(null);
    } finally {
      if (loadToken === loadTokenRef.current) {
        setBlueprintRestoreToken((token) => token + 1);
      }
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      
      {/* Header Bar */}
      <Header status={status} onRefresh={loadStatus} />

      {/* Main Workspace */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">

        {/* M10: workflow progress — teacher always knows where they are */}
        <WorkflowSteps
          hasMaterials={(status?.chromadb?.document_count || 0) > 0}
          hasBlueprint={!!blueprint?.expanded}
          hasPaper={!!generatedPaper}
          hasQuality={!!validation && !!duplicates}
        />
        {/* Navigation Tabs (Mobile & Desktop switcher) */}
        <div className="no-print flex items-center gap-2 border-b border-slate-800 pb-3">
          <button
            onClick={() => setActiveTab('generator')}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all ${
              activeTab === 'generator'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'bg-slate-900 hover:bg-slate-800 text-slate-400 border border-slate-800'
            }`}
          >
            1. Paper Generator & Config
          </button>
          <button
            onClick={() => setActiveTab('upload')}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 ${
              activeTab === 'upload'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'bg-slate-900 hover:bg-slate-800 text-slate-400 border border-slate-800'
            }`}
          >
            2. Reference Notes & RAG Store
            {status?.chromadb?.document_count > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 font-bold text-[10px]">
                {status.chromadb.document_count} chunks
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all ${
              activeTab === 'history'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'bg-slate-900 hover:bg-slate-800 text-slate-400 border border-slate-800'
            }`}
          >
            3. History
          </button>
        </div>

        {/* M10: history tab renders full-width; other tabs keep the 2-column layout */}
        {activeTab === 'history' ? (
          <HistoryList
            paper={generatedPaper}
            blueprint={blueprint}
            validation={validation}
            onLoad={handleLoadSnapshot}
          />
        ) : (
        <>
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          
          {/* Left Column: Form / Upload Controls */}
          <div className="no-print lg:col-span-5 space-y-6">
            {activeTab === 'generator' ? (
              <>
                <BlueprintForm
                  onValidated={setBlueprint}
                  onInvalid={() => setBlueprint(null)}
                  activeBlueprint={blueprint}
                  restoreToken={blueprintRestoreToken}
                />
                {blueprint?.expanded && (
                  <div className="px-4 py-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300">
                    Blueprint active: <strong>{blueprint.payload?.subject}</strong> · {blueprint.payload?.total_marks} marks · {blueprint.payload?.exam_name}
                    <span className="text-emerald-400/70"> (structured generation enabled)</span>
                  </div>
                )}
                <GeneratorForm
                  onPaperGenerated={handlePaperGenerated}
                  isOllamaConnected={status?.ollama_connected}
                  onRefreshStatus={loadStatus}
                  docCount={status?.chromadb?.document_count || 0}
                  blueprint={blueprint}
                  paper={generatedPaper}
                  paperIdentity={paperGen}
                />
              </>
            ) : (
              <FileUpload onNotesUpdated={handleNotesUpdated} />
            )}
          </div>

          {/* Right Column: Question Paper Preview */}
          <div className="lg:col-span-7">
            <PaperErrorBoundary>
              <PaperPreview paperData={generatedPaper} validation={validation} />
            </PaperErrorBoundary>
          </div>

        </div>

        {/* M5/M6/M7/M8: quality + review sections, keyed by paper identity (FIX 2)
            so analysis data, review decisions/editing, dismissed pairs and
            expanded rows reset whenever a new paper is generated or loaded. */}
        {generatedPaper && (
          <>
            <ValidationPanel
              key={`val-${paperGen}`}
              paper={generatedPaper}
              validation={validation}
              onValidation={setValidation}
            />
            <DuplicatePanel
              key={`dup-${paperGen}`}
              paper={generatedPaper}
              subject={generatedPaper.subject}
              onPaperChange={handlePaperEdited}
              pairs={duplicates}
              onPairs={setDuplicates}
            />
            <PaperAnalysis
              key={`ana-${paperGen}`}
              paper={generatedPaper}
              blueprint={blueprint}
              validation={validation}
              duplicates={duplicates}
              qualityToken={qualityToken}
            />
            <ReviewMode
              key={`rev-${paperGen}`}
              paper={generatedPaper}
              validation={validation}
              subject={generatedPaper.subject}
              onPaperChange={handlePaperEdited}
            />
          </>
        )}
        </> )} {/* end history ternary */}

      </main>

      {/* Footer */}
      <footer className="no-print border-t border-slate-900 py-4 text-center text-xs text-slate-500">
        Local Question Paper Generator &bull; 100% Offline AI &bull; Ollama + ChromaDB + FastAPI + React
      </footer>

    </div>
  );
}

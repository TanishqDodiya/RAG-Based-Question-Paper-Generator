import React from 'react';
import { BookOpen, Cpu, CheckCircle2, AlertTriangle, RefreshCw, Server } from 'lucide-react';

export default function Header({ status, onRefresh }) {
  const isOllamaConnected = status?.ollama_connected;
  const isLlmInstalled = status?.required_models?.llm?.installed;
  const isEmbedInstalled = status?.required_models?.embedding?.installed;
  const docCount = status?.chromadb?.document_count || 0;

  return (
    <header className="no-print bg-slate-900/80 backdrop-blur-md border-b border-slate-800 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex flex-wrap items-center justify-between gap-4">
        
        {/* Logo & Title */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-blue-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <BookOpen className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
              Local Question Paper Generator
              <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-medium">
                100% Offline
              </span>
            </h1>
            <p className="text-xs text-slate-400">Powered by Ollama (llama3.2 & nomic-embed-text) & ChromaDB</p>
          </div>
        </div>

        {/* System Status Indicators */}
        <div className="flex items-center gap-3 text-xs">
          {/* Document count badge */}
          <div className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700/80 flex items-center gap-2">
            <Server className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-slate-300 font-medium">Notes Chunks:</span>
            <span className="text-indigo-400 font-bold">{docCount}</span>
          </div>

          {/* Ollama Status Badge */}
          <div className={`px-3 py-1.5 rounded-lg border flex items-center gap-2 transition-colors ${
            isOllamaConnected 
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : 'bg-amber-500/10 border-amber-500/30 text-amber-400'
          }`}>
            <span className="relative flex h-2 w-2">
              {isOllamaConnected && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              )}
              <span className={`relative inline-flex rounded-full h-2 w-2 ${isOllamaConnected ? 'bg-emerald-500' : 'bg-amber-500'}`}></span>
            </span>
            <span className="font-semibold">{isOllamaConnected ? 'Ollama Online' : 'Ollama Offline'}</span>
          </div>

          {/* Refresh Button */}
          <button
            onClick={onRefresh}
            className="p-1.5 text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition-colors"
            title="Refresh Server & Ollama Status"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>

      </div>

      {/* Warning banner if Ollama or models missing */}
      {(!isOllamaConnected || !isLlmInstalled || !isEmbedInstalled) && (
        <div className="bg-amber-500/10 border-y border-amber-500/20 px-4 py-2 text-xs text-amber-200 flex items-center justify-between max-w-7xl mx-auto">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
            <span>
              {!isOllamaConnected 
                ? 'Ollama service is disconnected at http://localhost:11434. Please start Ollama locally.' 
                : `Missing required models: ${!isLlmInstalled ? 'llama3.2 ' : ''}${!isEmbedInstalled ? 'nomic-embed-text' : ''}. Run: ollama pull llama3.2 && ollama pull nomic-embed-text`}
            </span>
          </div>
        </div>
      )}
    </header>
  );
}

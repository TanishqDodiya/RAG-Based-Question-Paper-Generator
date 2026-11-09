import React from 'react';
import { Check } from 'lucide-react';

// Lightweight step tracker so the teacher always knows where they are:
// Upload → Blueprint → Generate → Quality → Review → Export.
export default function WorkflowSteps({ hasMaterials, hasBlueprint, hasPaper, hasQuality }) {
  const steps = [
    { label: 'Upload Materials', done: hasMaterials },
    { label: 'Blueprint', done: hasBlueprint },
    { label: 'Generate', done: hasPaper },
    { label: 'Quality Check', done: hasQuality },
    { label: 'Review & Export', done: false },
  ];
  const firstOpen = steps.findIndex((s) => !s.done);
  return (
    <div className="no-print flex items-center gap-1.5 flex-wrap text-[11px] font-semibold">
      {steps.map((s, i) => {
        const done = s.done;
        const current = i === firstOpen;
        return (
          <React.Fragment key={s.label}>
            <span className={`px-2.5 py-1 rounded-full border flex items-center gap-1.5 transition-colors ${
              done ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
              : current ? 'bg-indigo-600 text-white border-indigo-600 shadow-lg shadow-indigo-600/30'
              : 'bg-slate-900 text-slate-500 border-slate-800'}`}>
              {done && <Check className="w-3 h-3" />}
              {i + 1}. {s.label}
            </span>
            {i < steps.length - 1 && <span className="text-slate-700">→</span>}
          </React.Fragment>
        );
      })}
    </div>
  );
}

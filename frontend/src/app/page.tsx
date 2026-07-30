'use client';

import React, { useEffect, useState, useCallback, useRef } from 'react';
import Link from 'next/link';

interface DatasetInfo {
  name: string;
  filename: string;
  uploaded_at: string;
  row_count: number;
  columns: string[];
  numeric_columns: string[];
  is_active: boolean;
}

const API_URL =
  typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000')
    : 'http://localhost:8000';

interface UploadSuccess { filename: string; rows: number }

function UploadSection({ onUploadSuccess }: { onUploadSuccess: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [status, setStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [success, setSuccess] = useState<UploadSuccess | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const reset = () => { setStatus('idle'); setErrorMsg(null); setSuccess(null); setProgress(0); };

  const setFileIfCsv = (f: File) => {
    if (f.name.endsWith('.csv')) { setFile(f); reset(); }
    else { setErrorMsg('Only CSV files are allowed'); setStatus('error'); }
  };

  const handleDrag = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault(); e.stopPropagation();
    setDragActive(e.type === 'dragenter' || e.type === 'dragover');
  };
  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault(); e.stopPropagation(); setDragActive(false);
    if (e.dataTransfer.files?.[0]) setFileIfCsv(e.dataTransfer.files[0]);
  };
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) setFileIfCsv(e.target.files[0]);
  };
  const clearFile = () => { setFile(null); reset(); if (fileRef.current) fileRef.current.value = ''; };

  const fmtBytes = (b: number) => {
    if (!b) return '0 B';
    const i = Math.floor(Math.log(b) / Math.log(1024));
    return `${(b / Math.pow(1024, i)).toFixed(1)} ${['B','KB','MB','GB'][i]}`;
  };

  const upload = async () => {
    if (!file) return;
    setStatus('uploading'); setProgress(10);
    const iv = setInterval(() => setProgress(p => p >= 80 ? p : p + 10), 150);
    const fd = new FormData(); fd.append('file', file);
    try {
      const res = await fetch(`${API_URL}/ingest`, { method: 'POST', body: fd });
      clearInterval(iv); setProgress(100);
      const data = await res.json();
      if (res.ok) {
        setStatus('success');
        setSuccess({ filename: file.name, rows: data.rows });
        onUploadSuccess(); // refresh schema
      } else {
        setStatus('error'); setErrorMsg(data.detail || 'Ingestion failed.');
      }
    } catch (e: unknown) {
      clearInterval(iv); setStatus('error');
      setErrorMsg(e instanceof Error ? e.message : 'Cannot reach backend.');
    }
  };

  return (
    <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800 rounded-2xl p-6 shadow-2xl">
      <h2 className="text-sm font-bold text-slate-300 uppercase tracking-widest mb-5 flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full bg-violet-400" />
        Upload CSV Dataset
      </h2>

      {/* Drop zone */}
      <div onDragEnter={handleDrag} onDragOver={handleDrag}
        onDragLeave={handleDrag} onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer
          flex flex-col items-center justify-center min-h-[170px] transition-all duration-200
          ${dragActive ? 'border-violet-500 bg-violet-950/10'
            : 'border-slate-700 hover:border-slate-600 bg-slate-950/30 hover:bg-slate-950/50'}`}>
        <input ref={fileRef} type="file" accept=".csv" className="hidden"
          onChange={handleChange} id="csv-file-input" />
        <div className="p-3 bg-slate-800 rounded-full border border-slate-700 text-violet-400 mb-3">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
            strokeWidth={1.5} stroke="currentColor" className="w-7 h-7">
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M12 16.5V9.75m0 0 3 3m-3-3-3 3M6.75 19.5a4.5 4.5 0 0 1-1.41-8.775 5.25 5.25 0 0 1 10.233-2.33 3 3 0 0 1 3.758 3.848A3.752 3.752 0 0 1 18 19.5H6.75Z" />
          </svg>
        </div>
        <p className="text-sm font-semibold text-slate-200">
          Drag &amp; drop a CSV, or <span className="text-violet-400 underline underline-offset-2">browse</span>
        </p>
        <p className="text-[10px] text-slate-500 mt-1.5 uppercase tracking-wider">.csv only</p>
      </div>

      {/* File pill */}
      {file && (
        <div className="mt-4 bg-slate-950/50 border border-slate-800 rounded-xl p-3
          flex items-center justify-between animate-fadeIn">
          <div className="flex items-center gap-2.5 truncate">
            <div className="p-1.5 bg-slate-800 rounded-lg text-cyan-400 flex-shrink-0">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
                strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
              </svg>
            </div>
            <div className="truncate">
              <p className="text-xs font-semibold text-slate-200 truncate">{file.name}</p>
              <p className="text-[10px] text-slate-500">{fmtBytes(file.size)}</p>
            </div>
          </div>
          {status !== 'uploading' && (
            <button onClick={clearFile} id="remove-file-button"
              className="p-1 text-slate-500 hover:text-rose-400 transition-colors flex-shrink-0">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
                strokeWidth={2} stroke="currentColor" className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      )}

      {/* Upload button */}
      {file && status === 'idle' && (
        <button onClick={upload} id="upload-button"
          className="mt-4 w-full bg-gradient-to-r from-violet-600 to-cyan-600
            hover:from-violet-500 hover:to-cyan-500 text-white font-bold
            py-3 px-4 rounded-xl transition-all duration-200 hover:-translate-y-px text-sm">
          Stream CSV into Pipeline →
        </button>
      )}

      {/* Progress */}
      {status === 'uploading' && (
        <div className="mt-4 space-y-1.5">
          <div className="flex justify-between text-[10px] font-semibold text-slate-400">
            <span className="animate-pulse">Publishing rows to Kafka…</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-slate-900 rounded-full h-1.5 border border-slate-800">
            <div className="bg-gradient-to-r from-violet-500 to-cyan-500 h-full rounded-full
              transition-all duration-300" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      {/* Success */}
      {status === 'success' && success && (
        <div className="mt-4 bg-emerald-950/30 border border-emerald-800/50 rounded-xl p-4
          space-y-2 animate-slideUp">
          <div className="flex items-center gap-2">
            <div className="p-1 bg-emerald-900/60 rounded-md text-emerald-400">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
                strokeWidth={2.5} stroke="currentColor" className="w-3.5 h-3.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              </svg>
            </div>
            <p className="text-sm font-bold text-emerald-300">Ingested Successfully</p>
          </div>
          <div className="bg-emerald-950/50 rounded-lg p-2.5 text-xs space-y-1">
            <div className="flex justify-between">
              <span className="text-emerald-400/70">Dataset:</span>
              <span className="font-semibold text-slate-200">{success.filename.replace('.csv','')}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-emerald-400/70">Rows streamed:</span>
              <span className="font-bold text-emerald-400">{success.rows}</span>
            </div>
          </div>
          <button onClick={reset} id="success-dismiss-button"
            className="w-full text-xs font-semibold py-2 border border-emerald-800/40
              hover:bg-emerald-900/20 text-emerald-400 rounded-lg transition-colors">
            Upload Another File
          </button>
        </div>
      )}

      {/* Error */}
      {status === 'error' && errorMsg && (
        <div className="mt-4 bg-rose-950/30 border border-rose-800/50 rounded-xl p-4
          space-y-2 animate-slideUp">
          <div className="flex items-center gap-2">
            <div className="p-1 bg-rose-900/60 rounded-md text-rose-400">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
                strokeWidth={2.5} stroke="currentColor" className="w-3.5 h-3.5">
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" />
              </svg>
            </div>
            <p className="text-sm font-bold text-rose-300">Ingestion Error</p>
          </div>
          <p className="text-xs text-rose-400/90">{errorMsg}</p>
          <button onClick={reset} id="error-dismiss-button"
            className="w-full text-xs font-semibold py-2 border border-rose-800/40
              hover:bg-rose-900/20 text-rose-400 rounded-lg transition-colors">
            Try Again
          </button>
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/datasets`);
      if (res.ok) setDatasets(await res.json());
    } catch {
      // API not ready
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const activeDataset = datasets.find(d => d.is_active) || datasets[0] || null;

  const handleActivate = async (name: string) => {
    try {
      await fetch(`${API_URL}/datasets/${name}/activate`, { method: 'POST' });
      fetchData();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <main className="min-h-[calc(100vh-65px)] pt-10 px-6 max-w-6xl mx-auto space-y-8">
      {/* Background gradients */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-40 -left-40 w-[600px] h-[600px] rounded-full bg-violet-900/15 blur-[140px]" />
        <div className="absolute -bottom-40 -right-40 w-[600px] h-[600px] rounded-full bg-cyan-900/15 blur-[140px]" />
      </div>

      <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white mb-2">
            Dataset Dashboard
          </h1>
          <p className="text-sm text-slate-400">
            Manage your uploaded datasets and view current context.
          </p>
        </div>

        {datasets.length > 0 && (
          <div className="flex items-center gap-3 bg-slate-900/80 border border-slate-700 py-2 px-4 rounded-xl">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Active:</span>
            <select
              value={activeDataset?.name || ''}
              onChange={(e) => handleActivate(e.target.value)}
              className="bg-transparent text-sm font-bold text-violet-300 outline-none cursor-pointer"
            >
              {datasets.map(d => (
                <option key={d.name} value={d.name} className="bg-slate-900 text-slate-200">
                  {d.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div className="relative z-10 grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Active Dataset Stats & Upload */}
        <div className="lg:col-span-2 space-y-6">
          <UploadSection onUploadSuccess={fetchData} />
          
          {loading ? (
            <div className="h-64 bg-slate-900/60 rounded-2xl border border-slate-800 animate-pulse" />
          ) : activeDataset ? (
            <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-6">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-200 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-cyan-400" />
                  {activeDataset.name}
                </h2>
                <Link href="/chat"
                  className="px-4 py-2 text-xs font-bold bg-violet-600/20 text-violet-300 border border-violet-500/30 rounded-lg hover:bg-violet-600/40 transition-colors">
                  Open Chat →
                </Link>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div className="bg-slate-950/50 rounded-xl p-4 border border-slate-800">
                  <p className="text-xs text-slate-500 font-semibold mb-1">Rows</p>
                  <p className="text-2xl font-black text-slate-200">{activeDataset.row_count.toLocaleString()}</p>
                </div>
                <div className="bg-slate-950/50 rounded-xl p-4 border border-slate-800">
                  <p className="text-xs text-slate-500 font-semibold mb-1">Columns</p>
                  <p className="text-2xl font-black text-slate-200">{activeDataset.columns.length}</p>
                </div>
                <div className="bg-slate-950/50 rounded-xl p-4 border border-slate-800">
                  <p className="text-xs text-slate-500 font-semibold mb-1">Uploaded At</p>
                  <p className="text-sm font-semibold text-slate-300 mt-2">
                    {new Date(activeDataset.uploaded_at).toLocaleDateString()}
                  </p>
                </div>
              </div>

              <div>
                <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">Columns schema</p>
                <div className="flex flex-wrap gap-2">
                  {activeDataset.columns.map(c => (
                    <span key={c} className={`text-xs px-2.5 py-1 rounded-md border font-medium ${
                      activeDataset.numeric_columns.includes(c)
                        ? 'bg-cyan-950/40 border-cyan-800 text-cyan-300'
                        : 'bg-violet-950/40 border-violet-800 text-violet-300'
                    }`}>
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </div>

        {/* Right Column: History */}
        <div className="space-y-6">
          <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800 rounded-2xl p-6 shadow-2xl h-full">
            <h3 className="text-sm font-bold text-slate-300 uppercase tracking-widest mb-5 flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-violet-400" />
              Upload History
            </h3>
            {datasets.length === 0 && !loading && (
              <p className="text-xs text-slate-500 italic">No history available.</p>
            )}
            <div className="space-y-3">
              {datasets.map(ds => (
                <div key={ds.name} onClick={() => handleActivate(ds.name)}
                  className={`p-3 rounded-xl border cursor-pointer transition-colors ${
                    ds.is_active
                      ? 'bg-violet-900/20 border-violet-600/40'
                      : 'bg-slate-950/50 border-slate-800 hover:border-slate-600 hover:bg-slate-800/40'
                  }`}>
                  <div className="flex justify-between items-start mb-1">
                    <p className={`text-sm font-bold ${ds.is_active ? 'text-violet-300' : 'text-slate-300'}`}>
                      {ds.name}
                    </p>
                    {ds.is_active && (
                      <span className="text-[9px] bg-violet-600 text-white px-1.5 py-0.5 rounded font-black tracking-widest">
                        ACTIVE
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] text-slate-500 font-mono">
                    {ds.row_count.toLocaleString()} rows · {new Date(ds.uploaded_at).toLocaleDateString()}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

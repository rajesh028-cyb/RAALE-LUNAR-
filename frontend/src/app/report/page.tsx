'use client';

import React, { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';

interface DatasetInfo {
  name: string;
  is_active: boolean;
}

interface ColumnStat {
  name: string;
  col_type: string;
  distinct_count: number;
  top_values: { value: string; count: number }[];
  min_val: number | null;
  max_val: number | null;
  avg_val: number | null;
  sum_val: number | null;
}

interface DatasetSummary {
  name: string;
  row_count: number;
  column_stats: ColumnStat[];
}

const API_URL =
  typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000')
    : 'http://localhost:8000';

function BarChart({ data }: { data: { value: string; count: number }[] }) {
  if (!data || data.length === 0) return <p className="text-xs text-slate-500 italic">No data</p>;
  
  const maxCount = Math.max(...data.map(d => d.count));
  
  return (
    <div className="space-y-3 mt-4">
      {data.map((item, i) => (
        <div key={i} className="flex flex-col gap-1">
          <div className="flex justify-between text-xs">
            <span className="text-slate-300 font-medium truncate pr-4">{item.value || '(empty)'}</span>
            <span className="text-slate-400 font-mono">{item.count.toLocaleString()}</span>
          </div>
          <div className="w-full bg-slate-900 rounded-full h-2.5 border border-slate-800 overflow-hidden relative">
            <div 
              className="bg-gradient-to-r from-violet-500 to-cyan-400 h-full rounded-full transition-all duration-1000 ease-out"
              style={{ width: `${Math.max(1, (item.count / maxCount) * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function ReportPage() {
  const [activeDataset, setActiveDataset] = useState<DatasetInfo | null>(null);
  const [summary, setSummary] = useState<DatasetSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/datasets/current`);
      if (!res.ok) throw new Error("Failed to load active dataset.");
      const ds = await res.json();
      
      if (!ds.name) {
        setLoading(false);
        return;
      }
      
      setActiveDataset(ds);

      const sumRes = await fetch(`${API_URL}/datasets/${ds.name}/summary`);
      if (!sumRes.ok) throw new Error("Failed to load dataset summary.");
      const sumData = await sumRes.json();
      setSummary(sumData);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message || 'An error occurred while fetching the report.');
      } else {
        setError('An unknown error occurred.');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  const categoricals = summary?.column_stats.filter(c => c.col_type === 'categorical') || [];
  const numerics = summary?.column_stats.filter(c => c.col_type === 'numeric') || [];

  return (
    <main className="min-h-[calc(100vh-65px)] pt-10 px-6 max-w-7xl mx-auto space-y-8 pb-20">
      {/* Background gradients */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden z-[-1]">
        <div className="absolute -top-40 -right-40 w-[600px] h-[600px] rounded-full bg-cyan-900/10 blur-[140px]" />
        <div className="absolute bottom-20 left-10 w-[500px] h-[500px] rounded-full bg-violet-900/10 blur-[140px]" />
      </div>

      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white mb-2 flex items-center gap-3">
            <span className="w-3 h-3 rounded-full bg-emerald-400 animate-pulse" />
            Automated Visual Report
          </h1>
          <p className="text-sm text-slate-400">
            {activeDataset?.name 
              ? `Showing data insights for ${activeDataset.name}` 
              : 'No active dataset selected for reporting.'}
          </p>
        </div>
        
        {loading && <div className="text-xs text-slate-500 animate-pulse">Analyzing dataset...</div>}
      </div>

      {error && (
        <div className="bg-rose-950/40 border border-rose-800/50 p-4 rounded-xl text-rose-300 text-sm">
          {error}
        </div>
      )}

      {!loading && !activeDataset && !error && (
        <div className="bg-slate-900/60 backdrop-blur border border-slate-800 rounded-2xl p-10 shadow-2xl text-center space-y-4 max-w-2xl mx-auto mt-20">
          <p className="text-lg font-bold text-slate-300">No Dataset Available</p>
          <p className="text-sm text-slate-500">
            Please upload a dataset on the Chat page or select an active dataset on the Dashboard.
          </p>
          <Link href="/" className="inline-block mt-4 px-6 py-2.5 bg-violet-600/20 text-violet-300 border border-violet-500/30 rounded-xl font-bold text-sm hover:bg-violet-600/40 transition-colors">
            Go to Dashboard
          </Link>
        </div>
      )}

      {!loading && summary && (
        <div className="space-y-12 animate-in fade-in slide-in-from-bottom-4 duration-700">
          
          {/* Numerics Summary */}
          {numerics.length > 0 && (
            <div className="space-y-5">
              <h2 className="text-lg font-bold text-slate-200 tracking-wide uppercase border-b border-slate-800/50 pb-2">
                Numeric Metrics
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {numerics.map(col => (
                  <div key={col.name} className="bg-slate-900/40 backdrop-blur-md border border-slate-800 rounded-2xl p-5 hover:border-slate-700 transition-colors">
                    <p className="text-xs font-bold text-violet-400 uppercase tracking-widest mb-4 truncate">{col.name}</p>
                    <div className="space-y-3">
                      <div className="flex justify-between items-end border-b border-slate-800/60 pb-2">
                        <span className="text-xs text-slate-500">Sum</span>
                        <span className="text-base font-black text-slate-200">{col.sum_val?.toLocaleString(undefined, {maximumFractionDigits: 2}) ?? 'N/A'}</span>
                      </div>
                      <div className="flex justify-between items-end border-b border-slate-800/60 pb-2">
                        <span className="text-xs text-slate-500">Average</span>
                        <span className="text-base font-bold text-slate-300">{col.avg_val?.toLocaleString(undefined, {maximumFractionDigits: 2}) ?? 'N/A'}</span>
                      </div>
                      <div className="flex justify-between items-end">
                        <span className="text-xs text-slate-500">Max / Min</span>
                        <span className="text-sm font-semibold text-slate-400">
                          {col.max_val?.toLocaleString(undefined, {maximumFractionDigits: 2}) ?? '-'} / {col.min_val?.toLocaleString(undefined, {maximumFractionDigits: 2}) ?? '-'}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Categoricals Distributions */}
          {categoricals.length > 0 && (
            <div className="space-y-5">
              <h2 className="text-lg font-bold text-slate-200 tracking-wide uppercase border-b border-slate-800/50 pb-2">
                Categorical Distributions
              </h2>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {categoricals.map(col => (
                  <div key={col.name} className="bg-slate-900/40 backdrop-blur-md border border-slate-800 rounded-2xl p-6">
                    <div className="flex justify-between items-center mb-2">
                      <p className="text-xs font-bold text-cyan-400 uppercase tracking-widest truncate">{col.name}</p>
                      <p className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold bg-slate-950 px-2 py-1 rounded">
                        {col.distinct_count} distinct values
                      </p>
                    </div>
                    
                    <BarChart data={col.top_values} />
                    
                    {col.distinct_count > 10 && (
                      <p className="text-[10px] text-slate-600 mt-4 text-center italic">Showing top 10 values</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          
        </div>
      )}
    </main>
  );
}

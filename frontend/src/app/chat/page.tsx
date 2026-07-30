'use client';

import React, {
  useState, useRef, useEffect, useCallback,
  FormEvent,
} from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────


interface SchemaData {
  columns: string[];
  datasets: string[];
  numeric_columns: string[];
  active_dataset: string | null;
}

interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  question: string;
  answer: string;
  cypher: string | null;
  results: Record<string, unknown>[] | null;
  grounded: boolean;
  loading?: boolean;
}

// ── API URL ───────────────────────────────────────────────────────────────────

const API_URL =
  typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000')
    : 'http://localhost:8000';

// ── Dynamic question generator ────────────────────────────────────────────────

function generateSampleQuestions(schema: SchemaData): string[] {
  const { columns, numeric_columns } = schema;
  if (columns.length === 0) return [];

  const questions: string[] = [];
  const used = new Set<string>();

  const add = (q: string) => {
    if (!used.has(q)) { used.add(q); questions.push(q); }
  };

  // Find likely "name" columns
  const nameHints = ['name', 'employee', 'person', 'user', 'member', 'title'];
  const nameCol = columns.find(c => nameHints.some(h => c.toLowerCase().includes(h)));

  // Find likely "category" columns (non-numeric short-value columns)
  const catHints = ['department', 'city', 'country', 'region', 'category', 'type',
    'status', 'role', 'team', 'group', 'division', 'location', 'office'];
  const catCol = columns.find(c => catHints.some(h => c.toLowerCase().includes(h)));

  // 1. Count total rows
  add('How many records are there?');

  // 2. List all rows (show name column if available)
  if (nameCol) {
    add(`List all ${nameCol}s`);
  } else {
    add('Show all records');
  }

  // 3. Count distinct for category column
  if (catCol) {
    add(`How many ${catCol}s?`);
    add(`Show all ${catCol}s`);
  }

  // 4. Aggregates for numeric columns
  if (numeric_columns.length > 0) {
    add(`Average ${numeric_columns[0]}`);
    if (numeric_columns.length > 0) add(`Maximum ${numeric_columns[0]}`);
    if (numeric_columns.length > 1) add(`Total ${numeric_columns[1]}`);
  }

  // 5. Filter example (name + category)
  if (nameCol && catCol && columns.length >= 2) {
    add(`Who works in Engineering?`);
  }

  // 6. Fill from remaining columns up to 8 total
  for (const col of columns) {
    if (questions.length >= 8) break;
    if (col === nameCol || col === catCol) continue;
    if (numeric_columns.includes(col)) {
      add(`Minimum ${col}`);
    } else {
      add(`Distinct ${col} values`);
    }
  }

  return questions.slice(0, 8);
}

// ── Small UI components ───────────────────────────────────────────────────────

function GroundedBadge({ grounded }: { grounded: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full
      text-[10px] font-bold tracking-wider
      ${grounded
        ? 'bg-emerald-900/60 text-emerald-300 border border-emerald-700/40'
        : 'bg-amber-900/60 text-amber-300 border border-amber-700/40'}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${grounded ? 'bg-emerald-400' : 'bg-amber-400'}`} />
      {grounded ? 'GROUNDED' : 'UNGROUNDED'}
    </span>
  );
}

function Collapsible({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2 border border-slate-800 rounded-xl overflow-hidden">
      <button onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold
          text-slate-400 hover:text-slate-200 hover:bg-slate-800/40 transition-colors">
        <span>{label}</span>
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
          strokeWidth={2} stroke="currentColor"
          className={`w-3.5 h-3.5 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}>
          <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
        </svg>
      </button>
      {open && (
        <div className="bg-slate-950/60 border-t border-slate-800 p-3">{children}</div>
      )}
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-1.5 px-2 py-2">
      {[0, 1, 2].map(i => (
        <span key={i} className="thinking-dot w-2 h-2 rounded-full bg-violet-400"
          style={{ animationDelay: `${i * 0.2}s` }} />
      ))}
    </div>
  );
}

// Format markdown bold (**text**) in answer strings
function AnswerText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <p className="text-sm text-slate-100 leading-relaxed">
      {parts.map((part, i) =>
        part.startsWith('**') && part.endsWith('**')
          ? <strong key={i} className="text-white font-bold">{part.slice(2, -2)}</strong>
          : <span key={i}>{part}</span>
      )}
    </p>
  );
}

// ── Schema pill display ───────────────────────────────────────────────────────

function SchemaPills({ schema }: { schema: SchemaData | null }) {
  if (!schema || schema.columns.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-3">
      {schema.columns.map(col => (
        <span key={col}
          className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold tracking-wide
            ${schema.numeric_columns.includes(col)
              ? 'bg-cyan-900/30 border-cyan-700/40 text-cyan-300'
              : 'bg-violet-900/30 border-violet-700/40 text-violet-300'}`}>
          {col}
        </span>
      ))}
    </div>
  );
}



// ── Chat Section ──────────────────────────────────────────────────────────────

function ChatSection({ schema, schemaLoading }: {
  schema: SchemaData | null;
  schemaLoading: boolean;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const msgId = useRef(0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sampleQuestions = schema ? generateSampleQuestions(schema) : [];

  const sendQuestion = useCallback(async (questionText: string) => {
    const question = questionText.trim();
    if (!question || loading) return;
    setInput('');
    setLoading(true);

    const id = ++msgId.current;
    const loadingId = id + 0.5;

    setMessages(prev => [
      ...prev,
      { id, role: 'user', question, answer: question, cypher: null, results: null, grounded: false },
      { id: loadingId, role: 'assistant', question, answer: '', cypher: null, results: null, grounded: false, loading: true },
    ] as ChatMessage[]);

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, dataset_name: schema?.active_dataset }),
      });
      const data = await res.json();
      setMessages(prev => prev.map(m =>
        (m as { id: number }).id === loadingId
          ? {
              ...m,
              loading: false,
              answer: res.ok ? data.answer : (data.detail || 'Server error.'),
              cypher: data.cypher ?? null,
              results: data.results ?? null,
              grounded: res.ok ? data.grounded : false,
            }
          : m
      ));
    } catch (e: unknown) {
      setMessages(prev => prev.map(m =>
        (m as { id: number }).id === loadingId
          ? { ...m, loading: false, answer: e instanceof Error ? e.message : 'Cannot reach backend.', grounded: false }
          : m
      ));
    } finally {
      setLoading(false);
    }
  }, [loading, schema?.active_dataset]);

  const handleSubmit = (e: FormEvent) => { e.preventDefault(); sendQuestion(input); };

  return (
    <div className="flex flex-col bg-slate-900/60 backdrop-blur-xl border border-slate-800
      rounded-2xl shadow-2xl overflow-hidden" style={{ minHeight: '560px' }}>

      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between flex-shrink-0">
        <h2 className="text-sm font-bold text-slate-300 uppercase tracking-widest flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
          Graph Query Chat
        </h2>
        {schema && schema.datasets.length > 0 && (
          <select 
            value={schema.active_dataset || ''}
            onChange={async (e) => {
              if (e.target.value) {
                await fetch(`${API_URL}/datasets/${e.target.value}/activate`, { method: 'POST' });
                window.location.reload();
              }
            }}
            className="text-[10px] bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-slate-300 font-semibold tracking-wider outline-none focus:border-violet-500"
          >
            <option value="" disabled>Select Dataset...</option>
            {schema.datasets.map(ds => (
              <option key={ds} value={ds}>{ds}</option>
            ))}
          </select>
        )}
        {!schema?.datasets.length && (
          <span className="text-[10px] text-slate-500 font-semibold tracking-wider">
            Grounded · No LLM · Neo4j only
          </span>
        )}
      </div>

      {/* Schema pill strip */}
      {schema && schema.columns.length > 0 && (
        <div className="px-5 py-2.5 border-b border-slate-800/60 bg-slate-950/30 flex-shrink-0">
          <p className="text-[9px] font-bold text-slate-500 uppercase tracking-widest mb-1.5">
            Schema · {schema.active_dataset || 'No active dataset'}
          </p>
          <SchemaPills schema={schema} />
        </div>
      )}

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0" style={{ maxHeight: '400px' }}>
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full py-8 space-y-5">
            <div className="text-center space-y-2">
              <div className="w-12 h-12 mx-auto bg-slate-800 rounded-2xl flex items-center justify-center
                border border-slate-700 text-cyan-400">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
                  strokeWidth={1.5} stroke="currentColor" className="w-6 h-6">
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
                </svg>
              </div>
              {schemaLoading ? (
                <p className="text-xs text-slate-500 animate-pulse">Loading dataset schema…</p>
              ) : sampleQuestions.length > 0 ? (
                <>
                  <p className="text-sm font-semibold text-slate-300">Ask about your data</p>
                  <p className="text-xs text-slate-500">
                    Questions below are generated from your dataset&apos;s actual columns.
                  </p>
                </>
              ) : (
                <>
                  <p className="text-sm font-semibold text-slate-300">No dataset loaded yet</p>
                  <p className="text-xs text-slate-500">Upload a CSV to start querying.</p>
                </>
              )}
            </div>
            {/* Dynamic sample question pills */}
            {sampleQuestions.length > 0 && (
              <div className="flex flex-wrap justify-center gap-2 max-w-sm">
                {sampleQuestions.map(q => (
                  <button key={q} onClick={() => sendQuestion(q)}
                    className="text-xs px-3 py-1.5 rounded-full border border-slate-700
                      text-slate-400 hover:border-violet-600 hover:text-violet-300
                      hover:bg-violet-950/30 transition-all duration-150">
                    {q}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          messages.map(msg => (
            <div key={(msg as { id: number }).id}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-fadeIn`}>
              {msg.role === 'user' ? (
                <div className="max-w-[75%] bg-violet-600/30 border border-violet-700/40
                  rounded-2xl rounded-br-sm px-4 py-2.5 text-sm text-slate-100">
                  {msg.question}
                </div>
              ) : (
                <div className="max-w-[92%] space-y-1.5">
                  <div className="bg-slate-800/60 border border-slate-700/40
                    rounded-2xl rounded-bl-sm px-4 py-3">
                    {msg.loading ? <ThinkingIndicator /> : (
                      <div className="space-y-2">
                        <AnswerText text={msg.answer} />
                        <GroundedBadge grounded={msg.grounded} />
                      </div>
                    )}
                  </div>
                  {!msg.loading && (
                    <div className="px-1 space-y-1">
                      {msg.cypher && (
                        <Collapsible label="⚙ Cypher Query">
                          <pre className="text-[11px] text-cyan-300 whitespace-pre-wrap font-mono leading-relaxed">
                            {msg.cypher}
                          </pre>
                        </Collapsible>
                      )}
                      {msg.results && msg.results.length > 0 && (
                        <Collapsible label={`📊 Raw Results (${msg.results.length} records)`}>
                          <pre className="text-[11px] text-slate-300 whitespace-pre-wrap font-mono
                            overflow-auto max-h-48">
                            {JSON.stringify(msg.results, null, 2)}
                          </pre>
                        </Collapsible>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-slate-800 p-4 flex-shrink-0">
        <form onSubmit={handleSubmit} className="flex gap-2.5">
          <input
            id="chat-input"
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder={
              schema && schema.columns.length > 0
                ? `Ask about ${schema.columns.slice(0, 3).join(', ')}…`
                : 'Ask a question about your data…'
            }
            disabled={loading}
            className="flex-1 bg-slate-950/60 border border-slate-700 rounded-xl px-4 py-2.5
              text-sm text-slate-100 placeholder-slate-500 outline-none
              focus:border-violet-600 focus:ring-1 focus:ring-violet-600/30
              disabled:opacity-60 transition-colors"
          />
          <button id="send-button" type="submit"
            disabled={loading || !input.trim()}
            className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-violet-600 to-cyan-600
              hover:from-violet-500 hover:to-cyan-500 disabled:opacity-50
              text-white font-bold text-sm transition-all duration-200
              hover:-translate-y-px disabled:translate-y-0 flex-shrink-0">
            {loading ? (
              <svg className="w-4 h-4 animate-spin" xmlns="http://www.w3.org/2000/svg"
                fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10"
                  stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4Z" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
                strokeWidth={2} stroke="currentColor" className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M6 12 3.269 3.125A59.769 59.769 0 0 1 21.485 12 59.768 59.768 0 0 1 3.27 20.875L5.999 12Zm0 0h7.5" />
              </svg>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function Home() {
  const [schema, setSchema] = useState<SchemaData | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(true);

  const fetchSchema = useCallback(async () => {
    setSchemaLoading(true);
    try {
      const res = await fetch(`${API_URL}/schema`);
      if (res.ok) {
        const data: SchemaData = await res.json();
        setSchema(data);
      }
    } catch {
      // Backend not reachable yet — silently ignore
    } finally {
      setSchemaLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSchema();
  }, [fetchSchema]);

  return (
    <main className="min-h-[calc(100vh-65px)] bg-slate-950 text-slate-100 relative overflow-x-hidden font-sans pt-10">
      {/* Background gradients */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-40 -left-40 w-[600px] h-[600px] rounded-full
          bg-violet-900/15 blur-[140px]" />
        <div className="absolute -bottom-40 -right-40 w-[600px] h-[600px] rounded-full
          bg-cyan-900/15 blur-[140px]" />
      </div>

      <div className="relative z-10 max-w-6xl mx-auto px-6 py-10 space-y-8">
        {/* Header */}
        <div className="text-center space-y-2 pb-2">
          <h1 className="text-4xl md:text-5xl font-extrabold tracking-tight
            bg-clip-text text-transparent bg-gradient-to-r from-violet-400 via-purple-300 to-cyan-400">
            RAALE INGESTION
          </h1>
          <p className="text-sm text-slate-400 font-medium tracking-wide max-w-lg mx-auto">
            Upload any CSV → Stream through Kafka → Store in Neo4j → Query with grounded natural language
          </p>
        </div>

        {/* Single-column chat layout */}
        <div className="max-w-4xl mx-auto w-full">
          <ChatSection schema={schema} schemaLoading={schemaLoading} />
        </div>

        <p className="text-center text-[10px] text-slate-600 font-semibold uppercase tracking-wider">
          Milestone 2 — Schema-Aware Graph Query Engine · Zero Hallucination
        </p>
      </div>
    </main>
  );
}

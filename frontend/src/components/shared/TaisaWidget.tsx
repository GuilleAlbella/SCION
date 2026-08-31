"use client";

import { useState, useRef, useEffect } from "react";
import { Brain, Send, X, Minimize2, User, Bot, Sparkles, RotateCcw } from "lucide-react";
import { askQuestion } from "@/lib/api/reasoning";
import { useSelection } from "@/lib/SelectionContext";

/**
 * TAISA — floating AI chatbot widget. Three visual states driven by `open`
 * and `minimized`: closed (floating brain button), minimized (pill with
 * unread count), and fully expanded (chat panel). Rendered once globally
 * from the app root so conversation state survives page navigation.
 */
export default function TaisaWidget() {
  // ──── Widget visibility state ────
  const [open, setOpen] = useState(false);
  const [minimized, setMinimized] = useState(false);
  // ──── Chat state ────
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [chatHistory, setChatHistory] = useState<{ role: "user" | "taisa"; text: string }[]>([]);
  // Anchor at the end of the message list so we can auto-scroll on new content
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // We piggyback on the globally-selected diff to give TAISA a change_id
  // context — if the user is looking at a diff, questions target that change.
  const { cachedDiffDetails, activeChangeId } = useSelection();

  // Scroll to bottom on new message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, asking]);

  // Focus input when opened. The timeout gives the panel time to mount/animate
  // in before we try to focus — otherwise focus() fires on an unmounted input.
  useEffect(() => {
    if (open && !minimized) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [open, minimized]);

  async function handleSend() {
    // Guard against empty submissions and double-fire while a request is pending.
    if (!question.trim() || asking) return;
    const userMsg = question.trim();
    setQuestion("");
    // Optimistically append the user message so the UI feels instant — the
    // assistant reply comes in a later setState once the API resolves.
    setChatHistory((prev) => [...prev, { role: "user", text: userMsg }]);

    // Prefer the change the user scoped via "What next?" typeahead; fall back
    // to the first change in the cached diff, then to 1 as a generic anchor.
    const cid = activeChangeId ?? cachedDiffDetails?.changes?.[0]?.change_id ?? 1;
    setAsking(true);
    try {
      const data = await askQuestion(cid, userMsg, chatHistory);
      let text = data.answer;
      // The LLM sometimes returns a JSON envelope like {"explanation": "..."};
      // unwrap it for display. Plain-text answers stay as-is.
      try {
        const parsed = JSON.parse(text);
        if (typeof parsed === "object" && parsed.explanation) {
          text = parsed.explanation;
        }
      } catch { /* not JSON, good */ }
      setChatHistory((prev) => [...prev, { role: "taisa", text }]);
    } catch {
      setChatHistory((prev) => [...prev, { role: "taisa", text: "Sorry, I couldn't process that. Please try again." }]);
    } finally {
      setAsking(false);
    }
  }

  // ──── Collapsed states: floating button / minimized pill ────
  // Early returns keep the JSX for the full panel flat below.
  // Floating button when closed
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full bg-gradient-to-br from-td-navy to-td-navy-light shadow-lg shadow-td-navy/30 flex items-center justify-center hover:scale-110 transition-transform group"
      >
        <Brain size={24} className="text-td-orange group-hover:scale-110 transition-transform" />
        {/* Pulse ring */}
        <span className="absolute inset-0 rounded-full bg-td-orange/20 animate-ping" style={{ animationDuration: "3s" }} />
      </button>
    );
  }

  // Minimized pill
  if (minimized) {
    return (
      <button
        onClick={() => setMinimized(false)}
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 bg-td-navy text-white px-4 py-2.5 rounded-full shadow-lg hover:shadow-xl transition-all hover:scale-105"
      >
        <Brain size={16} className="text-td-orange" />
        <span className="text-xs font-medium">AI Assistant</span>
        {chatHistory.length > 0 && (
          <span className="bg-td-orange text-white text-[10px] font-bold w-5 h-5 rounded-full flex items-center justify-center">
            {chatHistory.filter(m => m.role === "taisa").length}
          </span>
        )}
      </button>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 w-96 h-[520px] rounded-2xl shadow-2xl shadow-black/20 overflow-hidden flex flex-col border border-slate-700 bg-white dark:bg-slate-900">
      {/* Header */}
      <div className="bg-gradient-to-r from-td-navy to-td-navy-light px-4 py-3 flex items-center gap-3 shrink-0">
        <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center">
          <Brain size={16} className="text-td-orange" />
        </div>
        <div className="flex-1">
          <div className="text-sm font-semibold text-white">AI Assistant</div>
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            <span className="text-[10px] text-green-400">Online — Ask anything about SCION</span>
          </div>
        </div>
        <button
          onClick={() => { setChatHistory([]); setQuestion(""); }}
          title="New session"
          className="text-white/50 hover:text-white p-1"
        >
          <RotateCcw size={14} />
        </button>
        <button onClick={() => setMinimized(true)} className="text-white/50 hover:text-white p-1">
          <Minimize2 size={14} />
        </button>
        <button onClick={() => { setOpen(false); setMinimized(false); }} className="text-white/50 hover:text-white p-1">
          <X size={14} />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 bg-gray-50 dark:bg-slate-900/50">
        {chatHistory.length === 0 && (
          <div className="text-center py-8">
            <div className="w-12 h-12 rounded-full bg-td-navy/10 dark:bg-white/5 flex items-center justify-center mx-auto mb-3">
              <Sparkles size={20} className="text-td-orange" />
            </div>
            <p className="text-xs text-td-gray-dark mb-1">AI Assistant</p>
            <p className="text-[11px] text-td-gray-dark/70 mb-4 px-4">
              I have full access to SCION data. Ask me about changes, impact, usage, risk, or anything else.
            </p>
            <div className="flex flex-col gap-1.5 px-4">
              {["What changed recently?", "Which tables are high risk?", "Summarize the current state"].map((q) => (
                <button
                  key={q}
                  onClick={() => setQuestion(q)}
                  className="text-[11px] bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-td-gray-dark px-3 py-2 rounded-lg hover:border-td-orange hover:text-td-orange transition-colors text-left"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {chatHistory.map((msg, i) => (
          <div key={i} className={`flex gap-2 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            {msg.role === "taisa" && (
              <div className="w-6 h-6 rounded-full bg-td-navy flex items-center justify-center shrink-0 mt-1">
                <Bot size={12} className="text-td-orange" />
              </div>
            )}
            <div
              className={`max-w-[80%] rounded-2xl px-3 py-2 text-xs leading-relaxed ${
                msg.role === "user"
                  ? "bg-td-navy text-white rounded-br-sm"
                  : "bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-700 dark:text-slate-300 rounded-bl-sm shadow-sm"
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.text}</p>
            </div>
            {msg.role === "user" && (
              <div className="w-6 h-6 rounded-full bg-td-orange/20 flex items-center justify-center shrink-0 mt-1">
                <User size={12} className="text-td-orange" />
              </div>
            )}
          </div>
        ))}

        {asking && (
          <div className="flex gap-2">
            <div className="w-6 h-6 rounded-full bg-td-navy flex items-center justify-center shrink-0">
              <Bot size={12} className="text-td-orange" />
            </div>
            <div className="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-2xl rounded-bl-sm px-3 py-2.5 shadow-sm">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-td-gray-dark/40 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 bg-td-gray-dark/40 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 bg-td-gray-dark/40 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-2.5 border-t border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 shrink-0">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="Ask anything about your data warehouse..."
            className="flex-1 border border-gray-200 dark:border-slate-600 rounded-full px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-td-navy/20 bg-gray-50 dark:bg-slate-800 dark:text-white"
          />
          <button
            onClick={handleSend}
            disabled={asking || !question.trim()}
            className="w-8 h-8 flex items-center justify-center bg-td-orange text-white rounded-full hover:bg-td-orange/90 disabled:opacity-50 transition-colors shrink-0"
          >
            <Send size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}

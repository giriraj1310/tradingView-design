import fs from "node:fs";
import path from "node:path";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function Home() {
  const md = fs.readFileSync(
    path.join(process.cwd(), "content", "design.md"),
    "utf8"
  );

  return (
    <main className="page">
      <header className="hero">
        <div className="tag">Engineering Design · Not Financial Advice</div>
        <h1>Automated Trading System</h1>
        <p className="subtitle">
          A practical, risk-first, auditable design — from research to
          backtesting to paper trading to live execution on Interactive Brokers
          (IBKR).
        </p>
      </header>
      <article className="markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
      </article>
      <footer className="footer">
        <p>
          Capital preservation is a first-class requirement. Backtested results
          do not predict live performance. Live behavior depends on changing
          market conditions.
        </p>
      </footer>
    </main>
  );
}

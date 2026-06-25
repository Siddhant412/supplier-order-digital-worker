import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  RefreshCw,
  Send,
  Upload,
} from "lucide-react";
import "./styles.css";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

const samples = {
  exact: `ISA*00*          *00*          *ZZ*ACME           *ZZ*BUYER          *260701*1200*^*00401*000000901*0*T*:~GS*PO*ACME*BUYER*20260701*1200*1*X*004010~ST*855*0001~BAK*00*AC*PO-1042*20260701~N1*SU*Acme Components*92*SUP-100~PO1*1*500*EA*12.00**BP*MOTOR-100*VP*ACME-M100~ACK*IA*500*EA*067*20260710~PO1*2*200*EA*8.50**BP*SENSOR-22*VP*ACME-S22~ACK*IA*200*EA*067*20260712~SE*9*0001~GE*1*1~IEA*1*000000901~`,
  risky: `ISA*00*          *00*          *ZZ*ACME           *ZZ*BUYER          *260701*1200*^*00401*000000902*0*T*:~GS*PO*ACME*BUYER*20260701*1200*2*X*004010~ST*855*0002~BAK*00*AC*PO-1042*20260701~N1*SU*Acme Components*92*SUP-100~PO1*1*500*EA*12.50**BP*MOTOR-100*VP*ACME-M100~ACK*IQ*450*EA*067*20260715~PO1*2*200*EA*8.50**BP*SENSOR-22*VP*ACME-S22~ACK*IA*200*EA*067*20260712~SE*9*0002~GE*1*2~IEA*1*000000902~`,
  qualifier: `ISA*00*          *00*          *ZZ*ACME           *ZZ*BUYER          *260701*1200*^*00401*000000903*0*T*:~GS*PO*ACME*BUYER*20260701*1200*3*X*004010~ST*855*0003~BAK*00*AC*PO-1042*20260701~N1*SU*Acme Components*92*SUP-100~PO1*1*500*EA*12.00**BP*MOTOR-100*VP*ACME-M100~ACK*IA*500*EA*999*20260710~SE*7*0003~GE*1*3~IEA*1*000000903~`,
};

function App() {
  const [ediText, setEdiText] = useState(samples.risky);
  const [workflows, setWorkflows] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selected = useMemo(
    () => workflows.find((workflow) => workflow.workflow_id === selectedId) ?? workflows[0],
    [workflows, selectedId],
  );

  async function fetchJson(path, options) {
    const response = await fetch(`${API_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail ?? response.statusText);
    }
    return response.json();
  }

  async function refresh() {
    const [workflowData, metricData] = await Promise.all([
      fetchJson("/api/workflows"),
      fetchJson("/api/metrics"),
    ]);
    setWorkflows(workflowData);
    setMetrics(metricData);
  }

  async function ingest() {
    setBusy(true);
    setError("");
    try {
      const workflow = await fetchJson("/api/ingest", {
        method: "POST",
        body: JSON.stringify({ edi_text: ediText }),
      });
      await refresh();
      setSelectedId(workflow.workflow_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const workflow = await fetchJson(`/api/workflows/${selected.workflow_id}/approve`, {
        method: "POST",
        body: JSON.stringify({
          approved_by: "operator@procureops.local",
          comments: "Approved from operations console.",
        }),
      });
      await refresh();
      setSelectedId(workflow.workflow_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, []);

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <ClipboardCheck size={22} />
          <div>
            <h1>ProcureOps AI</h1>
            <span>Supplier confirmations</span>
          </div>
        </div>

        <section className="panel compact">
          <div className="panel-title">
            <span>Workflows</span>
            <button className="icon-button" onClick={refresh} title="Refresh workflows">
              <RefreshCw size={16} />
            </button>
          </div>
          <div className="workflow-list">
            {workflows.length === 0 && <p className="muted">No workflows yet.</p>}
            {workflows.map((workflow) => (
              <button
                key={workflow.workflow_id}
                className={`workflow-row ${selected?.workflow_id === workflow.workflow_id ? "active" : ""}`}
                onClick={() => setSelectedId(workflow.workflow_id)}
              >
                <span>{workflow.confirmation?.purchase_order_number ?? "Unparsed"}</span>
                <StatusBadge status={workflow.status} />
              </button>
            ))}
          </div>
        </section>

        <section className="panel compact">
          <div className="panel-title">Metrics</div>
          <Metric label="Total" value={metrics?.total_workflows ?? 0} />
          <Metric label="Awaiting approval" value={metrics?.awaiting_approval ?? 0} />
          <Metric label="Manual review" value={metrics?.manual_review ?? 0} />
          <Metric label="False autonomous action rate" value={`${metrics?.false_autonomous_action_rate ?? 0}`} />
        </section>
      </aside>

      <section className="workspace">
        <section className="panel ingest-panel">
          <div className="panel-title">EDI Intake</div>
          <div className="sample-row">
            <button onClick={() => setEdiText(samples.exact)}>Exact match</button>
            <button onClick={() => setEdiText(samples.risky)}>Risky change</button>
            <button onClick={() => setEdiText(samples.qualifier)}>Unsupported qualifier</button>
          </div>
          <textarea value={ediText} onChange={(event) => setEdiText(event.target.value)} />
          <div className="action-row">
            <button className="primary-button" onClick={ingest} disabled={busy}>
              <Upload size={16} />
              Ingest EDI
            </button>
            {error && <span className="error-text">{error}</span>}
          </div>
        </section>

        {selected ? (
          <WorkflowDetail workflow={selected} onApprove={approve} busy={busy} />
        ) : (
          <section className="empty-state">
            <Send size={28} />
            <span>Ingest an EDI confirmation to start a governed workflow.</span>
          </section>
        )}
      </section>
    </main>
  );
}

function WorkflowDetail({ workflow, onApprove, busy }) {
  const differences = workflow.comparisons?.flatMap((comparison) =>
    comparison.differences.map((difference) => ({ ...difference, line_id: comparison.line_id })),
  );

  return (
    <section className="detail-grid">
      <section className="panel">
        <div className="detail-header">
          <div>
            <h2>{workflow.confirmation?.purchase_order_number ?? workflow.workflow_id}</h2>
            <p>{workflow.workflow_id}</p>
          </div>
          <StatusBadge status={workflow.status} />
        </div>
        <div className="summary-grid">
          <Metric label="Supplier" value={workflow.confirmation?.supplier_id ?? "-"} />
          <Metric label="Control" value={workflow.confirmation?.source_control_number ?? "-"} />
          <Metric label="Validation" value={workflow.confirmation?.validation_status ?? "-"} />
          <Metric label="Policy" value={workflow.policy_decision?.decision ?? "-"} />
        </div>
        {workflow.duplicate_of && (
          <div className="notice">
            <CheckCircle2 size={16} />
            Duplicate detected. Original workflow: {workflow.duplicate_of}
          </div>
        )}
        {workflow.status === "AWAITING_APPROVAL" && (
          <div className="approval-strip">
            <AlertTriangle size={18} />
            <span>ERP update is paused until approval is recorded.</span>
            <button className="primary-button" onClick={onApprove} disabled={busy}>
              <CheckCircle2 size={16} />
              Approve
            </button>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-title">Comparison</div>
        {differences.length === 0 ? (
          <p className="muted">No line differences detected.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Line</th>
                <th>Field</th>
                <th>Original</th>
                <th>Confirmed</th>
                <th>Severity</th>
              </tr>
            </thead>
            <tbody>
              {differences.map((difference, index) => (
                <tr key={`${difference.line_id}-${difference.field}-${index}`}>
                  <td>{difference.line_id}</td>
                  <td>{difference.field}</td>
                  <td>{formatValue(difference.original)}</td>
                  <td>{formatValue(difference.confirmed)}</td>
                  <td>{difference.severity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <div className="panel-title">Impact</div>
        {(workflow.impacts ?? []).map((impact) => (
          <div className="impact-row" key={impact.line_id}>
            <strong>Line {impact.line_id}</strong>
            <span>{impact.recommendation}</span>
            <small>
              Shortage: {impact.projected_shortage_quantity} | Financial variance: $
              {impact.financial_variance}
            </small>
          </div>
        ))}
      </section>

      <section className="panel">
        <div className="panel-title">Audit Timeline</div>
        <div className="timeline">
          {(workflow.audit_events ?? []).map((event) => (
            <div className="timeline-event" key={`${event.event_type}-${event.occurred_at}`}>
              <strong>{event.event_type}</strong>
              <span>{event.summary}</span>
              <small>{new Date(event.occurred_at).toLocaleString()}</small>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}

function StatusBadge({ status }) {
  const tone = status === "COMPLETED" ? "success" : status === "AWAITING_APPROVAL" ? "warning" : "neutral";
  return <span className={`status-badge ${tone}`}>{status}</span>;
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatValue(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return value;
}

createRoot(document.getElementById("root")).render(<App />);

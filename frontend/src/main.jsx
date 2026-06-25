import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FileCog,
  FlaskConical,
  RefreshCw,
  Save,
  Send,
  Upload,
} from "lucide-react";
import "./styles.css";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

const samples = {
  exact: `ISA*00*          *00*          *ZZ*ACME           *ZZ*BUYER          *260701*1200*^*00401*000000901*0*T*:~GS*PO*ACME*BUYER*20260701*1200*1*X*004010~ST*855*0001~BAK*00*AC*PO-1042*20260701~N1*SU*Acme Components*92*SUP-100~PO1*1*500*EA*12.00**BP*MOTOR-100*VP*ACME-M100~ACK*IA*500*EA*067*20260710~PO1*2*200*EA*8.50**BP*SENSOR-22*VP*ACME-S22~ACK*IA*200*EA*067*20260712~SE*9*0001~GE*1*1~IEA*1*000000901~`,
  smallDelay: `ISA*00*          *00*          *ZZ*ACME           *ZZ*BUYER          *260701*1200*^*00401*000000905*0*T*:~GS*PO*ACME*BUYER*20260701*1200*5*X*004010~ST*855*0005~BAK*00*AC*PO-1042*20260701~N1*SU*Acme Components*92*SUP-100~PO1*2*200*EA*8.50**BP*SENSOR-22*VP*ACME-S22~ACK*IA*200*EA*067*20260714~SE*7*0005~GE*1*5~IEA*1*000000905~`,
  risky: `ISA*00*          *00*          *ZZ*ACME           *ZZ*BUYER          *260701*1200*^*00401*000000902*0*T*:~GS*PO*ACME*BUYER*20260701*1200*2*X*004010~ST*855*0002~BAK*00*AC*PO-1042*20260701~N1*SU*Acme Components*92*SUP-100~PO1*1*500*EA*12.50**BP*MOTOR-100*VP*ACME-M100~ACK*IQ*450*EA*067*20260715~PO1*2*200*EA*8.50**BP*SENSOR-22*VP*ACME-S22~ACK*IA*200*EA*067*20260712~SE*9*0002~GE*1*2~IEA*1*000000902~`,
  qualifier: `ISA*00*          *00*          *ZZ*ACME           *ZZ*BUYER          *260701*1200*^*00401*000000903*0*T*:~GS*PO*ACME*BUYER*20260701*1200*3*X*004010~ST*855*0003~BAK*00*AC*PO-1042*20260701~N1*SU*Acme Components*92*SUP-100~PO1*1*500*EA*12.00**BP*MOTOR-100*VP*ACME-M100~ACK*IA*500*EA*999*20260710~SE*7*0003~GE*1*3~IEA*1*000000903~`,
};

function App() {
  const [ediText, setEdiText] = useState(samples.risky);
  const [workflows, setWorkflows] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [evaluationRuns, setEvaluationRuns] = useState([]);
  const [selectedProfileId, setSelectedProfileId] = useState(null);
  const [selectedPolicyId, setSelectedPolicyId] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selected = useMemo(
    () => workflows.find((workflow) => workflow.workflow_id === selectedId) ?? workflows[0],
    [workflows, selectedId],
  );
  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.profile_id === selectedProfileId) ?? profiles[0],
    [profiles, selectedProfileId],
  );
  const selectedPolicy = useMemo(
    () => policies.find((policy) => policy.policy_id === selectedPolicyId) ?? policies[0],
    [policies, selectedPolicyId],
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
    const [workflowData, metricData, profileData, policyData, evaluationData] = await Promise.all([
      fetchJson("/api/workflows"),
      fetchJson("/api/metrics"),
      fetchJson("/api/profiles"),
      fetchJson("/api/policies"),
      fetchJson("/api/evaluations/runs"),
    ]);
    setWorkflows(workflowData);
    setMetrics(metricData);
    setProfiles(profileData);
    setPolicies(policyData);
    setEvaluationRuns(evaluationData);
    if (!selectedProfileId && profileData.length > 0) {
      setSelectedProfileId(profileData[0].profile_id);
    }
    if (!selectedPolicyId && policyData.length > 0) {
      const activePolicy = policyData.find((policy) => policy.status === "PUBLISHED") ?? policyData[0];
      setSelectedPolicyId(activePolicy.policy_id);
    }
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

  async function saveProfile(profileId, payload) {
    setBusy(true);
    setError("");
    try {
      const profile = await fetchJson(`/api/profiles/${encodeURIComponent(profileId)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      await refresh();
      setSelectedProfileId(profile.profile_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function publishProfile(profileId) {
    setBusy(true);
    setError("");
    try {
      const profile = await fetchJson(`/api/profiles/${encodeURIComponent(profileId)}/publish`, {
        method: "POST",
      });
      await refresh();
      setSelectedProfileId(profile.profile_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function archiveProfile(profileId) {
    setBusy(true);
    setError("");
    try {
      const profile = await fetchJson(`/api/profiles/${encodeURIComponent(profileId)}/archive`, {
        method: "POST",
      });
      await refresh();
      setSelectedProfileId(profile.profile_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function savePolicy(policyId, payload) {
    setBusy(true);
    setError("");
    try {
      const policy = await fetchJson(`/api/policies/${encodeURIComponent(policyId)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      await refresh();
      setSelectedPolicyId(policy.policy_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function publishPolicy(policyId) {
    setBusy(true);
    setError("");
    try {
      const policy = await fetchJson(`/api/policies/${encodeURIComponent(policyId)}/publish`, {
        method: "POST",
      });
      await refresh();
      setSelectedPolicyId(policy.policy_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function archivePolicy(policyId) {
    setBusy(true);
    setError("");
    try {
      const policy = await fetchJson(`/api/policies/${encodeURIComponent(policyId)}/archive`, {
        method: "POST",
      });
      await refresh();
      setSelectedPolicyId(policy.policy_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function runEvaluations() {
    setBusy(true);
    setError("");
    try {
      await fetchJson("/api/evaluations/run", {
        method: "POST",
      });
      await refresh();
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
            <button onClick={() => setEdiText(samples.smallDelay)}>Small delay</button>
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

        <ProfileManager
          profiles={profiles}
          selectedProfile={selectedProfile}
          onSelect={setSelectedProfileId}
          onSave={saveProfile}
          onPublish={publishProfile}
          onArchive={archiveProfile}
          busy={busy}
        />

        <PolicyManager
          policies={policies}
          selectedPolicy={selectedPolicy}
          onSelect={setSelectedPolicyId}
          onSave={savePolicy}
          onPublish={publishPolicy}
          onArchive={archivePolicy}
          busy={busy}
        />

        <EvaluationDashboard runs={evaluationRuns} onRun={runEvaluations} busy={busy} />
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
  const tone =
    status === "COMPLETED" || status === "PUBLISHED"
      || status === "PASSED"
      ? "success"
      : status === "AWAITING_APPROVAL" || status === "DRAFT"
        || status === "FAILED"
        ? "warning"
        : "neutral";
  return <span className={`status-badge ${tone}`}>{status}</span>;
}

function ProfileManager({ profiles, selectedProfile, onSelect, onSave, onPublish, onArchive, busy }) {
  const [dateQualifierJson, setDateQualifierJson] = useState("{}");
  const [ackCodeJson, setAckCodeJson] = useState("{}");
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (!selectedProfile) return;
    setDateQualifierJson(JSON.stringify(selectedProfile.date_qualifiers ?? {}, null, 2));
    setAckCodeJson(JSON.stringify(selectedProfile.ack_codes ?? {}, null, 2));
    setLocalError("");
  }, [selectedProfile?.profile_id]);

  function save() {
    if (!selectedProfile) return;
    try {
      const dateQualifiers = JSON.parse(dateQualifierJson);
      const ackCodes = JSON.parse(ackCodeJson);
      setLocalError("");
      onSave(selectedProfile.profile_id, {
        date_qualifiers: dateQualifiers,
        ack_codes: ackCodes,
        repeated_ack_policy: selectedProfile.repeated_ack_policy,
        unknown_qualifier_policy: selectedProfile.unknown_qualifier_policy,
      });
    } catch {
      setLocalError("Mappings must be valid JSON objects.");
    }
  }

  return (
    <section className="panel profile-panel">
      <div className="panel-title">
        <span>Trading Partner Profiles</span>
        <FileCog size={18} />
      </div>
      <div className="profile-grid">
        <div className="profile-list">
          {profiles.map((profile) => (
            <button
              key={profile.profile_id}
              className={`profile-row ${selectedProfile?.profile_id === profile.profile_id ? "active" : ""}`}
              onClick={() => onSelect(profile.profile_id)}
            >
              <span>{profile.supplier_id}</span>
              <small>
                {profile.transaction_type} / {profile.edi_version} / v{profile.version}
              </small>
              <StatusBadge status={profile.status} />
            </button>
          ))}
        </div>

        {selectedProfile ? (
          <div className="profile-editor">
            <div className="profile-editor-header">
              <div>
                <strong>{selectedProfile.profile_id}</strong>
                <span>
                  {selectedProfile.supplier_id} / {selectedProfile.transaction_type} /{" "}
                  {selectedProfile.edi_version}
                </span>
              </div>
              <StatusBadge status={selectedProfile.status} />
            </div>

            <label>
              Date qualifier mappings
              <textarea
                className="mapping-editor"
                value={dateQualifierJson}
                onChange={(event) => setDateQualifierJson(event.target.value)}
              />
            </label>

            <label>
              ACK code mappings
              <textarea
                className="mapping-editor"
                value={ackCodeJson}
                onChange={(event) => setAckCodeJson(event.target.value)}
              />
            </label>

            <div className="action-row">
              <button onClick={save} disabled={busy}>
                <Save size={16} />
                Save draft
              </button>
              {selectedProfile.status === "DRAFT" && (
                <button className="primary-button" onClick={() => onPublish(selectedProfile.profile_id)} disabled={busy}>
                  <CheckCircle2 size={16} />
                  Publish
                </button>
              )}
              {selectedProfile.status !== "ARCHIVED" && (
                <button onClick={() => onArchive(selectedProfile.profile_id)} disabled={busy}>
                  Archive
                </button>
              )}
              {localError && <span className="error-text">{localError}</span>}
            </div>
          </div>
        ) : (
          <p className="muted">No trading partner profiles available.</p>
        )}
      </div>
    </section>
  );
}

function PolicyManager({ policies, selectedPolicy, onSelect, onSave, onPublish, onArchive, busy }) {
  const [draft, setDraft] = useState(null);

  useEffect(() => {
    if (!selectedPolicy) return;
    setDraft({
      exact_match_auto_approve: selectedPolicy.exact_match_auto_approve,
      maximum_price_increase_percent: selectedPolicy.maximum_price_increase_percent,
      maximum_delivery_delay_days: selectedPolicy.maximum_delivery_delay_days,
      maximum_order_value: selectedPolicy.maximum_order_value,
      require_no_stockout_impact: selectedPolicy.require_no_stockout_impact,
      policy_version: selectedPolicy.policy_version,
    });
  }, [selectedPolicy?.policy_id]);

  function updateField(field, value) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  function save() {
    if (!selectedPolicy || !draft) return;
    onSave(selectedPolicy.policy_id, draft);
  }

  return (
    <section className="panel policy-panel">
      <div className="panel-title">
        <span>Approval Policies</span>
        <CheckCircle2 size={18} />
      </div>
      <div className="policy-grid">
        <div className="policy-list">
          {policies.map((policy) => (
            <button
              key={policy.policy_id}
              className={`policy-row ${selectedPolicy?.policy_id === policy.policy_id ? "active" : ""}`}
              onClick={() => onSelect(policy.policy_id)}
            >
              <span>{policy.policy_id}</span>
              <small>
                {policy.policy_version} / v{policy.version}
              </small>
              <StatusBadge status={policy.status} />
            </button>
          ))}
        </div>

        {selectedPolicy && draft ? (
          <div className="policy-editor">
            <div className="policy-editor-header">
              <div>
                <strong>{selectedPolicy.policy_id}</strong>
                <span>Only published policies are used by workflow execution.</span>
              </div>
              <StatusBadge status={selectedPolicy.status} />
            </div>

            <div className="policy-form">
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={draft.exact_match_auto_approve}
                  onChange={(event) => updateField("exact_match_auto_approve", event.target.checked)}
                />
                Auto-confirm exact matches
              </label>

              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={draft.require_no_stockout_impact}
                  onChange={(event) => updateField("require_no_stockout_impact", event.target.checked)}
                />
                Require no stockout impact for auto-confirmation
              </label>

              <label>
                Policy version label
                <input
                  value={draft.policy_version}
                  onChange={(event) => updateField("policy_version", event.target.value)}
                />
              </label>

              <label>
                Maximum price increase %
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={draft.maximum_price_increase_percent}
                  onChange={(event) =>
                    updateField("maximum_price_increase_percent", Number(event.target.value))
                  }
                />
              </label>

              <label>
                Maximum delivery delay days
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={draft.maximum_delivery_delay_days}
                  onChange={(event) => updateField("maximum_delivery_delay_days", Number(event.target.value))}
                />
              </label>

              <label>
                Maximum order value
                <input
                  type="number"
                  min="0"
                  step="100"
                  value={draft.maximum_order_value}
                  onChange={(event) => updateField("maximum_order_value", Number(event.target.value))}
                />
              </label>
            </div>

            <div className="action-row">
              <button onClick={save} disabled={busy}>
                <Save size={16} />
                Save draft
              </button>
              {selectedPolicy.status === "DRAFT" && (
                <button className="primary-button" onClick={() => onPublish(selectedPolicy.policy_id)} disabled={busy}>
                  <CheckCircle2 size={16} />
                  Publish
                </button>
              )}
              {selectedPolicy.status !== "ARCHIVED" && (
                <button onClick={() => onArchive(selectedPolicy.policy_id)} disabled={busy}>
                  Archive
                </button>
              )}
            </div>
          </div>
        ) : (
          <p className="muted">No approval policies available.</p>
        )}
      </div>
    </section>
  );
}

function EvaluationDashboard({ runs, onRun, busy }) {
  const latestRun = runs[0];

  return (
    <section className="panel evaluation-panel">
      <div className="panel-title">
        <span>Evaluation Runs</span>
        <FlaskConical size={18} />
      </div>
      <div className="evaluation-header">
        <div className="summary-grid">
          <Metric label="Latest status" value={latestRun?.status ?? "-"} />
          <Metric label="Passed" value={latestRun?.passed ?? 0} />
          <Metric label="Failed" value={latestRun?.failed ?? 0} />
          <Metric label="Total" value={latestRun?.total ?? 0} />
        </div>
        <button className="primary-button" onClick={onRun} disabled={busy}>
          <FlaskConical size={16} />
          Run scenarios
        </button>
      </div>

      {latestRun ? (
        <div className="evaluation-results">
          {latestRun.results.map((result) => (
            <div className={`scenario-result ${result.status === "PASSED" ? "passed" : "failed"}`} key={result.scenario_id}>
              <div className="scenario-title">
                <strong>{result.name}</strong>
                <StatusBadge status={result.status} />
              </div>
              <div className="scenario-fields">
                <span>Workflow: {result.workflow_id ?? "-"}</span>
                <span>Expected status: {result.expected.workflow_status}</span>
                <span>Actual status: {result.actual.workflow_status}</span>
                <span>Expected policy: {result.expected.policy_decision ?? "-"}</span>
                <span>Actual policy: {result.actual.policy_decision ?? "-"}</span>
              </div>
              {result.mismatches.length > 0 && (
                <ul className="mismatch-list">
                  {result.mismatches.map((mismatch) => (
                    <li key={mismatch}>{mismatch}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">No evaluation runs yet.</p>
      )}
    </section>
  );
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

import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  FlaskConical,
  GitBranch,
  HelpCircle,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Send,
  Upload,
  XCircle,
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
  const [workflowStatusFilter, setWorkflowStatusFilter] = useState("needs_attention");
  const [workflowQuery, setWorkflowQuery] = useState("");
  const [workflowSort, setWorkflowSort] = useState("priority");
  const [executionTrace, setExecutionTrace] = useState([]);
  const [traceLoading, setTraceLoading] = useState(false);
  const [metrics, setMetrics] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const filteredWorkflows = useMemo(() => {
    const query = workflowQuery.trim().toLowerCase();
    return workflows
      .filter((workflow) => workflowMatchesStatus(workflow, workflowStatusFilter))
      .filter((workflow) => workflowSearchText(workflow).includes(query))
      .sort((left, right) => {
        if (workflowSort === "newest") {
          return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
        }
        return workflowRiskScore(right) - workflowRiskScore(left)
          || new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
      });
  }, [workflows, workflowStatusFilter, workflowQuery, workflowSort]);

  const selected = useMemo(
    () => workflows.find((workflow) => workflow.workflow_id === selectedId) ?? filteredWorkflows[0] ?? workflows[0],
    [workflows, filteredWorkflows, selectedId],
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

  async function submitWorkflowDecision(endpoint, payload) {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const workflow = await fetchJson(`/api/workflows/${selected.workflow_id}/${endpoint}`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await refresh();
      setSelectedId(workflow.workflow_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function retryNotification() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const workflow = await fetchJson(`/api/workflows/${selected.workflow_id}/retry-notification`, {
        method: "POST",
      });
      await refresh();
      setSelectedId(workflow.workflow_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function generateBrief() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await fetchJson(`/api/workflows/${selected.workflow_id}/brief`, {
        method: "POST",
      });
      await refresh();
      setSelectedId(selected.workflow_id);
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

  async function createProfile(payload) {
    setBusy(true);
    setError("");
    try {
      const profile = await fetchJson("/api/profiles", {
        method: "POST",
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

  async function createPolicy(payload) {
    setBusy(true);
    setError("");
    try {
      const policy = await fetchJson("/api/policies", {
        method: "POST",
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

  async function reprocessWorkflow() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const workflow = await fetchJson(`/api/workflows/${selected.workflow_id}/reprocess`, {
        method: "POST",
      });
      await refresh();
      setSelectedId(workflow.workflow_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function resetMockErp() {
    setBusy(true);
    setError("");
    try {
      await fetchJson("/api/mock-erp/reset", {
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

  useEffect(() => {
    if (!selected?.workflow_id) {
      setExecutionTrace([]);
      return;
    }
    let cancelled = false;
    setTraceLoading(true);
    fetchJson(`/api/workflows/${selected.workflow_id}/execution-trace`)
      .then((trace) => {
        if (!cancelled) {
          setExecutionTrace(trace);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
          setExecutionTrace([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setTraceLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.workflow_id, selected?.updated_at]);

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
          <div className="workflow-controls">
            <label className="workflow-search">
              <Search size={15} />
              <input
                value={workflowQuery}
                onChange={(event) => setWorkflowQuery(event.target.value)}
                placeholder="Search PO, supplier, workflow"
              />
            </label>
            <div className="workflow-select-row">
              <select value={workflowStatusFilter} onChange={(event) => setWorkflowStatusFilter(event.target.value)}>
                <option value="needs_attention">Needs attention</option>
                <option value="all">All statuses</option>
                <option value="AWAITING_APPROVAL">Awaiting approval</option>
                <option value="MANUAL_REVIEW">Manual review</option>
                <option value="DEAD_LETTER">Dead letter</option>
                <option value="RETRY_PENDING">Retry pending</option>
                <option value="COMPLETED">Completed</option>
                <option value="REJECTED">Rejected</option>
                <option value="CLARIFICATION_REQUESTED">Clarification</option>
              </select>
              <select value={workflowSort} onChange={(event) => setWorkflowSort(event.target.value)}>
                <option value="priority">Priority</option>
                <option value="newest">Newest</option>
              </select>
            </div>
          </div>
          <div className="workflow-list">
            {workflows.length === 0 && <p className="muted">No workflows yet.</p>}
            {workflows.length > 0 && filteredWorkflows.length === 0 && <p className="muted">No matching workflows.</p>}
            {filteredWorkflows.map((workflow) => (
              <button
                key={workflow.workflow_id}
                className={`workflow-row ${selected?.workflow_id === workflow.workflow_id ? "active" : ""}`}
                onClick={() => setSelectedId(workflow.workflow_id)}
              >
                <span className="workflow-main">
                  <strong>{workflow.confirmation?.purchase_order_number ?? "Unparsed"}</strong>
                  <small>
                    {workflow.confirmation?.supplier_id ?? "-"} / {workflow.confirmation?.source_control_number ?? workflow.workflow_id}
                  </small>
                </span>
                <StatusBadge status={workflow.status} />
              </button>
            ))}
          </div>
        </section>

        <section className="panel compact">
          <div className="panel-title">Metrics</div>
          <Metric label="Total" value={metrics?.total_workflows ?? 0} />
          <Metric label="Completed" value={metrics?.completed ?? 0} />
          <Metric label="Awaiting approval" value={metrics?.awaiting_approval ?? 0} />
          <Metric label="Manual review" value={metrics?.manual_review ?? 0} />
          <Metric label="Retry pending" value={metrics?.retry_pending ?? 0} />
          <Metric label="Dead letter" value={metrics?.dead_letter ?? 0} />
          <Metric label="Failed notifications" value={metrics?.failed_notifications ?? 0} />
          <Metric label="Retry recovery rate" value={formatRate(metrics?.retry_recovery_rate)} />
          <Metric label="LLM fallback rate" value={formatRate(metrics?.llm_fallback_rate)} />
          <Metric label="Avg duration" value={formatSeconds(metrics?.average_workflow_duration_seconds)} />
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
          <WorkflowDetail
            workflow={selected}
            executionTrace={executionTrace}
            traceLoading={traceLoading}
            onApprove={(payload) => submitWorkflowDecision("approve", payload)}
            onReject={(payload) => submitWorkflowDecision("reject", payload)}
            onClarify={(payload) => submitWorkflowDecision("request-clarification", payload)}
            onRetryNotification={retryNotification}
            onGenerateBrief={generateBrief}
            onReprocess={reprocessWorkflow}
            busy={busy}
          />
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
          onCreate={createProfile}
          onSave={saveProfile}
          onPublish={publishProfile}
          onArchive={archiveProfile}
          busy={busy}
        />

        <PolicyManager
          policies={policies}
          selectedPolicy={selectedPolicy}
          onSelect={setSelectedPolicyId}
          onCreate={createPolicy}
          onSave={savePolicy}
          onPublish={publishPolicy}
          onArchive={archivePolicy}
          busy={busy}
        />

        <EvaluationDashboard runs={evaluationRuns} onRun={runEvaluations} onResetMockErp={resetMockErp} busy={busy} />
      </section>
    </main>
  );
}

function WorkflowDetail({
  workflow,
  executionTrace,
  traceLoading,
  onApprove,
  onReject,
  onClarify,
  onRetryNotification,
  onGenerateBrief,
  onReprocess,
  busy,
}) {
  const differences = workflow.comparisons?.flatMap((comparison) =>
    comparison.differences.map((difference) => ({ ...difference, line_id: comparison.line_id })),
  );
  const canApprove = workflow.status === "AWAITING_APPROVAL";
  const canResolveManual = workflow.status === "MANUAL_REVIEW" || workflow.status === "DEAD_LETTER";
  const showDecisionPanel = canApprove || canResolveManual;
  const findings = [
    ...(workflow.parse_result?.errors ?? []).map((message) => ({ kind: "Parse error", message })),
    ...(workflow.confirmation?.errors ?? []).map((message) => ({ kind: "Semantic error", message })),
    ...(workflow.parse_result?.warnings ?? []).map((message) => ({ kind: "Parse warning", message })),
    ...(workflow.confirmation?.warnings ?? []).map((message) => ({ kind: "Semantic warning", message })),
  ];
  const [decisionMode, setDecisionMode] = useState("approve");
  const [comments, setComments] = useState("");
  const [responseSubject, setResponseSubject] = useState("");
  const [responseBody, setResponseBody] = useState("");
  const [auditTypeFilter, setAuditTypeFilter] = useState("all");
  const [auditActorFilter, setAuditActorFilter] = useState("all");
  const [auditQuery, setAuditQuery] = useState("");
  const auditEvents = workflow.audit_events ?? [];
  const auditTypes = Array.from(new Set(auditEvents.map((event) => event.event_type))).sort();
  const filteredAuditEvents = auditEvents.filter((event) => {
    const query = auditQuery.trim().toLowerCase();
    const matchesType = auditTypeFilter === "all" || event.event_type === auditTypeFilter;
    const matchesActor = auditActorFilter === "all" || event.actor_type === auditActorFilter;
    const matchesQuery = !query || auditSearchText(event).includes(query);
    return matchesType && matchesActor && matchesQuery;
  });

  useEffect(() => {
    const allowedModes = canApprove ? ["approve", "clarification", "reject"] : ["clarification", "reject"];
    const nextMode = allowedModes.includes(decisionMode) ? decisionMode : "clarification";
    if (nextMode !== decisionMode) {
      setDecisionMode(nextMode);
      return;
    }
    setComments("");
    const response = defaultSupplierResponse(workflow, nextMode);
    setResponseSubject(response.subject);
    setResponseBody(response.body);
  }, [workflow.workflow_id, decisionMode, canApprove]);

  function submitDecision() {
    if (decisionMode === "approve" && !canApprove) return;
    const payload = {
      approved_by: "operator@procureops.local",
      comments,
      supplier_response_subject: responseSubject,
      supplier_response_body: responseBody,
    };
    if (decisionMode === "reject") {
      onReject(payload);
    } else if (decisionMode === "clarification") {
      onClarify(payload);
    } else {
      onApprove(payload);
    }
  }

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
        {findings.length > 0 && (
          <section className="finding-panel">
            <strong>Review findings</strong>
            <div className="finding-list">
              {findings.map((finding, index) => (
                <div className="finding-row" key={`${finding.kind}-${finding.message}-${index}`}>
                  <span>{finding.kind}</span>
                  <small>{finding.message}</small>
                </div>
              ))}
            </div>
          </section>
        )}
        {showDecisionPanel && (
          <section className="approval-panel">
            <div className="approval-strip">
              <AlertTriangle size={18} />
              <span>
                {canApprove
                  ? "ERP update is paused until approval is recorded."
                  : "Workflow requires manual resolution before any operational action."}
              </span>
            </div>
            <div className="decision-mode-row">
              {canApprove && (
                <button
                  className={decisionMode === "approve" ? "active" : ""}
                  onClick={() => setDecisionMode("approve")}
                >
                  <CheckCircle2 size={16} />
                  Approve
                </button>
              )}
              <button
                className={decisionMode === "clarification" ? "active" : ""}
                onClick={() => setDecisionMode("clarification")}
              >
                <HelpCircle size={16} />
                Clarify
              </button>
              <button
                className={decisionMode === "reject" ? "active" : ""}
                onClick={() => setDecisionMode("reject")}
              >
                <XCircle size={16} />
                Reject
              </button>
            </div>
            <div className="approval-form">
              <label>
                Decision comments
                <textarea
                  className="decision-textarea"
                  value={comments}
                  onChange={(event) => setComments(event.target.value)}
                />
              </label>
              <label>
                Supplier subject
                <input value={responseSubject} onChange={(event) => setResponseSubject(event.target.value)} />
              </label>
              <label>
                Supplier message
                <textarea
                  className="decision-textarea"
                  value={responseBody}
                  onChange={(event) => setResponseBody(event.target.value)}
                />
              </label>
            </div>
            <div className="action-row">
              <button
                className={decisionMode === "reject" ? "danger-button" : "primary-button"}
                onClick={submitDecision}
                disabled={busy}
              >
                {decisionMode === "reject" ? <XCircle size={16} /> : decisionMode === "clarification" ? <HelpCircle size={16} /> : <CheckCircle2 size={16} />}
                {decisionMode === "clarification"
                  ? "Request clarification"
                  : decisionMode === "reject"
                    ? "Reject"
                  : "Approve"}
              </button>
              {canResolveManual && (
                <button onClick={onReprocess} disabled={busy}>
                  <RotateCcw size={16} />
                  Reprocess
                </button>
              )}
            </div>
          </section>
        )}
        {workflow.status === "RETRY_PENDING" && workflow.supplier_response?.status === "failed" && (
          <div className="approval-strip">
            <AlertTriangle size={18} />
            <span>Supplier notification failed after prior workflow steps completed.</span>
            <button className="primary-button" onClick={onRetryNotification} disabled={busy}>
              <RefreshCw size={16} />
              Retry notification
            </button>
          </div>
        )}
      </section>

      <ExecutionTracePanel trace={executionTrace} loading={traceLoading} />

      <RiskInvestigationPanel investigation={workflow.risk_investigation} />

      <section className="panel">
        <div className="panel-title">
          <span>Operator Brief</span>
          <button className="primary-button" onClick={onGenerateBrief} disabled={busy} title="Generate operator brief">
            <FileText size={16} />
            Generate
          </button>
        </div>
        {workflow.operator_brief ? (
          <div className="brief-grid">
            <BriefField label="Summary" value={workflow.operator_brief.summary} />
            <BriefField label="Risk" value={workflow.operator_brief.risk_assessment} />
            <BriefField label="Action" value={workflow.operator_brief.recommended_action} />
            <BriefField label="Supplier draft" value={workflow.operator_brief.supplier_message_draft} />
            <small>
              Source: {workflow.operator_brief.source}
              {workflow.operator_brief.model ? ` / ${workflow.operator_brief.model}` : ""}
            </small>
          </div>
        ) : (
          <p className="muted">No brief generated.</p>
        )}
      </section>

      <LineComparisonDetail workflow={workflow} />

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

      <ErpUpdateSnapshot workflow={workflow} />

      <section className="panel">
        <div className="panel-title">Supplier Response</div>
        {workflow.supplier_response ? (
          <div className="supplier-response">
            <strong>{workflow.supplier_response.subject}</strong>
            <span>{workflow.supplier_response.body}</span>
            <small>Status: {workflow.supplier_response.status}</small>
          </div>
        ) : (
          <p className="muted">No supplier response sent.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-title">Decision History</div>
        {(workflow.approval_history ?? []).length > 0 ? (
          <div className="history-list">
            {workflow.approval_history.map((approval, index) => (
              <div className="history-row" key={`${approval.decision}-${approval.approved_at}-${index}`}>
                <strong>{approval.decision}</strong>
                <span>{approval.comments || "-"}</span>
                <small>
                  {approval.approved_by} / {new Date(approval.approved_at).toLocaleString()}
                </small>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">No human decision recorded.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-title">Audit Timeline</div>
        <div className="audit-controls">
          <label className="workflow-search">
            <Search size={15} />
            <input
              value={auditQuery}
              onChange={(event) => setAuditQuery(event.target.value)}
              placeholder="Search audit"
            />
          </label>
          <select value={auditTypeFilter} onChange={(event) => setAuditTypeFilter(event.target.value)}>
            <option value="all">All event types</option>
            {auditTypes.map((eventType) => (
              <option value={eventType} key={eventType}>
                {eventType}
              </option>
            ))}
          </select>
          <select value={auditActorFilter} onChange={(event) => setAuditActorFilter(event.target.value)}>
            <option value="all">All actors</option>
            <option value="system">System</option>
            <option value="user">User</option>
          </select>
        </div>
        <div className="timeline">
          {filteredAuditEvents.map((event) => (
            <div className="timeline-event" key={event.event_id ?? `${event.event_type}-${event.occurred_at}`}>
              <strong>{event.event_type}</strong>
              <span>{event.summary}</span>
              <small>
                {event.actor_type} / {new Date(event.occurred_at).toLocaleString()}
              </small>
              {event.metadata && Object.keys(event.metadata).length > 0 && (
                <details>
                  <summary>Metadata</summary>
                  <pre>{JSON.stringify(event.metadata, null, 2)}</pre>
                </details>
              )}
            </div>
          ))}
          {filteredAuditEvents.length === 0 && <p className="muted">No audit events match the current filters.</p>}
        </div>
      </section>
    </section>
  );
}

function RiskInvestigationPanel({ investigation }) {
  return (
    <section className="panel">
      <div className="panel-title">Risk Investigation</div>
      {investigation ? (
        <div className="investigation-panel">
          <div className="brief-field">
            <strong>Recommendation</strong>
            <span>{investigation.recommendation}</span>
          </div>
          <div className="brief-field">
            <strong>Observations</strong>
            <ul className="compact-list">
              {investigation.observations.map((observation, index) => (
                <li key={`${observation}-${index}`}>{observation}</li>
              ))}
            </ul>
          </div>
          <div className="tool-call-list">
            {investigation.tool_requests.map((request, index) => (
              <details className="tool-call" key={`${request.tool}-${index}`}>
                <summary>
                  <strong>{request.tool}</strong>
                  <span>{request.reason}</span>
                </summary>
                <pre>
                  {JSON.stringify(
                    {
                      arguments: request.arguments,
                      result: investigation.tool_results[index]?.result ?? null,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            ))}
          </div>
          <small className="muted">
            Source: {investigation.source}
            {investigation.model ? ` / ${investigation.model}` : ""}
          </small>
        </div>
      ) : (
        <p className="muted">No bounded investigation was needed for this workflow.</p>
      )}
    </section>
  );
}

function ExecutionTracePanel({ trace, loading }) {
  return (
    <section className="panel trace-panel">
      <div className="panel-title">
        <span>Digital Worker Execution Trace</span>
        <GitBranch size={16} />
      </div>
      {loading ? (
        <p className="muted">Loading execution trace.</p>
      ) : trace.length === 0 ? (
        <p className="muted">No execution trace available.</p>
      ) : (
        <div className="execution-trace">
          {trace.map((step) => (
            <div className={`trace-step ${step.status}`} key={step.step_id}>
              <div className="trace-marker">
                <span />
              </div>
              <div className="trace-content">
                <div className="trace-step-header">
                  <strong>{step.label}</strong>
                  <StatusBadge status={step.status} />
                </div>
                <span>{step.summary}</span>
                <div className="trace-meta">
                  <small>{step.owner}</small>
                  <small>{step.langgraph_node ? `LangGraph: ${step.langgraph_node}` : "Outside graph"}</small>
                  <small>{step.event_type ?? "No event"}</small>
                  <small>{step.occurred_at ? new Date(step.occurred_at).toLocaleString() : "-"}</small>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function BriefField({ label, value }) {
  return (
    <div className="brief-field">
      <strong>{label}</strong>
      <span>{value}</span>
    </div>
  );
}

function LineComparisonDetail({ workflow }) {
  const poLines = workflow.purchase_order?.lines ?? [];
  const confirmationLines = workflow.confirmation?.lines ?? [];
  const impactsByLine = new Map((workflow.impacts ?? []).map((impact) => [impact.line_id, impact]));
  const comparisonsByLine = new Map((workflow.comparisons ?? []).map((comparison) => [comparison.line_id, comparison]));
  const lineIds = Array.from(
    new Set([
      ...poLines.map((line) => line.line_id),
      ...confirmationLines.map((line) => line.supplier_line_id),
      ...(workflow.comparisons ?? []).map((comparison) => comparison.line_id),
    ]),
  );

  return (
    <section className="panel">
      <div className="panel-title">Line Detail</div>
      {lineIds.length === 0 ? (
        <p className="muted">No line data available.</p>
      ) : (
        <div className="line-card-grid">
          {lineIds.map((lineId) => {
            const poLine = poLines.find((line) => line.line_id === lineId);
            const confirmationLine = confirmationLines.find((line) => line.supplier_line_id === lineId);
            const impact = impactsByLine.get(lineId);
            const comparison = comparisonsByLine.get(lineId);
            return (
              <div className="line-card" key={lineId}>
                <div className="line-card-header">
                  <strong>Line {lineId}</strong>
                  <StatusBadge status={impact?.stockout_risk ? "STOCKOUT_RISK" : comparison?.match_status ?? "NO_RISK"} />
                </div>
                <div className="line-columns">
                  <LineSnapshot
                    title="Purchase order"
                    rows={[
                      ["Part", poLine?.part_number],
                      ["Quantity", poLine ? `${poLine.quantity} ${poLine.unit}` : null],
                      ["Unit price", poLine?.unit_price],
                      ["Date", poLine?.requested_date],
                      ["Status", poLine?.status],
                    ]}
                  />
                  <LineSnapshot
                    title="Supplier confirmation"
                    rows={[
                      ["Part", confirmationLine?.supplier_part_number],
                      ["Internal part", confirmationLine?.internal_part_number],
                      ["Quantity", confirmationLine ? `${confirmationLine.quantity} ${confirmationLine.unit}` : null],
                      ["Unit price", confirmationLine?.unit_price],
                      ["Date", confirmationLine?.promised_date],
                      ["Status", confirmationLine?.status],
                    ]}
                  />
                </div>
                {impact && (
                  <div className="line-impact">
                    <span>{impact.recommendation}</span>
                    <small>
                      Shortage: {impact.projected_shortage_quantity} / Financial variance: $
                      {impact.financial_variance}
                    </small>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function ErpUpdateSnapshot({ workflow }) {
  const erpEvent = (workflow.audit_events ?? []).find((event) => event.event_type === "ERP_UPDATED");
  const beforeLines = erpEvent?.metadata?.before?.lines ?? [];
  const afterLines = erpEvent?.metadata?.after?.lines ?? [];
  const commandLines = workflow.erp_update_command?.line_updates ?? [];
  const lineIds = Array.from(
    new Set([
      ...beforeLines.map((line) => line.line_id),
      ...afterLines.map((line) => line.line_id),
      ...commandLines.map((line) => line.line_id),
    ]),
  );

  return (
    <section className="panel">
      <div className="panel-title">ERP Update Snapshot</div>
      {!workflow.erp_update_command ? (
        <p className="muted">No ERP update executed.</p>
      ) : (
        <div className="erp-snapshot">
          <div className="snapshot-summary">
            <Metric label="Command" value={workflow.erp_update_command.idempotency_key} />
            <Metric label="Purchase order" value={workflow.erp_update_command.purchase_order_number} />
          </div>
          <div className="erp-line-list">
            {lineIds.map((lineId) => {
              const before = beforeLines.find((line) => line.line_id === lineId);
              const after = afterLines.find((line) => line.line_id === lineId);
              return (
                <div className="erp-line-row" key={lineId}>
                  <strong>Line {lineId}</strong>
                  <div className="line-columns">
                    <LineSnapshot
                      title="Before"
                      rows={[
                        ["Part", before?.part_number],
                        ["Quantity", before ? `${before.quantity} ${before.unit}` : null],
                        ["Unit price", before?.unit_price],
                        ["Date", before?.requested_date],
                        ["Status", before?.status],
                      ]}
                    />
                    <LineSnapshot
                      title="After"
                      rows={[
                        ["Part", after?.part_number],
                        ["Quantity", after ? `${after.quantity} ${after.unit}` : null],
                        ["Unit price", after?.unit_price],
                        ["Date", after?.requested_date],
                        ["Status", after?.status],
                      ]}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

function LineSnapshot({ title, rows }) {
  return (
    <div className="line-snapshot">
      <strong>{title}</strong>
      {rows.map(([label, value]) => (
        <div className="line-snapshot-row" key={label}>
          <span>{label}</span>
          <small>{formatValue(value)}</small>
        </div>
      ))}
    </div>
  );
}

function workflowMatchesStatus(workflow, filter) {
  if (filter === "all") return true;
  if (filter === "needs_attention") {
    return ["AWAITING_APPROVAL", "MANUAL_REVIEW", "DEAD_LETTER", "RETRY_PENDING"].includes(workflow.status);
  }
  return workflow.status === filter;
}

function workflowSearchText(workflow) {
  return [
    workflow.workflow_id,
    workflow.status,
    workflow.confirmation?.purchase_order_number,
    workflow.confirmation?.supplier_id,
    workflow.confirmation?.source_control_number,
    workflow.policy_decision?.decision,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function workflowRiskScore(workflow) {
  const statusScore = {
    DEAD_LETTER: 80,
    MANUAL_REVIEW: 70,
    RETRY_PENDING: 65,
    AWAITING_APPROVAL: 60,
    CLARIFICATION_REQUESTED: 40,
    REJECTED: 20,
    COMPLETED: 0,
  }[workflow.status] ?? 10;
  const differenceScore = (workflow.comparisons ?? []).reduce(
    (total, comparison) => total + comparison.differences.length,
    0,
  );
  const stockoutScore = (workflow.impacts ?? []).some((impact) => impact.stockout_risk) ? 20 : 0;
  return statusScore + differenceScore + stockoutScore;
}

function auditSearchText(event) {
  return [event.event_type, event.actor_type, event.summary, JSON.stringify(event.metadata ?? {})]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function StatusBadge({ status }) {
  const tone =
    status === "COMPLETED" || status === "PUBLISHED"
      || status === "PASSED"
      || status === "completed"
      ? "success"
      : status === "AWAITING_APPROVAL" || status === "DRAFT" || status === "CLARIFICATION_REQUESTED" || status === "RETRY_PENDING"
        || status === "MANUAL_REVIEW" || status === "DEAD_LETTER"
        || status === "STOCKOUT_RISK" || status === "manual_review" || status === "unmatched"
        || status === "FAILED" || status === "waiting" || status === "blocked"
        ? "warning"
        : status === "REJECTED" || status === "failed"
          ? "danger"
        : "neutral";
  return <span className={`status-badge ${tone}`}>{status}</span>;
}

function defaultSupplierResponse(workflow, decisionMode) {
  const poNumber = workflow.confirmation?.purchase_order_number ?? "the purchase order";
  if (decisionMode === "reject") {
    return {
      subject: `Purchase Order ${poNumber} changes not accepted`,
      body: `Thank you for confirming purchase order ${poNumber}. We cannot accept the proposed changes at this time.`,
    };
  }
  if (decisionMode === "clarification") {
    return {
      subject: `Clarification needed for purchase order ${poNumber}`,
      body: `Thank you for confirming purchase order ${poNumber}. We need clarification before the acknowledgment can be accepted.`,
    };
  }
  return {
    subject: `Purchase Order ${poNumber} confirmation`,
    body: `Thank you for confirming purchase order ${poNumber}. The approved confirmation has been recorded.`,
  };
}

function ProfileManager({ profiles, selectedProfile, onSelect, onCreate, onSave, onPublish, onArchive, busy }) {
  const [dateQualifierJson, setDateQualifierJson] = useState("{}");
  const [ackCodeJson, setAckCodeJson] = useState("{}");
  const [showCreate, setShowCreate] = useState(false);
  const [createDraft, setCreateDraft] = useState({
    supplier_id: "",
    transaction_type: "855",
    edi_version: "004010",
    date_qualifiers: "{\n  \"067\": \"promised_delivery_date\"\n}",
    ack_codes: "{\n  \"IA\": \"accepted\"\n}",
    repeated_ack_policy: "manual_review",
    unknown_qualifier_policy: "manual_review",
  });
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

  function create() {
    try {
      setLocalError("");
      onCreate({
        supplier_id: createDraft.supplier_id,
        transaction_type: createDraft.transaction_type,
        edi_version: createDraft.edi_version,
        date_qualifiers: JSON.parse(createDraft.date_qualifiers),
        ack_codes: JSON.parse(createDraft.ack_codes),
        repeated_ack_policy: createDraft.repeated_ack_policy,
        unknown_qualifier_policy: createDraft.unknown_qualifier_policy,
      });
      setShowCreate(false);
    } catch {
      setLocalError("New profile mappings must be valid JSON objects.");
    }
  }

  function updateCreateField(field, value) {
    setCreateDraft((current) => ({ ...current, [field]: value }));
  }

  return (
    <section className="panel profile-panel">
      <div className="panel-title">
        <span>Trading Partner Profiles</span>
        <button onClick={() => setShowCreate((current) => !current)} disabled={busy}>
          <Plus size={16} />
          New profile
        </button>
      </div>
      {showCreate && (
        <div className="create-form">
          <div className="create-form-grid">
            <label>
              Supplier ID
              <input
                value={createDraft.supplier_id}
                onChange={(event) => updateCreateField("supplier_id", event.target.value)}
              />
            </label>
            <label>
              Transaction
              <input
                value={createDraft.transaction_type}
                onChange={(event) => updateCreateField("transaction_type", event.target.value)}
              />
            </label>
            <label>
              EDI version
              <input
                value={createDraft.edi_version}
                onChange={(event) => updateCreateField("edi_version", event.target.value)}
              />
            </label>
            <label>
              Repeated ACK policy
              <select
                value={createDraft.repeated_ack_policy}
                onChange={(event) => updateCreateField("repeated_ack_policy", event.target.value)}
              >
                <option value="manual_review">Manual review</option>
                <option value="split_quantities">Split quantities</option>
              </select>
            </label>
            <label>
              Unknown qualifier policy
              <select
                value={createDraft.unknown_qualifier_policy}
                onChange={(event) => updateCreateField("unknown_qualifier_policy", event.target.value)}
              >
                <option value="manual_review">Manual review</option>
                <option value="reject">Reject</option>
              </select>
            </label>
          </div>
          <label>
            Date qualifier mappings
            <textarea
              className="mapping-editor"
              value={createDraft.date_qualifiers}
              onChange={(event) => updateCreateField("date_qualifiers", event.target.value)}
            />
          </label>
          <label>
            ACK code mappings
            <textarea
              className="mapping-editor"
              value={createDraft.ack_codes}
              onChange={(event) => updateCreateField("ack_codes", event.target.value)}
            />
          </label>
          <div className="action-row">
            <button className="primary-button" onClick={create} disabled={busy || !createDraft.supplier_id.trim()}>
              <Plus size={16} />
              Create draft
            </button>
          </div>
        </div>
      )}
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

function PolicyManager({ policies, selectedPolicy, onSelect, onCreate, onSave, onPublish, onArchive, busy }) {
  const [draft, setDraft] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createDraft, setCreateDraft] = useState({
    exact_match_auto_approve: true,
    maximum_price_increase_percent: 1,
    maximum_delivery_delay_days: 2,
    maximum_order_value: 5000,
    require_no_stockout_impact: true,
    policy_version: "draft-v1",
  });

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

  function updateCreateField(field, value) {
    setCreateDraft((current) => ({ ...current, [field]: value }));
  }

  function create() {
    onCreate(createDraft);
    setShowCreate(false);
  }

  return (
    <section className="panel policy-panel">
      <div className="panel-title">
        <span>Approval Policies</span>
        <button onClick={() => setShowCreate((current) => !current)} disabled={busy}>
          <Plus size={16} />
          New policy
        </button>
      </div>
      {showCreate && (
        <div className="create-form">
          <div className="policy-form">
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={createDraft.exact_match_auto_approve}
                onChange={(event) => updateCreateField("exact_match_auto_approve", event.target.checked)}
              />
              Auto-confirm exact matches
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={createDraft.require_no_stockout_impact}
                onChange={(event) => updateCreateField("require_no_stockout_impact", event.target.checked)}
              />
              Require no stockout impact for auto-confirmation
            </label>
            <label>
              Policy version label
              <input
                value={createDraft.policy_version}
                onChange={(event) => updateCreateField("policy_version", event.target.value)}
              />
            </label>
            <label>
              Maximum price increase %
              <input
                type="number"
                min="0"
                step="0.1"
                value={createDraft.maximum_price_increase_percent}
                onChange={(event) => updateCreateField("maximum_price_increase_percent", Number(event.target.value))}
              />
            </label>
            <label>
              Maximum delivery delay days
              <input
                type="number"
                min="0"
                step="1"
                value={createDraft.maximum_delivery_delay_days}
                onChange={(event) => updateCreateField("maximum_delivery_delay_days", Number(event.target.value))}
              />
            </label>
            <label>
              Maximum order value
              <input
                type="number"
                min="0"
                step="100"
                value={createDraft.maximum_order_value}
                onChange={(event) => updateCreateField("maximum_order_value", Number(event.target.value))}
              />
            </label>
          </div>
          <div className="action-row">
            <button className="primary-button" onClick={create} disabled={busy || !createDraft.policy_version.trim()}>
              <Plus size={16} />
              Create draft
            </button>
          </div>
        </div>
      )}
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

function EvaluationDashboard({ runs, onRun, onResetMockErp, busy }) {
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
        <div className="evaluation-actions">
          <button onClick={onResetMockErp} disabled={busy}>
            <RotateCcw size={16} />
            Reset mock ERP
          </button>
          <button className="primary-button" onClick={onRun} disabled={busy}>
            <FlaskConical size={16} />
            Run scenarios
          </button>
        </div>
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

function formatRate(value) {
  if (value === null || value === undefined) return "0%";
  return `${Math.round(value * 100)}%`;
}

function formatSeconds(value) {
  if (!value) return "0s";
  return `${Math.round(value)}s`;
}

createRoot(document.getElementById("root")).render(<App />);

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { clinicApi, requireData } from "./api";
import type { components } from "./generated/api";
import { readConflict, ReportingConflict } from "./ReportingConflict";
import type { Conflict } from "./ReportingConflict";

type Detail = components["schemas"]["CaseDetail"];
type Scan = components["schemas"]["OutageRescanView"];

export function OutsideCompletion({
  api,
  detail,
  onReload,
  onSaved,
}: {
  api: ReturnType<typeof clinicApi>;
  detail: Detail;
  onReload: (detail: Detail) => void;
  onSaved: () => void;
}) {
  const [scan, setScan] = useState<Scan>();
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState<Conflict>();
  const active = useRef(true);
  const pending = useRef<{ fields: string; requestId: string } | undefined>(
    undefined,
  );
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, [api]);
  async function loadScan() {
    setBusy(true);
    setError("");
    setScan(undefined);
    setConfirmed(false);
    try {
      const result = requireData(
        await api.GET("/api/v1/outage-rescans/latest"),
      );
      if (!active.current) return;
      if (!result?.jobId || !["succeeded", "partial"].includes(result.status)) {
        setError(
          "尚無完成的停機補掃，請先在來源掃描區勾選停機復原補掃、指定日期範圍並等候完成。",
        );
        return;
      }
      setScan(result);
    } catch {
      if (active.current) setError("補掃結果讀取失敗，請重新讀取。");
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function reload() {
    setBusy(true);
    try {
      const result = requireData(
        await api.GET("/api/v1/cases/{case_id}", {
          params: { path: { case_id: detail.caseId } },
        }),
      );
      if (active.current) onReload(result);
    } catch {
      if (active.current) setError("案件讀取失敗，請重試。");
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!scan?.jobId || !confirmed || conflict || busy) return;
    setBusy(true);
    setError("");
    const fields = {
      expectedRevision: detail.revision,
      sourceSnapshot: detail.latestSourceSnapshot,
      scanJobId: scan.jobId,
      paperAndSmisCompleted: confirmed,
      reason,
    };
    const encoded = JSON.stringify(fields);
    if (pending.current?.fields !== encoded)
      pending.current = { fields: encoded, requestId: crypto.randomUUID() };
    try {
      const result = await api.POST(
        "/api/v1/cases/{case_id}/outside-completion",
        {
          params: { path: { case_id: detail.caseId } },
          body: { ...fields, requestId: pending.current.requestId },
        },
      );
      if (!active.current) return;
      if (result.response.status === 409) {
        setConflict(readConflict(result.error));
        pending.current = undefined;
        return;
      }
      const data = requireData(result);
      if (!("outsideCompletion" in data) || !data.outsideCompletion)
        throw new Error("Unexpected replay");
      pending.current = undefined;
      onSaved();
    } catch {
      if (active.current)
        setError(
          "補記未完成；請確認補掃範圍涵蓋最新來源，且已核對紙本與 SMIS 結果，再重試。",
        );
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return (
    <section aria-label="系統外完成補記">
      <h3>停機後補記系統外已完成</h3>
      <p>
        先指定停機日期範圍重掃，重新查詢案件並核對來源醫令。補記後案件結束，不再列入待辦或匯出；保留原有人工資料與來源歷史。
      </p>
      <p>
        核對來源版本 {detail.latestSourceSnapshot}。HIS
        只提供日期，不推測當日開立時間。
      </p>
      {detail.excluded || detail.sourceUnresolved ? (
        <p>此案已排除或來源仍有隔離問題，請先由回報人員核對或完成來源重試。</p>
      ) : (
        <>
          <button
            type="button"
            disabled={busy || !!conflict}
            onClick={() => void loadScan()}
          >
            讀取補掃結果
          </button>
          {scan && (
            <p>
              補掃範圍：{scan.dateFrom} 至 {scan.dateTo}；
              {scan.status === "partial"
                ? "部分來源仍隔離，逐案核對"
                : "掃描完成"}
            </p>
          )}
          <form onSubmit={(event) => void submit(event)}>
            <fieldset disabled={busy || !!conflict}>
              <legend>核對紙本與 SMIS 完成紀錄</legend>
              <label>
                補記原因
                <input
                  required
                  autoComplete="off"
                  maxLength={1000}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                已核對此來源醫令，確認停機期間已依紙本及 SMIS 完成
              </label>
              <button
                type="submit"
                disabled={!scan || !confirmed || !reason.trim()}
              >
                確認系統外已完成
              </button>
            </fieldset>
          </form>
        </>
      )}
      {conflict && (
        <>
          <ReportingConflict conflict={conflict} before={detail} draft={{}} />
          <button disabled={busy} onClick={() => void reload()}>
            重新讀取案件再核對
          </button>
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

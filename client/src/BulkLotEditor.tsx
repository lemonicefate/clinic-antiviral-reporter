import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { clinicApi, requireData } from "./api";
import type { components } from "./generated/api";
import { readConflict, ReportingConflict } from "./ReportingConflict";
import type { Conflict } from "./ReportingConflict";

export function BulkLotEditor({
  api,
  cases,
  onSaved,
}: {
  api: ReturnType<typeof clinicApi>;
  cases: components["schemas"]["CaseView"][];
  onSaved: () => void;
}) {
  const [lot, setLot] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [conflictData, setConflictData] = useState<Conflict>();
  const active = useRef(true);
  const pending = useRef<{ body: string; id: string } | undefined>(undefined);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function save(e: FormEvent) {
    e.preventDefault();
    if (!confirmed || conflict) return;
    setBusy(true);
    setError("");
    const fields = {
      expectedRevision: 0,
      lot,
      replaceConfirmed: confirmed,
      cases: cases.map((c) => ({
        caseId: c.caseId,
        expectedRevision: c.revision,
      })),
    };
    const serialized = JSON.stringify(fields);
    if (pending.current?.body !== serialized)
      pending.current = { body: serialized, id: crypto.randomUUID() };
    try {
      const result = await api.POST("/api/v1/cases/bulk-lot", {
        body: { ...fields, requestId: pending.current.id },
      });
      if (!active.current) return;
      if (result.response.status === 409) {
        setConflict(true);
        setConflictData(readConflict(result.error));
        setConfirmed(false);
        setError(
          "至少一案已變更；本批次全部未套用。請查詢清單並重新選案核對。",
        );
        return;
      }
      const data = requireData(result);
      if (!("appliedCases" in data)) throw new Error("Unexpected replay");
      onSaved();
    } catch {
      if (active.current) setError("批次未能確認儲存，請重試或重新查詢。");
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return (
    <form onSubmit={(e) => void save(e)} aria-label="批次同批號">
      <h3>選取 {cases.length} 案填入同一批號</h3>
      <p>每案依自己的實發量分配；此操作會取代已選案件原有的全部批號分攤。</p>
      <label>
        批次批號
        <input
          required
          maxLength={100}
          autoComplete="off"
          disabled={busy || conflict}
          value={lot}
          onChange={(e) => {
            setLot(e.target.value);
            setConfirmed(false);
          }}
        />
      </label>
      <label className="patient-confirmation">
        <input
          type="checkbox"
          disabled={busy || conflict}
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        <span>我已核對已選案件，確認取代其全部批號分攤</span>
      </label>
      <button disabled={busy || !confirmed || conflict || cases.length === 0}>
        套用批次批號
      </button>
      {error && <p role="alert">{error}</p>}
      {conflictData &&
        cases
          .filter((c) => c.caseId === conflictData.caseId)
          .map((c) => (
            <ReportingConflict
              key={c.caseId}
              conflict={conflictData}
              before={c}
              draft={{ lots: [{ lot, quantity: c.reportedQuantity }] }}
            />
          ))}
    </form>
  );
}

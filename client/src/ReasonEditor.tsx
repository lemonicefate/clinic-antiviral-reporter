import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { clinicApi, requireData } from "./api";
import type { components } from "./generated/api";

type Detail = components["schemas"]["CaseDetail"];

export function ReasonEditor({
  api,
  detail,
  onSaved,
  onReload,
}: {
  api: ReturnType<typeof clinicApi>;
  detail: Detail;
  onSaved: () => void;
  onReload: (detail: Detail) => void;
}) {
  const [options, setOptions] = useState<string[]>([]);
  const [reason, setReason] = useState(detail.reason ?? "");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState<{
    revision: number;
    reason: string | null;
  }>();
  const active = useRef(true);
  const pending = useRef<{ body: string; id: string } | undefined>(undefined);
  const conflictHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    active.current = true;
    api
      .GET("/api/v1/reason-options")
      .then(requireData)
      .then((data) => {
        if (active.current) setOptions(data.values);
      })
      .catch(() => {
        if (active.current)
          setError("理由選項讀取失敗，請關閉案件後重新開啟。");
      });
    return () => {
      active.current = false;
    };
  }, [api]);
  useEffect(() => {
    if (conflict) conflictHeading.current?.focus();
  }, [conflict]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!confirmed || !reason || conflict) return;
    setBusy(true);
    setError("");
    const fields = {
      expectedRevision: detail.revision,
      reason,
      patientConfirmed: confirmed,
    };
    const serialized = JSON.stringify(fields);
    if (pending.current?.body !== serialized)
      pending.current = { body: serialized, id: crypto.randomUUID() };
    try {
      const result = await api.POST("/api/v1/cases/{case_id}/reason", {
        params: { path: { case_id: detail.caseId } },
        body: { ...fields, requestId: pending.current.id },
      });
      if (!active.current) return;
      if (result.response.status === 409) {
        const body = result.error as {
          detail?: {
            currentRevision?: unknown;
            differences?: { reason?: unknown };
          };
        };
        const revision = body?.detail?.currentRevision;
        const currentReason = body?.detail?.differences?.reason;
        if (
          typeof revision !== "number" ||
          !(currentReason === null || typeof currentReason === "string")
        ) {
          throw new Error("Invalid conflict response");
        }
        setConfirmed(false);
        setConflict({ revision, reason: currentReason });
        return;
      }
      const data = requireData(result);
      if (!("caseId" in data)) throw new Error("Unexpected replay shape");
      pending.current = undefined;
      onSaved();
    } catch {
      if (active.current)
        setError("理由未能確認儲存，請重試；重新連線後請先核對中央最新內容。");
    } finally {
      if (active.current) setBusy(false);
    }
  }

  async function reload() {
    setBusy(true);
    setError("");
    try {
      const latest = requireData(
        await api.GET("/api/v1/cases/{case_id}", {
          params: { path: { case_id: detail.caseId } },
        }),
      );
      if (active.current) onReload(latest);
    } catch {
      if (active.current) setError("重新讀取失敗，尚不能覆寫。請重試。");
    } finally {
      if (active.current) setBusy(false);
    }
  }

  return (
    <form onSubmit={save} aria-label="用藥理由">
      <h3>用藥理由</h3>
      <p>
        請由人員判斷並選取官方範本的完整用藥對象；系統不推定公費資格。條件必填及平台規則仍待確認，儲存理由不代表可正式匯出。
      </p>
      {options.length === 0 && !error && <p role="status">正在讀取理由選項…</p>}
      <label>
        官方用藥對象
        <select
          aria-label="官方用藥對象"
          required
          value={reason}
          disabled={busy || !!conflict || options.length === 0}
          onChange={(e) => {
            setReason(e.target.value);
            setConfirmed(false);
          }}
        >
          <option value="">請選取完整理由</option>
          {options.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
      {reason && <p className="selected-reason">本次選取：{reason}</p>}
      <label className="patient-confirmation">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={busy || !!conflict}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        <span>我已核對 {detail.patientName}／{detail.chartNumber}／{detail.birthDate}{" "}
        與醫令 {detail.sourceOrder}</span>
      </label>
      {conflict && (
        <div role="alert">
          <h3 tabIndex={-1} ref={conflictHeading}>
            理由已被其他操作更新
          </h3>
          <p>
            讀取時版本 {detail.revision}：{detail.reason ?? "尚未填寫"}
          </p>
          <p>
            中央版本 {conflict.revision}：{conflict.reason ?? "尚未填寫"}
          </p>
          <p>你本次選取：{reason}</p>
          <p>尚未覆寫。請重新讀取並核對病人、理由後再儲存。</p>
          <button type="button" disabled={busy} onClick={() => void reload()}>
            重新讀取並核對
          </button>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      <button
        disabled={
          busy || !confirmed || !reason || !!conflict || options.length === 0
        }
        type="submit"
      >
        {busy ? "處理中…" : "儲存用藥理由"}
      </button>
    </form>
  );
}

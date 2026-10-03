import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { clinicApi, requireData } from "./api";
import type { components } from "./generated/api";
import { readConflict, ReportingConflict } from "./ReportingConflict";
import type { Conflict } from "./ReportingConflict";
type Detail = components["schemas"]["CaseDetail"];
type Api = ReturnType<typeof clinicApi>;

export function ReportingEditor({
  api,
  detail,
  onSaved,
  onReload,
}: {
  api: Api;
  detail: Detail;
  onSaved: () => void;
  onReload: (detail: Detail) => void;
}) {
  const [quantity, setQuantity] = useState(String(detail.reportedQuantity));
  const [lots, setLots] = useState(
    detail.lots?.length
      ? detail.lots.map((l) => ({ lot: l.lot, quantity: String(l.quantity) }))
      : [{ lot: "", quantity: String(detail.reportedQuantity) }],
  );
  const [reason, setReason] = useState("");
  const [decisionReason, setDecisionReason] = useState("");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [conflictData, setConflictData] = useState<Conflict>();
  const [conflictDraft, setConflictDraft] = useState<Record<string, unknown>>(
    {},
  );
  const [busy, setBusy] = useState(false);
  const [history, setHistory] =
    useState<components["schemas"]["CaseHistoryEvent"][]>();
  const [historyError, setHistoryError] = useState("");
  const active = useRef(true);
  const pending = useRef<{ body: string; id: string } | undefined>(undefined);
  function requestId(body: unknown) {
    const serialized = JSON.stringify(body);
    if (pending.current?.body !== serialized)
      pending.current = { body: serialized, id: crypto.randomUUID() };
    return pending.current.id;
  }
  useEffect(() => {
    active.current = true;
    api
      .GET("/api/v1/cases/{case_id}/history", {
        params: { path: { case_id: detail.caseId } },
      })
      .then(requireData)
      .then((data) => {
        if (active.current) setHistory(data);
      })
      .catch(() => {
        if (active.current) setHistoryError("歷史讀取失敗；請重新開啟此案。");
      });
    return () => {
      active.current = false;
    };
  }, [api, detail.caseId]);

  async function save(event: FormEvent, exclusion: boolean) {
    event.preventDefault();
    if (conflict) return;
    setBusy(true);
    setError("");
    try {
      const result = exclusion
        ? await (() => {
            const fields = {
              expectedRevision: detail.revision,
              excluded: !detail.excluded,
              reason: decisionReason,
            };
            return api.POST("/api/v1/cases/{case_id}/exclusion", {
              params: { path: { case_id: detail.caseId } },
              body: { ...fields, requestId: requestId(fields) },
            });
          })()
        : await (() => {
            const fields = {
              expectedRevision: detail.revision,
              reportedQuantity: Number(quantity),
              lots: lots.map((l) => ({
                lot: l.lot,
                quantity: Number(l.quantity),
              })),
              changeReason: reason,
            };
            return api.POST("/api/v1/cases/{case_id}/dispensing", {
              params: { path: { case_id: detail.caseId } },
              body: { ...fields, requestId: requestId(fields) },
            });
          })();
      if (!active.current) return;
      if (result.response.status === 409) {
        setConflict(true);
        setConflictData(readConflict(result.error));
        setConflictDraft(
          exclusion
            ? { excluded: !detail.excluded, exclusionReason: decisionReason }
            : {
                reportedQuantity: Number(quantity),
                lots: lots.map((l) => ({
                  lot: l.lot,
                  quantity: Number(l.quantity),
                })),
              },
        );
        setError(
          "案件版本或排除狀態已變更，尚未覆寫。請重新讀取並核對數量、批號及理由。",
        );
        return;
      }
      const data = requireData(result);
      if (!("caseId" in data)) throw new Error("Unexpected command replay");
      onSaved();
    } catch {
      if (active.current)
        setError(
          "未能儲存。請確認實發量不超過來源、批號不重複、分攤合計相符，且數量修改與排除／納入皆有原因。",
        );
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function reload() {
    setBusy(true);
    try {
      const latest = requireData(
        await api.GET("/api/v1/cases/{case_id}", {
          params: { path: { case_id: detail.caseId } },
        }),
      );
      if (active.current) onReload(latest);
    } catch {
      if (active.current) setError("重新讀取失敗，請重試。");
    } finally {
      if (active.current) setBusy(false);
    }
  }
  const disabled = busy || conflict;
  return (
    <section aria-label="回報核對">
      <h3>實發數量與批號分攤</h3>
      <p>
        來源 {detail.sourceQuantity} 顆；目前回報 {detail.reportedQuantity}{" "}
        顆。來源快照不會因人工核對而改寫。
      </p>
      {!detail.excluded && (
        <form onSubmit={(e) => void save(e, false)}>
          <fieldset disabled={disabled}>
            <legend>核對本次實際發藥</legend>
            <label>
              實發數量
              <input
                type="number"
                min="1"
                max={detail.sourceQuantity}
                step="1"
                required
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </label>
            {lots.map((allocation, index) => (
              <div className="lot-row" key={index}>
                <label>
                  批號 {index + 1}
                  <input
                    required
                    maxLength={100}
                    autoComplete="off"
                    value={allocation.lot}
                    onChange={(e) =>
                      setLots(
                        lots.map((l, i) =>
                          i === index ? { ...l, lot: e.target.value } : l,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  分攤數量 {index + 1}
                  <input
                    type="number"
                    min="1"
                    step="1"
                    required
                    value={allocation.quantity}
                    onChange={(e) =>
                      setLots(
                        lots.map((l, i) =>
                          i === index ? { ...l, quantity: e.target.value } : l,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  className="secondary"
                  type="button"
                  disabled={lots.length === 1}
                  onClick={() => setLots(lots.filter((_, i) => i !== index))}
                >
                  移除批號 {index + 1}
                </button>
              </div>
            ))}
            <button
              className="secondary"
              type="button"
              disabled={lots.length >= 50}
              onClick={() => setLots([...lots, { lot: "", quantity: "" }])}
            >
              新增批號分攤
            </button>
            <p>
              目前分攤合計：
              {lots.reduce((sum, l) => sum + (Number(l.quantity) || 0), 0)}{" "}
              顆；須等於實發數量。
            </p>
            <label>
              數量修改原因
              <input
                maxLength={500}
                autoComplete="off"
                required={Number(quantity) !== detail.reportedQuantity}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <button type="submit">儲存發藥核對</button>
          </fieldset>
        </form>
      )}
      <h3>{detail.excluded ? "重新納入案件" : "排除案件"}</h3>
      {detail.exclusionReason && (
        <p>最近排除／納入原因：{detail.exclusionReason}</p>
      )}
      <form onSubmit={(e) => void save(e, true)}>
        <label>
          排除或納入原因
          <input
            required
            maxLength={500}
            autoComplete="off"
            disabled={disabled}
            value={decisionReason}
            onChange={(e) => setDecisionReason(e.target.value)}
          />
        </label>
        <button type="submit" className="secondary" disabled={disabled}>
          {detail.excluded ? "確認重新納入" : "確認排除此案"}
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
      {conflictData && (
        <ReportingConflict
          conflict={conflictData}
          before={detail}
          draft={conflictDraft}
        />
      )}
      {conflict && (
        <button type="button" disabled={busy} onClick={() => void reload()}>
          重新讀取回報資料
        </button>
      )}
      <details>
        <summary>案件稽核歷史</summary>
        {historyError && <p role="alert">{historyError}</p>}
        {!history && !historyError && <p>正在讀取歷史…</p>}
        {history?.map((event) => (
          <article key={event.sequence}>
            <h4>
              {(
                {
                  case_created: "建案",
                  reason_saved: "用藥理由",
                  dispensing_saved: "發藥核對",
                  bulk_lot_saved: "批次批號",
                  exclusion_changed: "排除／納入",
                } as Record<string, string>
              )[event.kind] ?? event.kind}
            </h4>
            <p>
              {new Date(event.occurredAt * 1000).toLocaleString("zh-TW")} ·{" "}
              {event.operator} · 裝置 {event.deviceId}
            </p>
            <p>原因：{String(event.changes.reason || "未另填原因")}</p>
            <p>
              修改前：{describe(event.changes.before)}；修改後：
              {describe(event.changes.after)}
            </p>
          </article>
        ))}
      </details>
    </section>
  );
}

function describe(value: unknown): string {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return "無";
  const data = value as {
    reportedQuantity?: number;
    excluded?: boolean;
    lots?: { lot: string; quantity: number }[];
  };
  return (
    "實發 " +
    (data.reportedQuantity ?? "—") +
    " 顆，" +
    (data.excluded ? "已排除" : "已納入") +
    "；批號 " +
    (data.lots?.map((l) => l.lot + "：" + l.quantity + " 顆").join("、") ||
      "未填")
  );
}

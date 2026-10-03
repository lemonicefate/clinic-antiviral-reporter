import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { clinicApi, requireData } from "./api";
import type { components } from "./generated/api";
import { readConflict, ReportingConflict } from "./ReportingConflict";
import type { Conflict } from "./ReportingConflict";

type Detail = components["schemas"]["CaseDetail"];
type Api = ReturnType<typeof clinicApi>;
const labels: Record<string, string> = {
  "PD011M1.NUM": "病歷號",
  "PD011M1.NAME": "姓名",
  "PD011M1.BIRTH": "出生日期",
  "CH011M1.DOC": "醫師",
  "CH011M1.SDATE": "給藥日期",
  "CH012M1.USE_TAMT": "來源數量",
  "RG011M1.TREAT": "來源看診狀態",
  "CH012M1.SYS_2015": "來源醫令",
};

export function SourceReview({
  api,
  detail,
  reporting,
  onReload,
  onSaved,
}: {
  api: Api;
  detail: Detail;
  reporting: boolean;
  onReload: (detail: Detail) => void;
  onSaved: () => void;
}) {
  const [resolution, setResolution] = useState<
    "update" | "retain" | "exclude" | ""
  >("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const [current, setCurrent] = useState<Conflict>();
  const active = useRef(true);
  const pending = useRef<{ body: string; id: string } | undefined>(undefined);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!resolution || blocked || detail.sourceUnresolved) return;
    const fields = {
      expectedRevision: detail.revision,
      sourceSnapshot: detail.latestSourceSnapshot ?? 0,
      resolution,
      reason,
    };
    const body = JSON.stringify(fields);
    if (pending.current?.body !== body)
      pending.current = { body, id: crypto.randomUUID() };
    setBusy(true);
    setError("");
    try {
      const result = await api.POST("/api/v1/cases/{case_id}/source-review", {
        params: { path: { case_id: detail.caseId } },
        body: { ...fields, requestId: pending.current.id },
      });
      if (!active.current) return;
      if (result.response.status === 409) {
        setBlocked(true);
        const conflict = readConflict(result.error);
        setCurrent(conflict);
        setError("來源或回報資料已變更，尚未套用本次決定。請重新讀取並核對。");
        return;
      }
      const data = requireData(result);
      if (!("caseId" in data)) throw new Error("Unexpected replay");
      onSaved();
    } catch {
      if (active.current)
        setError("來源核對未儲存，請檢查處理方式與原因後重試。");
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function reload() {
    setBusy(true);
    try {
      const data = requireData(
        await api.GET("/api/v1/cases/{case_id}", {
          params: { path: { case_id: detail.caseId } },
        }),
      );
      if (active.current) onReload(data);
    } catch {
      if (active.current) setError("重新讀取失敗，請重試。");
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return (
    <section aria-label="HIS 來源核對">
      <h3>{detail.sourceReviewRequired ? "HIS 異動待確認" : "HIS 來源核對"}</h3>
      <p>
        回報採用來源版本 {detail.reportingSourceSnapshot}；最新來源版本{" "}
        {detail.latestSourceSnapshot}。
      </p>
      <p>目前來源狀態：{detail.sourceTreatment || "未提供"}</p>
      <p>
        下表比較回報目前採用的來源與最新來源；人工理由、實發量、批號及排除決定另行保存。
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>欄位</th>
              <th>回報採用來源</th>
              <th>最新來源</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(detail.sourceDifferences ?? {}).map(
              ([key, diff]) => (
                <tr key={key}>
                  <th>{labels[key] ?? key}</th>
                  <td>{diff.before ?? "未提供"}</td>
                  <td>{diff.after ?? "未提供"}</td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
      {Object.keys(detail.sourceDifferences ?? {}).length === 0 && (
        <p>目前來源值相同；仍須確認尚未處理的來源事件。</p>
      )}
      {detail.sourceUnresolved && (
        <p className="notice">
          來源尚未能可靠讀取，請由管理者重試並處理隔離來源；來源恢復前不能完成核對。
        </p>
      )}
      {reporting && detail.sourceReviewRequired && (
        <form onSubmit={(e) => void save(e)}>
          <fieldset disabled={busy || blocked || detail.sourceUnresolved}>
            <legend>回報管理人員確認處理方式</legend>
            <label>
              來源處理方式
              <select
                aria-label="來源處理方式"
                required
                value={resolution}
                onChange={(e) =>
                  setResolution(e.target.value as typeof resolution)
                }
              >
                <option value="">請選擇</option>
                <option value="update">採用最新來源資料</option>
                <option value="retain">保留目前回報採用的來源</option>
                <option value="exclude">排除此案</option>
              </select>
            </label>
            <p>
              採用最新來源會更新姓名、日期等來源欄位，實發量及批號仍保留，請接著核對；保留或採用都不會自動重新納入已排除案件。
            </p>
            <label>
              來源核對原因
              <textarea
                required
                maxLength={500}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <button type="submit">儲存來源核對</button>
          </fieldset>
        </form>
      )}
      {!reporting && detail.sourceReviewRequired && (
        <p>請交由回報管理人員核對來源異動。</p>
      )}
      {error && <p role="alert">{error}</p>}
      {blocked && (
        <>
          {current && (
            <>
              <p>
                讀取時來源狀態 {detail.sourceTreatment}、版本{" "}
                {detail.latestSourceSnapshot}； 中央目前來源狀態{" "}
                {String(current.differences.sourceTreatment ?? "未提供")}、 版本{" "}
                {String(current.differences.latestSourceSnapshot ?? "未提供")}。
                本次處理方式與原因仍保留於上方，尚未套用。
              </p>
              <ReportingConflict
                conflict={current}
                before={detail}
                draft={{}}
              />
            </>
          )}
          <button disabled={busy} onClick={() => void reload()}>
            重新讀取來源與回報資料
          </button>
        </>
      )}
    </section>
  );
}

export function SourceQuarantine({ api }: { api: Api }) {
  const [items, setItems] =
    useState<components["schemas"]["QuarantineView"][]>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function load() {
    setBusy(true);
    setError("");
    setItems(undefined);
    try {
      const data = requireData(await api.GET("/api/v1/source-quarantine"));
      if (active.current) setItems(data);
    } catch {
      if (active.current) setError("隔離來源讀取失敗，請重試。");
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return (
    <section aria-label="隔離來源">
      <button disabled={busy} onClick={() => void load()}>
        讀取隔離來源
      </button>
      {error && <p role="alert">{error}</p>}
      {items?.length === 0 && <p>目前沒有隔離來源紀錄。</p>}
      {items?.map((item) => (
        <p key={item.sequence}>
          {item.sourceKey}：
          <span>
            {item.diagnosis === "registration_not_seen_with_order"
              ? "尚未看診但存在醫令"
              : "原來源未再觀測到"}
          </span>
          {" · "}
          {item.resolved ? "來源已恢復，案件仍須人工核對" : "待重試"} · 觀測{" "}
          {item.attempts} 次
        </p>
      ))}
    </section>
  );
}

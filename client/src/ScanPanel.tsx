import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { clinicApi, requireData } from "./api";
import type { components } from "./generated/api";

type Scan = components["schemas"]["ScanView"];
const states: Record<Scan["status"], string> = {
  disabled: "檔案掃描未啟用",
  awaiting_configuration: "等待管理者設定映射與初始掃描範圍",
  idle: "尚未掃描",
  queued: "已排入掃描",
  running: "正在讀取來源",
  succeeded: "掃描完成",
  partial: "掃描有隔離來源",
  failed: "掃描失敗",
  interrupted: "掃描中斷",
};
const diagnostics: Record<string, string> = {
  sharing_or_access_denied: "來源檔被鎖定或無讀取權限",
  source_unavailable: "來源尚未準備或無法存取",
  partial_or_unsupported_table: "來源可能尚在寫入或格式不支援",
  decoding_error: "來源編碼無法辨識",
  quarantined_sources: "有來源需要管理者或回報人員處理",
  source_changed_during_read: "讀取期間來源變動，請重試",
  ingestion_failed: "儲存掃描結果失敗，未套用本次案件變更",
  service_restarted: "中央重新啟動，上次掃描中斷",
};

export function ScanPanel({
  api,
  admin = false,
}: {
  api: ReturnType<typeof clinicApi>;
  admin?: boolean;
}) {
  const [scan, setScan] = useState<Scan>();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [outageRecovery, setOutageRecovery] = useState(false);
  const active = useRef(true),
    generation = useRef(0),
    sending = useRef(false);
  const pending = useRef<{ body: string; id: string } | undefined>(undefined);
  useEffect(() => {
    active.current = true;
    async function load() {
      if (sending.current) return;
      const current = ++generation.current;
      try {
        const data = requireData(await api.GET("/api/v1/scans/status"));
        if (!active.current || current !== generation.current) return;
        setScan(data);
        setFrom((value) => value || data.dateFrom || "");
        setTo((value) => value || data.dateTo || "");
        setError("");
      } catch {
        if (active.current && current === generation.current)
          setError("掃描狀態讀取失敗；不能視為來源已更新。");
      }
    }
    void load();
    const timer = setInterval(() => void load(), 1000);
    return () => {
      active.current = false;
      generation.current++;
      clearInterval(timer);
    };
  }, [api]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!scan) return;
    sending.current = true;
    generation.current++;
    setBusy(true);
    setNotice("");
    const fields = {
      expectedRevision: scan.revision,
      dateFrom: from,
      dateTo: to,
      outageRecovery,
    };
    const body = JSON.stringify(fields);
    if (pending.current?.body !== body)
      pending.current = { body, id: crypto.randomUUID() };
    try {
      const result = await api.POST("/api/v1/scans", {
        body: { ...fields, requestId: pending.current.id },
      });
      if (!active.current) return;
      if (result.response.status === 409) {
        pending.current = undefined;
        setNotice(
          "掃描版本已變更或已有工作執行中，未重複排入；請等候狀態更新後再核對範圍。",
        );
        return;
      }
      const data = requireData(result);
      if (!("jobId" in data)) throw new Error("Unexpected replay");
      pending.current = undefined;
      setScan(data);
      setNotice("掃描要求已受理，請等候完成；完成後重新查詢案件清單。");
    } catch {
      if (active.current)
        setNotice("掃描要求未受理，請確認日期在已設定的初始範圍內後重試。");
    } finally {
      sending.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <section aria-label="來源掃描狀態">
      <h3>來源檔案掃描</h3>
      {error && <p role="alert">{error}</p>}
      {scan && (
        <>
          <p role="status">{states[scan.status]}</p>
          {scan.status === "awaiting_configuration" ? (
            <p>尚未設定明確啟用時間及初始範圍，中央不會自動建立案件。</p>
          ) : scan.enabled ? (
            <>
              <p>
                合成 DBF 測試 · 中央每 {scan.intervalSeconds}{" "}
                秒掃描，即使沒有客戶端連線也會執行。
              </p>
              <p>
                最近完整成功：
                {scan.lastSuccessAt
                  ? new Date(scan.lastSuccessAt * 1000).toLocaleString("zh-TW")
                  : "尚無"}
                {scan.stale && "；掃描資料可能落後，請勿視為 HIS 已更新"}
              </p>
              {scan.diagnostic && (
                <p className="notice">
                  {diagnostics[scan.diagnostic] ??
                    "來源讀取未完成，請由管理者檢查合成檔案與格式。"}
                </p>
              )}
              <p>
                本次新增 {scan.counts?.created ?? 0} 案、異動{" "}
                {scan.counts?.changed ?? 0} 案、隔離{" "}
                {scan.counts?.quarantined ?? 0} 筆。
              </p>
              <form onSubmit={(event) => void submit(event)}>
                <fieldset
                  disabled={
                    busy ||
                    scan.status === "running" ||
                    scan.status === "queued"
                  }
                >
                  <legend>指定日期重新掃描與重試隔離來源</legend>
                  {admin && (
                    <label>
                      <input
                        type="checkbox"
                        checked={outageRecovery}
                        onChange={(e) => setOutageRecovery(e.target.checked)}
                      />
                      停機復原補掃（管理者）
                    </label>
                  )}
                  <label>
                    重掃開始日期
                    <input
                      required
                      type="date"
                      value={from}
                      onChange={(e) => setFrom(e.target.value)}
                    />
                  </label>
                  <label>
                    重掃結束日期
                    <input
                      required
                      type="date"
                      value={to}
                      onChange={(e) => setTo(e.target.value)}
                    />
                  </label>
                  <button type="submit">要求檔案重掃</button>
                </fieldset>
              </form>
            </>
          ) : (
            <p>正式 HIS 讀取等待真機證據；合成檔案掃描可由中央測試設定啟用。</p>
          )}
        </>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}

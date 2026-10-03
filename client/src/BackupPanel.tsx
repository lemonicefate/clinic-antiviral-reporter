import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { clinicApi, requireData } from "./api";
import type { components } from "./generated/api";

type Backup = components["schemas"]["BackupView"];
const statuses: Record<Backup["status"], string> = {
  disabled: "中央尚未啟用備份",
  idle: "尚無備份工作",
  queued: "備份已排入",
  running: "正在建立備份",
  ready: "備份完成",
  failed: "備份失敗",
  interrupted: "備份中斷",
};
function timestamp(value: number | null) {
  return value ? new Date(value * 1000).toLocaleString("zh-TW") : "尚無紀錄";
}

export function BackupPanel({ api }: { api: ReturnType<typeof clinicApi> }) {
  const [view, setView] = useState<Backup>();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const active = useRef(true),
    sending = useRef(false),
    generation = useRef(0);
  const pending = useRef<{ fields: string; requestId: string } | undefined>(
    undefined,
  );
  useEffect(() => {
    active.current = true;
    async function load() {
      if (sending.current) return;
      const current = ++generation.current;
      try {
        const data = requireData(await api.GET("/api/v1/backups/status"));
        if (active.current && generation.current === current) {
          setView(data);
          setError("");
        }
      } catch {
        if (active.current && generation.current === current) {
          setView(undefined);
          setError("備份狀態讀取失敗，不能視為已有可用備份。");
        }
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
    if (!view || sending.current) return;
    sending.current = true;
    generation.current++;
    setBusy(true);
    setNotice("");
    const fields = { expectedRevision: view.revision, reason };
    const encoded = JSON.stringify(fields);
    if (pending.current?.fields !== encoded)
      pending.current = { fields: encoded, requestId: crypto.randomUUID() };
    try {
      const result = await api.POST("/api/v1/backups", {
        body: { ...fields, requestId: pending.current.requestId },
      });
      if (!active.current) return;
      if (result.response.status === 409) {
        pending.current = undefined;
        setNotice(
          "備份版本已變更或有工作執行中，未重複建立；請等候狀態更新後重新核對。",
        );
        return;
      }
      const data = requireData(result);
      if (!("backupId" in data)) throw new Error("Unexpected replay");
      pending.current = undefined;
      setView(data);
      setReason("");
      setNotice("備份要求已受理；請等候完成。");
    } catch {
      if (active.current)
        setNotice("備份要求未完成，請確認中央設定與權限後重試。");
    } finally {
      sending.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <section aria-label="中央備份狀態">
      <h2>中央備份狀態</h2>
      {error && <p role="alert">{error}</p>}
      {view && (
        <>
          <p role="status">{statuses[view.status]}</p>
          <p>
            {view.destinationKind === "local_synthetic"
              ? "本機合成測試；不構成正式異機備份證據。"
              : view.enabled
                ? "使用中央設定的備份目的地；正式異機還原證據仍待驗證。"
                : "請由中央主機管理者設定並啟用備份。"}
          </p>
          <p>
            排程間隔 {view.intervalSeconds} 秒；可復原資料落後上限{" "}
            {view.rpoSeconds} 秒。
          </p>
          <p className={view.rpoBreached ? "notice" : undefined}>
            {view.rpoBreached
              ? "備份資料已超過一小時或尚無成功備份，請管理者立即處理。"
              : "最近成功備份的資料時間仍在一小時內。"}
          </p>
          <dl>
            <dt>最近成功完成</dt>
            <dd>{timestamp(view.lastSuccessfulAt)}</dd>
            <dt>可復原資料時間</dt>
            <dd>{timestamp(view.lastSnapshotAt)}</dd>
            <dt>最近失敗或中斷</dt>
            <dd>{timestamp(view.lastFailureAt)}</dd>
            <dt>目前備份識別碼</dt>
            <dd data-testid="backup-id" style={{ overflowWrap: "anywhere" }}>
              {view.backupId ?? "尚無"}
            </dd>
          </dl>
          {view.diagnostic && (
            <p>
              曾發生備份失敗或中斷；請中央管理者檢查存取權限與目的地可用性。只有完成並驗證的備份可供還原。
            </p>
          )}
          <form onSubmit={(event) => void submit(event)}>
            <fieldset
              disabled={
                busy ||
                !view.enabled ||
                view.status === "queued" ||
                view.status === "running"
              }
            >
              <legend>手動建立一份新備份</legend>
              <label>
                備份原因
                <input
                  required
                  autoComplete="off"
                  maxLength={500}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
              <button disabled={!reason.trim()}>立即要求備份</button>
            </fieldset>
          </form>
          <h3>還原與保存</h3>
          <p>
            由中央主機管理者將已驗證備份還原到全新的隔離目錄，確認案件歷史、裝置授權與檔案權限後再安排切換。還原工具不覆寫現用資料，還原後須重新建立操作
            session。
          </p>
          <p>
            備份、稽核與不可變檔案不會自動刪除；請依核准的保存政策管理。原因欄位不要輸入病患資料或憑證。
          </p>
        </>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}

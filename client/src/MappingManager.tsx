import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { clinicApi, requireData } from "./api";
import type { components } from "./generated/api";

type Mapping = components["schemas"]["MappingView"];
const gates: Record<string, string> = {
  live_his_contract: "實際 HIS 來源鍵、欄位及唯讀行為驗證",
  official_export_contract: "官方格式、數量、多批號及補正規則",
  synthetic_smis_import: "合成資料實際通過 SMIS 匯入",
  operator_authorization: "代理作業、憑證使用與責任授權",
  deployment_and_restore: "正式帳號、網路、裝置撤銷與異機備份還原",
  outage_recovery: "正式啟用紀錄、停機補掃與系統外完成流程",
};

export function MappingManager({ api }: { api: ReturnType<typeof clinicApi> }) {
  const [view, setView] = useState<Mapping>();
  const [effective, setEffective] = useState("");
  const [initial, setInitial] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState<Mapping>();
  const active = useRef(true);
  const pending = useRef<{ body: string; id: string } | undefined>(undefined);

  function adopt(data: Mapping) {
    setView(data);
    setInitial(data.initialDateFrom ?? "");
    setEffective("");
    setReason("");
    setEnabled(true);
    setConflict(undefined);
    pending.current = undefined;
  }
  async function reload() {
    setBusy(true);
    try {
      const data = requireData(await api.GET("/api/v1/mappings"));
      if (active.current) {
        adopt(data);
        setNotice("");
      }
    } catch {
      if (active.current) setNotice("設定讀取失敗，請重新載入。");
    } finally {
      if (active.current) setBusy(false);
    }
  }
  useEffect(() => {
    active.current = true;
    void reload();
    return () => {
      active.current = false;
    };
  }, [api]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!view || busy || conflict) return;
    const fields = {
      expectedRevision: view.revision,
      ...view.confirmedProfile,
      effectiveFrom: effective + "T00:00:00+08:00",
      initialDateFrom: initial,
      enabled,
      reason,
    };
    const body = JSON.stringify(fields);
    if (pending.current?.body !== body)
      pending.current = { body, id: crypto.randomUUID() };
    setBusy(true);
    setNotice("");
    try {
      const result = await api.POST("/api/v1/mappings", {
        body: { ...fields, requestId: pending.current.id },
      });
      if (!active.current) return;
      if (result.response.status === 409) {
        const payload = result.error as
          { detail?: { differences?: Mapping } } | undefined;
        const current = payload?.detail?.differences;
        if (!current || !Array.isArray(current.versions))
          throw new Error("Invalid conflict");
        setConflict(current);
        pending.current = undefined;
        setNotice(
          "其他管理者已變更設定。本次未儲存；請比較現行設定與草稿，再重新載入並核對。",
        );
        return;
      }
      const saved = requireData(result);
      if (!("versions" in saved)) throw new Error("Unexpected command result");
      adopt(saved);
      setNotice("映射新版本已儲存，歷史版本仍保留。正式匯出仍未啟用。");
    } catch {
      if (active.current)
        setNotice(
          "未能儲存。請確認生效日期晚於上一版本，初始起日不早於啟用日且不晚於今天。首次設定必須啟用映射。",
        );
    } finally {
      if (active.current) setBusy(false);
    }
  }

  return (
    <section className="mapping-manager" aria-label="映射與啟用設定">
      <h2>映射與啟用設定</h2>
      <p>只支援已確認的院內藥品鏈。新增未驗證品項或單位須先取得介接證據。</p>
      {notice && <p role="status">{notice}</p>}
      <button
        className="secondary"
        disabled={busy}
        onClick={() => void reload()}
      >
        重新載入並核對
      </button>
      {view && (
        <>
          <p>目前設定版本：{view.revision}</p>
          <p>
            {view.goLiveAt ? `啟用時間：${view.goLiveAt}` : "尚未設定啟用時間"}
          </p>
          <p>
            {view.confirmedProfile.internalCode} →{" "}
            {view.confirmedProfile.nhiCode} →{" "}
            {view.confirmedProfile.materialValue}
          </p>
          <p>
            來源數量：整數顆。來源日期只保存年月日；生效邊界為台灣時間午夜，不代表來源醫令時間。
          </p>
          <form onSubmit={submit}>
            <fieldset disabled={busy || Boolean(conflict)}>
              <legend>
                {view.revision === 0 ? "首次啟用" : "建立後續版本"}
              </legend>
              <label>
                生效日期（台灣時間 00:00）
                <input
                  type="date"
                  required
                  value={effective}
                  onChange={(e) => setEffective(e.target.value)}
                />
              </label>
              <label>
                初始掃描起日
                <input
                  type="date"
                  required
                  value={initial}
                  readOnly={view.revision > 0}
                  onChange={(e) => setInitial(e.target.value)}
                />
              </label>
              <p>初始起日設定後固定保留；中央會從此日起掃描到當日。</p>
              <label>
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                />
                啟用此版本的映射
              </label>
              <p>停用版本涵蓋的來源會隔離，既有案件與人工資料仍保留。</p>
              <label htmlFor="mapping-reason">設定原因</label>
              <textarea
                id="mapping-reason"
                required
                maxLength={500}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
              <button type="submit">儲存新版本</button>
            </fieldset>
          </form>
          {conflict && (
            <aside aria-label="設定衝突">
              <h3>中央現行設定（版本 {conflict.revision}）</h3>
              <p>
                啟用：{conflict.goLiveAt ?? "未設定"}；初始起日：
                {conflict.initialDateFrom ?? "未設定"}
              </p>
              <p>
                最新版本：{conflict.versions.at(-1)?.effectiveFrom ?? "未設定"}
                ；{conflict.versions.at(-1)?.enabled ? "啟用" : "停用"}
              </p>
              <p>上方保留本次草稿。重新載入會清除草稿，請核對後重新填寫。</p>
            </aside>
          )}
          <h3>版本歷史</h3>
          {view.versions.length === 0 ? (
            <p>尚無生效版本。</p>
          ) : (
            view.versions.map((version) => (
              <article key={version.version}>
                <h4>
                  版本 {version.version} · {version.enabled ? "啟用" : "停用"}
                </h4>
                <p>自 {version.effectiveFrom} 起，至後續版本生效前。</p>
                <p>
                  {version.internalCode} → {version.nhiCode} →{" "}
                  {version.materialValue}
                </p>
                <p>原因：{version.reason}</p>
                <p>
                  操作身分：{version.operator}；裝置：{version.deviceId}
                </p>
              </article>
            ))
          )}
          <h3>正式匯出尚未啟用</h3>
          <ul>
            {view.openGates?.map((gate) => (
              <li key={gate}>OPEN：{gates[gate] ?? gate}</li>
            ))}
          </ul>
          <p>映射儲存成功不代表已完成正式上線驗證。</p>
        </>
      )}
    </section>
  );
}

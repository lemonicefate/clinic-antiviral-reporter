import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { clinicApi, requireData } from "./api";
import type { Session } from "./api";
import type { components } from "./generated/api";

type Queue = components["schemas"]["QueueView"];
type Detail = components["schemas"]["CaseDetail"];

export function CaseQueue({
  api,
  session,
}: {
  api: ReturnType<typeof clinicApi>;
  session: Session;
}) {
  const [physician, setPhysician] = useState(session.operator);
  const [chart, setChart] = useState("");
  const [queue, setQueue] = useState<Queue>();
  const [detail, setDetail] = useState<Detail>();
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const detailGeneration = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const pendingRefresh = useRef<
    { requestId: string; expectedRevision: number } | undefined
  >(undefined);

  useEffect(() => {
    void load(session.operator, "");
    return () => {
      generation.current += 1;
      detailGeneration.current += 1;
    };
  }, [api]);
  useEffect(() => {
    if (detail) heading.current?.focus();
  }, [detail]);

  async function load(selected = physician, exactChart = chart) {
    const current = ++generation.current;
    detailGeneration.current += 1;
    setDetail(undefined);
    setQueue(undefined);
    setStatus("");
    setBusy(true);
    setError("");
    try {
      const data = requireData(
        await api.GET("/api/v1/cases", {
          params: {
            query: {
              physician: selected,
              ...(exactChart ? { chart: exactChart } : {}),
            },
          },
        }),
      );
      if (generation.current === current) setQueue(data);
    } catch {
      if (generation.current === current)
        setError("清單讀取失敗，請重新查詢；無法連線時改用紙本流程。");
    } finally {
      if (generation.current === current) setBusy(false);
    }
  }

  async function select(caseId: string) {
    const current = ++detailGeneration.current;
    setDetail(undefined);
    setError("");
    setStatus("正在讀取案件…");
    try {
      const data = requireData(
        await api.GET("/api/v1/cases/{case_id}", {
          params: { path: { case_id: caseId } },
        }),
      );
      if (detailGeneration.current === current) {
        setDetail(data);
        setStatus("");
      }
    } catch {
      if (detailGeneration.current === current) {
        setError("案件讀取失敗，請重新選取。");
        setStatus("");
      }
    }
  }

  async function refresh() {
    if (!queue) return;
    setBusy(true);
    setError("");
    const current = generation.current;
    const body = pendingRefresh.current ?? {
      requestId: crypto.randomUUID(),
      expectedRevision: queue.refreshRevision,
    };
    pendingRefresh.current = body;
    try {
      const result = await api.POST("/api/v1/synthetic/refresh", { body });
      if (generation.current !== current) return;
      if (result.response.status === 409) {
        pendingRefresh.current = undefined;
        await load();
        setError("來源刷新版本已變更，已重新讀取。請核對清單後再刷新。");
        return;
      }
      const data = requireData(result);
      if (!("created" in data))
        throw new Error("request replay belongs to another command");
      pendingRefresh.current = undefined;
      await load();
      if (generation.current === current + 1)
        setStatus(
          `合成來源刷新完成：新增 ${data.created} 案，未變 ${data.unchanged} 案。`,
        );
    } catch {
      if (generation.current === current)
        setError("合成來源刷新未完成，請重試。");
    } finally {
      if (generation.current === current) setBusy(false);
    }
  }

  function search(event: FormEvent) {
    event.preventDefault();
    setStatus("");
    void load();
  }

  return (
    <section aria-labelledby="case-queue-title">
      <h2 id="case-queue-title">醫師工作清單</h2>
      <p className="notice">
        合成資料測試：非真實 HIS。來源鍵與編碼尚未完成真機驗證；正式匯出停用。
      </p>
      <form onSubmit={search} className="queue-filters">
        <label>
          醫師篩選
          <select
            value={physician}
            disabled={busy}
            onChange={(e) => setPhysician(e.target.value)}
          >
            <option value="">全部醫師（協助處理）</option>
            {[
              ...new Set([
                session.operator,
                ...(queue?.physicians ?? []),
                physician,
              ]),
            ]
              .filter(Boolean)
              .map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
          </select>
        </label>
        <label>
          完整病歷號
          <input
            autoComplete="off"
            value={chart}
            disabled={busy}
            maxLength={100}
            onChange={(e) => setChart(e.target.value)}
            placeholder="例如 SYN-0001"
          />
        </label>
        <button disabled={busy} type="submit">
          查詢清單
        </button>
      </form>
      <p>
        病歷號採完整相符搜尋，會跨醫師查詢。同日醫令沒有可判定先後的時間，請逐案核對。
      </p>
      {session.capabilities.includes("admin") &&
        queue?.syntheticRefreshEnabled && (
          <button
            className="secondary"
            disabled={busy}
            onClick={() => void refresh()}
          >
            刷新合成來源
          </button>
        )}
      <p role="status">{busy ? "正在讀取清單…" : status}</p>
      {error && <p role="alert">{error}</p>}
      {queue && (
        <>
          <p>
            符合條件 {queue.total} 案 · 跨日未完成 {queue.overdue}{" "}
            案（優先顯示）
          </p>
          {queue.total === 0 ? (
            <p>沒有符合條件的案件。可改選全部醫師，或核對完整病歷號。</p>
          ) : (
            <div className="table-scroll">
              <table>
                <caption>待填理由案件；同日排列不代表開立先後</caption>
                <thead>
                  <tr>
                    <th>病人／病歷號</th>
                    <th>給藥日期／醫師</th>
                    <th>來源醫令／數量</th>
                    <th>待辦提醒</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.items.map((item) => (
                    <tr key={item.caseId}>
                      <td>
                        <span>{item.patientName}</span>
                        <br />
                        {item.chartNumber}
                      </td>
                      <td>
                        {item.reportingDate}
                        <br />
                        {item.physician}
                      </td>
                      <td>
                        {item.sourceOrder}
                        <br />
                        {item.sourceQuantity} 顆
                      </td>
                      <td>
                        {item.overdue && (
                          <strong>
                            跨日未完成
                            <br />
                          </strong>
                        )}
                        {item.duplicateConcern && (
                          <>
                            同病人同日多筆，請核對
                            <br />
                          </>
                        )}
                        待填理由
                      </td>
                      <td>
                        <button onClick={() => void select(item.caseId)}>
                          核對此案
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {detail && (
        <section className="case-detail" aria-labelledby="case-detail-title">
          <h2 id="case-detail-title" tabIndex={-1} ref={heading}>
            核對案件
          </h2>
          <p>
            <strong>{detail.patientName}</strong> · 病歷號 {detail.chartNumber}{" "}
            · 出生日期 {detail.birthDate}
          </p>
          <p>
            给藥日期 {detail.reportingDate} · 醫師 {detail.physician} · 醫令{" "}
            {detail.sourceOrder}
          </p>
          <p>
            來源量 {detail.sourceQuantity} 顆；回報量 {detail.reportedQuantity}{" "}
            顆
          </p>
          <p>{detail.material}</p>
          {detail.duplicateConcern && (
            <p className="notice">
              同病人同日另有醫令，請確認這一筆；系統不會自動合併或代選。
            </p>
          )}
          <p>
            請核對姓名、病歷號、出生日期與來源醫令。此階段提供案件查閱；用藥理由填寫將於下一步提供。
          </p>
          <details>
            <summary>原始合成來源（{detail.snapshots.length} 版）</summary>
            {detail.snapshots.map((snapshot) => (
              <dl key={snapshot.sequence}>
                {Object.entries(snapshot.raw).map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            ))}
          </details>
          <button
            className="secondary"
            onClick={() => {
              detailGeneration.current += 1;
              setDetail(undefined);
            }}
          >
            關閉案件
          </button>
        </section>
      )}
    </section>
  );
}

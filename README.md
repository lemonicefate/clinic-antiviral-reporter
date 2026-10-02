# clinic-antiviral-reporter

臺灣單一基層診所用的公費流感抗病毒藥劑回報輔助工具。系統從 HIS 唯讀建立待辦，協助填寫理由、核對實發數量與批號，並在人工登入 SMIS 的前提下管理不可變 Excel 匯出及逐案平台結果。

## Current status

Repository foundation only. M0 的 HIS、門診範本、SMIS、授權與營運證據尚未完成，因此正式 Excel 匯出必須保持停用。本 repository 不可用於正式病患作業。

## Start here

- Product baseline: [`tw-flu-antiviral-reporter_SPEC_v1.0.md`](./tw-flu-antiviral-reporter_SPEC_v1.0.md)
- Authoritative amendment: [`tw-flu-antiviral-reporter_SPEC_v1.1.md`](./tw-flu-antiviral-reporter_SPEC_v1.1.md)
- Domain language: [`CONTEXT.md`](./CONTEXT.md)
- Architecture: [`docs/architecture.md`](./docs/architecture.md)
- M0 gates: [`docs/validation/m0-gates.md`](./docs/validation/m0-gates.md)
- Agent workflow: [`AGENTS.md`](./AGENTS.md)

Run the fixture integrity check with Python 3.12 or later:

```powershell
python -m unittest discover -s tests -v
```

Only synthetic or irreversibly de-identified data belongs in this public repository.

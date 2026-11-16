# evals 結果

最新的在最上面。題目與評分標準見 `cases.json`，評分程式 `grade.py`。

## 2026-11-15 第 2 輪（現行題組）

- 換成 LIFF 新版本、新端點（優惠券、會員方案、圖文選單成效）、MINI App 規範等憑記憶答不出的題。
- 本輪另有 2 題沒 skill 也答對（`liff-scancode-unsupported`、`coupon-close-endpoint`），已標 `retired`，下表不列。
- `template-camera-action` 的評分規則在本輪後修正（原本漏判有 skill 的正確答案，也會讓沒 skill 的錯答過關），上表用修正後的規則評分；第 1 輪這題的判定（有 ✅、沒有 ❌）不受影響。


| 項目 | 有 skill | 沒有 skill |
|---|---|---|
| 計分題答對率（12 題） | **12/12（100.0%）** | 0/12（0.0%） |
| 全部題目（12 題） | 12/12 | 0/12 |
| 模型 | claude-opus-5-5 | claude-opus-5-5 |
| 作答方式 | subagent 讀 SKILL.md、用 search.py 查 | subagent 不用任何工具，憑記憶作答 |
| 答案檔 | `evals/runs/2026-11-15-r2-with-skill.json` | `evals/runs/2026-11-15-r2-without-skill.json` |

| 題目 | 可信度 | 有 skill | 沒有 skill | 備註 |
|---|---|---|---|---|
| `template-camera-action` | 實測 | ✅ | ❌ |  |
| `liff-requestfriendship-version` | 官方文件 | ✅ | ❌ |  |
| `liff-2300-date` | 官方文件 | ✅ | ❌ |  |
| `liff-2290-date` | 官方文件 | ✅ | ❌ |  |
| `liff-addtohomev2-version` | 官方文件 | ✅ | ❌ |  |
| `flex-deca-hecto-pc` | 官方文件 | ✅ | ❌ |  |
| `richmenu-insight-daily-path` | 官方文件 | ✅ | ❌ |  |
| `richmenu-insight-metricsfrom` | 官方文件 | ✅ | ❌ |  |
| `coupon-lottery-field` | 官方文件 | ✅ | ❌ |  |
| `membership-users-path` | 官方文件 | ✅ | ❌ |  |
| `insight-demographic-rate` | 官方文件 | ✅ | ❌ |  |
| `miniapp-logo-size` | 官方文件 | ✅ | ❌ |  |

## 2026-11-15 第 1 輪（舊題組，已淘汰）

有 skill 與沒有 skill 幾乎全對：沒有 skill 的模型憑記憶就答對 13/14，這些題沒有鑑別度，已在 `cases.json` 標 `retired` 並換題。表格是當時的評分輸出。


| 項目 | 有 skill | 沒有 skill |
|---|---|---|
| 計分題答對率（1 題） | **1/1（100.0%）** | 0/1（0.0%） |
| 全部題目（14 題） | 14/14 | 13/14 |
| 模型 | claude-opus-5-5 | claude-opus-5-5 |
| 作答方式 | subagent 讀 SKILL.md、用 search.py 查 | subagent 不用任何工具，憑記憶作答 |
| 答案檔 | `evals/runs/2026-11-15-with-skill.json` | `evals/runs/2026-11-15-without-skill.json` |

| 題目 | 可信度 | 有 skill | 沒有 skill | 備註 |
|---|---|---|---|---|
| `liff-share-version` | 官方文件 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `liff-scancodev2-version` | 官方文件 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `flex-deca-hecto-version` | 官方文件 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `miniapp-notifier-token-ttl` | 官方文件 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `miniapp-messages-per-token` | 官方文件 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `miniapp-template-count` | 官方文件 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `follow-unblocked` | 官方文件 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `idtoken-alg` | 官方文件 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `richmenu-image-rules` | 實測 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `text-utf16` | 實測 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `flex-unknown-prop` | 實測 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `token-v21-count` | 官方文件 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `label-by-placement` | 實測 | ✅ | ✅ | 沒 skill 也對：不計分，要換題 |
| `template-camera-action` | 實測 | ✅ | ❌ |  |


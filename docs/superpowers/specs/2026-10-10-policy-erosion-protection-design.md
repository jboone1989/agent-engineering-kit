# 设计：政策防侵蚀协议（strict 模式）

- 日期：2026-10-10
- 状态：已与需求方对齐设计，待实现
- 目标版本：0.4.0
- 关联：README "What it cannot enforce"（本设计缩小其中一条边界）

## 1. 问题

AEK 的核心承诺是 policy.json 是边界的唯一事实源、CI 强制执行。但 policy 本身可以被悄悄放宽：在修 bug 的同一个 PR 里顺手删一条 forbidden、把模块挪进 `unmanaged_modules`、关掉 `check_cycles`。这是目标侵蚀回路——一旦发生一两次没被发现，标准就持续下滑，所有架构检查名存实亡。当前唯一的闸是人审 policy diff，而人审在 agent 高速迭代的压力下最容易沦为橡皮图章。

## 2. 目标

把"policy 被悄悄放宽"从静默事件变成 **CI 必拦、有审计链、可归因**的事件：

1. policy 变更必须与代码变更隔离（单独 PR）。
2. 任何放宽型变更必须携带带理由的审计条目；裸放宽（naked relaxation）CI 直接 fail。
3. 审计历史防篡改：删改历史条目 → 链断 → fail。
4. 全部行为挂在 `strict` 开关下，缺省关闭；旧 policy 不加任何字段则行为与 0.3.3 完全一致。

## 3. 非目标

- 不防"商量好的侵蚀"：真人 review 通过的放宽是合法操作，本协议只把它从静默变成响亮、有理由、可归因。
- 不做 GPG/签名，sha256 链足够。
- 不建 policy 服务器、不追踪 relaxations 之外的 policy 历史。
- 不改变 sync 行为（relaxations 存于 policy.json，sync 本来就不碰 policy）。
- guard.py 保持只读执法器：放宽写入权在 kit CLI，不在 vendored guard。

## 4. Policy schema 扩展（schema_version 仍为 1，字段全部 optional）

```json
{
  "strict": true,
  "relaxations": [
    {
      "date_utc": "2026-10-10T08:00:00+00:00",
      "reason": "publishing 直连 contracts，废除 memory 中转层",
      "changes": ["removed_forbidden: publishing:memory"],
      "prev_entry_sha256": "0000...0000"
    }
  ]
}
```

### 4.1 字段定义

| 字段 | 约束 |
| --- | --- |
| `strict` | bool，缺省 `false` |
| `relaxations` | list，按时间追加；每条目字段如下 |
| `date_utc` | ISO 8601 UTC 时间戳字符串 |
| `reason` | 非空字符串 |
| `changes` | 非空列表，元素为 §5 定义的规范变更串 |
| `prev_entry_sha256` | 64 位 hex；首条为 64 个 `0`，否则为**上一条目规范化 JSON 的 sha256** |

**链语义（相对讨论稿的修正）**：链连接的是**条目与条目**（`prev_entry_sha256` = 上一条目 canonical JSON 的哈希），不是 policy 状态指纹。理由：policy 实质字段在最后一次 relax 之后发生**收紧**（加 forbidden、加 tests 等）是合法且不需要条目的，若链锚定 policy 指纹，收紧会误伤为断链。条目链只保证历史条目不可删改；"当前 policy 相对 base 有未解释的放宽"由 CI 的 naked relaxation 检测兜底（§6）。

`validate_policy` 扩展：`strict` 非 bool 拒绝；`relaxations` 存在时逐条目校验上述约束并重算哈希验证链条完整性，断链抛 `PolicyError`。字段存在即验证，与 `strict` 取值无关。

### 4.2 规范化 JSON

条目哈希与指纹均使用现有 `policy_fingerprint` 同款规范化：`json.dumps(value, sort_keys=True, separators=(",", ":"))` 后 UTF-8 编码取 sha256。

## 5. 什么算"放宽"（机器可判枚举）

按语言取**有效值**比较（Python `check_cycles` 缺省 false，TypeScript 缺省 true）：

| # | 变更 | 判定 | 规范变更串 |
| --- | --- | --- | --- |
| 1 | forbidden 对移除 | old 有、new 无 | `removed_forbidden: <src>:<dst>` |
| 2 | allowed 边移除 | old 有、new 无 | `removed_allowed: <src>:<dst>` |
| 3 | unmanaged_modules 新增 | new 有、old 无 | `unmanaged: <module>` |
| 4 | module_coverage 关闭 | old 有效值 `top_level`、new 为 `off` | `coverage_off` |
| 5 | 循环检查关闭 | old 有效值 true、new 有效值 false | `cycles_disabled` |
| 6 | tests 条目移除 | old 有、new 无（按条目标识比较） | `removed_test: <json.dumps(argv, separators=(",",":"))>` |
| 7 | strict 关闭 | old true、new false | `strict_disabled` |

收紧方向（加 forbidden、加 modules、加 allowed 边、coverage 开启、cycles 开启、加 tests、strict 开启）不需要条目——欢迎的方向不设摩擦。

**tests 修改按"移除+新增"处理**：换测试命令的移除侧也需要条目。宁可误伤（改个等价命令也要理由），不可漏放。

## 6. 两个执法点

### 6.1 `aegkit relax`（kit CLI，cli.py）

```
aegkit relax <project-root> --reason "..."
    [--remove-forbidden src:dst]... [--remove-allowed src:dst]...
    [--unmanage module]... [--coverage-off] [--no-cycles]
    [--remove-test N]... [--strict-off]
```

流程：读旧 policy → 应用变更 → `validate_policy(new)` → 判定变更集合，若不含任何 §5 放宽型变更则报错不写 → 追加条目（`date_utc` 取当前 UTC，`changes` 生成规范串，`prev_entry_sha256` 接链）→ 写回 → 打印条目摘要。

拒绝规则（均 exit 2，不写回）：
- `--reason` 缺失或空白
- 未提供任何变更 flag，或变更后与旧 policy 等价/更严
- 应用后 policy 非法
- 旧 policy `strict` 不为 true（提示：先开 strict；直接收紧不需 relax）

放 kit CLI 而非 vendored guard 的理由：目标项目默认未安装 kit，agent 想放宽时天然撞墙，操作权回到人；审计者不同体为写入口。

### 6.2 guard.py strict 分支（vendored，只读）

`check` 新增可选参数 `--ci-base <git-ref>`，由生成的 workflow 传入；仅当 policy `strict == true` 时激活。两个子检查：

**naked relaxation 检测**：
- `git show <base>:.agent-engineering/policy.json` 取旧 policy（文件不存在按 `{}` 处理）
- 按第 5 节枚举计算 base→current 的全部放宽型变更
- **新增条目** = current 的 `relaxations` 中第 `len(base.relaxations)` 条之后的条目（relax 只追加；改写历史会被 §4.1 链验证拦截，故前缀假设安全）
- 每个放宽型变更必须被某个新增条目的 `changes` **精确匹配**（按第 5 节规范串逐字符串相等）覆盖，否则 fail 并列出未解释变更

**变更隔离检查**：
- `git diff --name-only <base>...HEAD`（在 CI checkout 内）
- 若 `.agent-engineering/policy.json` 有变更，则全部变更路径必须落在白名单：`.agent-engineering/**`、`.github/workflows/engineering-guard.yml`、`ARCHITECTURE.md`
- 工作流含义：先 relax（纯 policy PR），再代码 PR 用掉自由度——先立法，后用权

**本地/无 base 行为**：未传 `--ci-base` → 跳过两个子检查，打印一行 `NOTE: strict policy isolation is enforced in CI`，不影响退出码（与 `--arch-only` 同一哲学：CI 是执法点）。传了 `--ci-base` 但 git 不可用或调用失败 → fail（遵守"missing tools 永不视为成功"）。

**退出码沿用现有约定**：`PolicyError` → 2；check 失败 → 1；成功 → 0。strict 子检查失败按 check 失败计。

## 7. CI workflow 变更

生成的 `engineering-guard.yml`：PR 场景传 `--ci-base ${{ github.event.pull_request.base.sha }}`；push 场景传 `github.event.before`（首推/空值时省略该参数）。`sync` 升级时 guard 与 workflow 属 managed 文件，未被用户手改的项目跑 `aegkit sync` 即可获得。

## 8. 兼容与迁移

- 旧 policy（无 `strict`/`relaxations`）：所有新逻辑不激活，行为与 0.3.3 一致；现有测试即回归。
- 老项目首次 relax：链从全零起点开始，无需迁移脚本。
- 老项目启用 strict：直接编辑 policy 加 `"strict": true`（收紧方向，无需条目），跑 `aegkit sync` 更新 guard/workflow。

## 9. 测试计划（沿用现有 mock 风格）

1. `validate_policy`：strict 非 bool 拒绝；relaxations 条目缺字段、空 reason、坏 hex、首条 prev 非全零、链条断裂——逐一拒绝；合法链通过。
2. 放宽 diff：第 5 节七类逐一识别；收紧集合识别为空；Python/TypeScript 的 `check_cycles` 缺省语义分别覆盖。
3. naked relaxation：base+current+条目覆盖 → 过；缺条目 → fail 且列出缺失变更；条目在 base 已存在（非新增）→ 不算覆盖。
4. 隔离：mock `git diff --name-only` 输出，白名单内/外两态；policy 无变更时不触发。
5. relax CLI：正常写入并接链；空理由拒；仅收紧拒；产出非法拒；strict=false 拒。
6. 端到端：init（strict）→ relax → check 绿；手工删一条审计条目 → check 红（断链）；手工裸删 forbidden → CI 场景（传 `--ci-base`）红。
7. real-adapters 集成不受影响（本设计不触碰适配器层）。

## 10. 文档更新

- README：新增 "Policy erosion protection (strict mode)" 节；"What it cannot enforce" 增补"审计链防的是悄悄的侵蚀，不防商量好的侵蚀"。
- `docs/中文使用指南.md` 同步；`CHANGELOG.md` 记 0.4.0。
- `docs/github-publication.md`：ruleset 建议 `.agent-engineering/**` 强制 CODEOWNERS review——"验证是真人审的"这层仍是 GitHub 的职责，工具不假装能验人性。

## 11. 副作用与观察指标（可证伪）

预判副作用回路及对策：
- 摩擦让人不开 strict → opt-in 设计；文档写明适用场景（agent 密集迭代、review 易走过场的仓库）。
- agent 学会编漂亮理由 → 理由质量交给 review；条目进 PR diff，敷衍可见。
- 双 PR 流程被嫌烦 → 白名单允许 ARCHITECTURE.md 随行；文档说明顺序（先立法后用权）。

开启 strict 的仓库按月观察：relax 次数、被拦的 naked relaxation 次数。长期全零 = 没有侵蚀发生（好），或没人开 strict（去查采用率）。

## 12. 设计决策记录

- **条目哈希链而非 policy 指纹链**（相对讨论稿的修正）：policy 指纹链会把合法收紧误伤为断链；条目链只防历史篡改，"未解释的放宽"交给 CI base diff 兜底，两机制各管一段。
- **relax 在 kit CLI 不在 guard**：抬高 agent 绕过成本（目标项目未装 kit）；guard 保持只读。
- **tests 修改从严**：移除侧需要条目，宁可误伤不漏放。
- **`strict_disabled` 本身是放宽**：关掉 strict 等于关掉全部检查，必须留痕。

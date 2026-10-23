# 全量账号搜索与详情：RED 评审

审计底座已完成 GREEN，47 项评审测试通过；PostgreSQL 15 项验证通过，
全量后端在本批测试加入前为 1311 passed、4 skipped。见 `audit-green-review.md`。

当前整体完成 10/36 项。任务 4.1 已完成 RED 准备，等待评审后实现，
没有将“已生成测试”等同于搜索、详情功能已完成。

## 测试与结果

测试：`backend/tests/admin_console/test_user_directory.py`。

```bash
cd backend
uv run pytest tests/admin_console/test_user_directory.py -q --tb=short \
  --junitxml=../openspec/changes/redesign-admin-console/evidence/user-directory-red.xml
```

实际结果：**40 failed, 10 passed in 3.59s**，**0 收集/fixture 错误，0 跳过**。
失败原因是现有列表忽略新筛选/校验，且 GET 详情尚未提供（405），符合预期缺失行为。
已通过项保留空搜索、原分页校验、原列表 401/403 作为兼容基线。
完整输出见 `user-directory-red.txt`、`user-directory-red.xml`。
新测试 Ruff 及格式检查通过，见 `user-directory-ruff.txt`、`user-directory-format.txt`。

| 覆盖 | 用例数 |
|---|---:|
| 邮箱/中文显示名、大小写、首尾空白、字面 `%`/`_`/反斜杠、无结果及 SQL 片段 | 10 |
| 角色与状态独立筛选，保留禁用、排除软删除 | 5 |
| 搜索 OR 与角色/状态 AND 组合 | 3 |
| 默认第一页之外的账号、筛选后分页/总数及 UUID 排序 | 1 |
| 空搜索兼容旧列表 | 3 |
| 100 个中文字符边界 | 1 |
| 超长搜索、非法角色/状态与分页校验 | 11 |
| 目标有效会话计数，不计过期/撤销/其他账号且不修改会话 | 1 |
| 禁用账号与管理员自身详情 | 2 |
| 不限额/有限额/占用超限的只读滚动额度快照 | 3 |
| 凭据与完整私有资料链路不泄露、伪造归属参数不改变投影 | 1 |
| 不存在/软删除账号及非法 UUID 的具体原因 | 3 |
| 匿名/成员/只读角色读取列表与详情的 401/403 | 6 |

## 明确的接口契约

- q 原始长度至多 100 字符，匹配前 trim；百分号、下划线及反斜杠是字面字符。
- 全量筛选后分页，保持 `(created_at ASC,id ASC)` 及旧 UserRead 字段。
- 详情仅 `{user,active_session_count,chat_limit}`；会话计数仅未过期未撤销。
- chat_limit 使用既定额度快照形态；本批只验证详情读取，额度新 API 和调整在 4.2 实现。
- 详情不修改会话、额度、资料或凭据；读取他人资料的原身份边界保留。
- 没有编写搜索/详情生产代码，没有修改用户已有的前端页面。

## 评审门禁

`openspec/config.yaml:64` 要求：

> 输出红测试代码后必须立刻停止生成，并明确提示用户：“红测试已生成，请评审。确认无误后，请回复‘继续’，我将进入绿测试阶段。”在用户明确回复“继续”或给出修改意见前，不得进入绿测试阶段。

待本批确认后继续任务 4.1 GREEN；上一批审计实现与验证已全部完成。


用户后续明确统一确认全部 RED 评审；4.1 GREEN 已通过 50 项测试，见 user-directory-green.txt。

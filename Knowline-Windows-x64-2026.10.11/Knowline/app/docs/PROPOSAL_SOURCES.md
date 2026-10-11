# 方案来源选择修复

已部署到原实例及原端口。刷新或重新打开 Knowline 后使用。

方案可以只勾选知识库、只提供论文、只提供代码，也可以组合。已选知识库无需额外勾选一份平台资料；导入知识库即使没有对应的平台 PDF 成员也能创建方案任务。未选择任何来源仍提示选择知识库或资料，未就绪知识库仍提示先完成构建。

错误源于后端先把知识库成员展开为 resource_ids，再调用要求非空的通用资料校验；导入知识库有知识内容却没有平台成员，因此错误显示“至少选择一份可用论文或代码”。修复仅允许方案在有已选知识库时使用空资料集合，不放宽普通资料任务的选择要求。非空资料继续验证状态，知识库仍冻结已验证的快照及 SHA256，并保留修订与证据检查。

修改：`backend/store.py`；`frontend/src/ProposalWorkbench.tsx`、`i18n.tsx`。界面添加中英文来源任选说明，导入知识库数量显示其实际来源数。另更新打包/审计/部署/静态资源核对脚本及三个启动入口。

验收均使用合成资料，没有运行生成模型：

- API：知识库单独、包含论文的知识库单独、论文单独、代码单独、组合，各自创建 Word 和 PPT；冻结知识内容、空/非空资料范围正确。空来源、未就绪知识库、普通任务空资料、错误修订均维持拒绝。14 个检查通过。
- 实际候选运行包与 Edge 界面：仅知识库创建 Word/PPT，补充资料选择为空；论文和代码分别创建任务；英文说明正常。没有浏览器脚本错误。
- 运行包全部后端模块及入口与源码匹配；部署前后 resources、knowledge-bases、groups、jobs、relations、ideas 六个集合的数据哈希相同。
- 当前运行包为 `Knowline/Knowline.exe`，保留先前 optimized 包用于部署失败恢复。没有数据库迁移或用户资料删除。

证据：`verification/proposal-sources.json`、`proposal-sources-ui.json`、`proposal-kb-only.png`、`proposal-package.json`、`optimization-runtime-proposal.json`、`proposal-deployment.json`、`proposal-installed-smoke.json`。

复测：`python tests/proposal-sources.py`；界面夹具由 `python tests/proposal_fixture.py` 创建，再运行 `node tests/proposal-sources-ui.mjs`。夹具始终位于 verification，勿改成用户真实资料目录。前端构建与原配置一致；未构建时界面复测使用当前安装资源。

这里验证的是来源选择、任务创建与冻结范围；没有把生成任务成功称为 Word/PPT 文档已经生成，也没有放宽成果引用校验。

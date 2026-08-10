# 0052 · 工程收尾（P8）：venv 瘦身 / 文档归档 / Electron 打包评估

日期：2026-08-10
状态：已接受
基准：PROJECT_AUDIT P8

## 一、范围与结论

### 1. venv 瘦身（完成）
- 卸载 chromadb 的传递依赖 **`kubernetes`（约 75MB，36.0.3）**：Tsumugi 单机内嵌使用
  chromadb，仅分布式集群模式才 import kubernetes（已验证 `import chromadb` 后
  `kubernetes not in sys.modules`）。卸载后 chromadb 正常导入、后端正常启动、pytest
  **420 全通过**、`/api/items` 正常返回。
- **已知取舍**：`pip check` 会报 "chromadb requires kubernetes"（pip 视角的"缺依赖"）。
  风险：未来升级 chromadb 若把分布式模块放进启动路径可能触发；Tsumugi 不使用集群模式，
  此风险可控。venv 从 ~1281MB → **1205MB**。
- 若未来担心，可 `pip install kubernetes` 一键恢复。

### 2. 文档归档（完成）
- `prompts/`（00-26 号设计文档 + AGENTS.md + AGENT_UI.md，共 29 个文件）为 gitignore
  私有内容，无版本保护。已整体归档到
  `E:\program\MyProject\项目简报\Tsumugi\prompts-archive\`（仓库外，与讨论简报同级）。
- 归档为一次性快照；后续 prompt 更新时建议定期刷新该目录。

### 3. Electron 打包 embedding（评估，暂不实施修复）
- 现状（ADR 0012 止损点）：独立打包版 embedding 不可用——transformers `_LazyModule`
  依赖文件系统真实存在的 `models/__init__.py`，PyInstaller PYZ 归档使其找不到，
  已尝试 3 种收集方案均失败，按止损点停止。Docker 是当前已验证的主要分发路径；
  Web / 本地开发不受影响。
- **可选修复路径（需单独排期，不阻塞当前）**：
  1. **升级 transformers**：新版对 lazy import 有重构，配 PyInstaller 重新打包验证
     （改动小、需重打包实测，约 20+ 分钟/次）；
  2. **换 ONNX embedding**：spec 已收集 onnxruntime；把 embedding 切到 ONNX 版
     （bge-small-zh 需导出 ONNX，或打包版用 chroma 默认 ONNX 模型）——可**同时去掉
     torch（约 500MB）**，是根治方案，但模型质量/接口需验证；
  3. **换打包器**（Nuitka/embedded Python）工程量最大，最后考虑。
- **结论**：本轮不做重打包（避免高不确定性 + 长时间构建）；记为待办，未来若要把
  exe 作为主分发再启动，推荐先试路径 1，根治走路径 2。

## 二、测试

- pytest **420 passed**（kubernetes 卸载后全量回归）；vitest 212 / build 通过（未改动
  前后端代码）。

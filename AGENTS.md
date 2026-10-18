# 构建约定

- 必须先读唯一构建操作文档 [docs/BUILD.md](docs/BUILD.md)。所有构建、缓存和发布说明只在该文档维护，其他文档引用它。
- 本仓库的唯一 Linux 分派入口为 `build.sh`；`tools/build/` 是内部阶段实现。Android 总入口为 `arlinux/build.ps1`，开发调试和 Release 使用相同流水线。
- rootfs 在各发行版仓库的 GitHub ARM64 标准 runner 构建；Wine 组件在对应仓库的 x64 标准 runner 构建。Windows 入口使用 GitHub CLI 调度，不依赖 WSL。Wine 和辅助组件是独立下载产物，不放入 rootfs。
- 只使用经过输入、输出和引用文件哈希验证的构建缓存。禁止从旧 ZIP、用户实例、手机导出快照或旧 Wine 归档手工重打包出发布产物。
- 第三方定制优先提交到对应 fork，通过固定提交的子模块引用；已有补丁逐步迁入 fork，避免构建时维护并重放补丁集。

- 每个组件仓库必须独立运行 workflow_dispatch，使用本仓库的 10 GB 免费 Cache；不得通过 workflow_call 将全部任务的缓存计入 arlinux-rootfs。仓库、runner 与依赖图只维护在 tools/build/github-components.json，workflow 薄包装只从唯一模板生成。

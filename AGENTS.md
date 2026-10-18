# 构建约定

- 必须先读唯一构建操作文档 [docs/BUILD.md](docs/BUILD.md)。所有构建、缓存和发布说明只在该文档维护，其他文档引用它。
- 本仓库的唯一 Linux 分派入口为 `build.sh`；`tools/build/` 是内部阶段实现。Android 总入口为 `arlinux/build.ps1`，开发调试和 Release 使用相同流水线。
- rootfs 全部在 Linux/WSL 构建。Bionic Wine 在 Linux/WSL 用 Linux NDK 交叉编译，独立产出运行时归档；它不是 rootfs，不能与 rootfs 合并为一个产物。
- 只使用经过输入、输出和引用文件哈希验证的构建缓存。禁止从旧 ZIP、用户实例、手机导出快照或旧 Wine 归档手工重打包出发布产物。
- 第三方定制优先提交到对应 fork，通过固定提交的子模块引用；已有补丁逐步迁入 fork，避免构建时维护并重放补丁集。

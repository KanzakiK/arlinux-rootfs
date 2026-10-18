# 唯一构建与发布流程

Android 总入口是 `arlinux/build.ps1`。开发、调试和 Release 使用同一入口；
Android 原生组件和 APK 在主机编译，Linux 产品由 GitHub 的免费标准 runner
编译。Windows 只需 PowerShell、Git、GitHub CLI、Python 和 Android 工具链，
不需要 WSL、Linux NDK、Linux 编译目录或旧 rootfs ZIP。

## 产品边界

| 产品 | 构建位置 | 交付方式 |
|---|---|---|
| Yibu | `taowen/arlinux-yibu` 的 `ubuntu-24.04-arm` | 独立 ZIP、输入/输出收据 |
| 其他发行版 | 各自 `taowen/arlinux-发行版` 的 ARM64 runner | 独立发行版 ZIP、收据 |
| Bionic Wine | Wine、FEX、DXVK、Mesa、libhybris 等组件仓库的 x64 runner | 独立运行时、SHA-256、完整源码 |
| Android | Android 项目所在主机 | Debug APK 或签名 Release APK |

Yibu 不包含 Wine，也不等待 Wine 构建。Steam Windows 游戏和 Windows 启动器
按需下载同一份 Bionic Wine。Steamworks 桥、Windows 无障碍和托盘二进制随
Wine 提供，并从对应的下载运行时读取，不能重新放回 rootfs。
更新上述产物边界后，必须先发布并更新匹配的 Wine 下载清单，再发布依赖新
路径的 APK；不能让新版 rootfs 指向缺少配套组件的旧 Wine。

Wine PE 拆成 ARM64/ARM64EC、x64、x86 三个独立编译任务，合并时检查重复文件
的内容一致性。FEX、DXVK、TLS、音频和图形依赖按依赖图并行；只在必要的
组装阶段汇合。Windows runner 只读取系统 Arial 厂商输入，不编译 Wine。
Yibu 在 ARM64 上原生安装 ARM64 软件包，不使用 QEMU 模拟 ARM64。

## 唯一脚本与工作流归属

- `arlinux/tools/build.ps1` 调度 Android 构建及远程 Linux 产品。
- `tools/build/github-products.py` 是跨仓库协调器，可直接在 Windows Python
  执行，通过 `gh workflow run --repo COMPONENT` 独立触发组件任务。
- `tools/build/github-components.json` 是唯一组件仓库、runner 和依赖图定义。
- 每个组件仓库的 `.github/workflows/arlinux-component.yml` 都是独立
  `workflow_dispatch`，不能从 arlinux-rootfs 通过 `workflow_call` 调用。
- 每个仓库共有 10 GB 免费缓存，同一仓库的多个架构和 job 共享额度；
  不是每个 job 各有 10 GB。保留默认容量上限，由 GitHub 淘汰旧缓存。
- 固定下载单独使用仓库级共享 Cache key，不在每个 job 的缓存里重复存放
  NDK、MinGW、Mono 和 Gecko。Wine 的大型完整工作树通过组件产物交付，
  Actions 缓存主要保留有容量上限的增量编译结果。
- 新请求可以从上一份组件产物恢复完整构建缓存，但必须重新验证当前输入、
  全部输出和工具引用的哈希。框架中无关文档的提交不会迫使未变的组件重新编译。
- 主机下载后的产品也保存哈希收据；同一产品再次构建 APK 时先校验本地缓存，
  不重复下载完整 rootfs 或 Wine。修改或损坏的文件会触发重新下载。
- 各仓库的薄工作流从 `tools/build/github-component.workflow.yml` 生成，
  `tools/build/install-github-workflows.py` 负责同步；不复制构建 recipe。
- Linux runner 仍只通过 `build.sh` 分派至本仓库 `tools/build/` 的同一套
  Wine/rootfs recipe。`github-component.py` 负责主机准备、依赖校验和交付。

所有请求固定 Android、构建框架与第三方源码提交；不在编译时自动 pull。
定制修改优先提交到组件 fork，再更新子模块。未修改的厂商输入使用
`tools/build/github-inputs.json` 固定 URL 和 SHA-256。

## 一次准备

登录具备这些公开仓库 workflow 调度权限的 GitHub CLI：`gh auth login`。
协调器使用本机已有认证，不把个人 token 写入 Git、产物或 runner 配置。
组件工作流仅使用自身仓库的临时 `GITHUB_TOKEN` 发布组件产物。
Linux 组件不读取私有 Android 仓库。共享 NDK recipe、音频输入和发行版校验器
由本公开仓库唯一维护；Android 本机构建引用同一份固定提交的 recipe。
Android 音频也由 x64 Linux runner 编译，通过 `audio` 产品下载后验证全部
九个库的哈希及 16 KB 对齐；Gradle 不再隐式调用 WSL。

主机保留 Android 项目 `toolchain.json` 指定的 JDK、SDK、NDK、MSYS2 辅助
工具和原生 Windows Python。无需再填写 desktop-build.json、wine-build.json
或配置 Linux/WSL 路径。远程 runner 的 NDK、LLVM-MinGW、Mono 和 Gecko 由
固定下载清单准备，不消费 Windows 编译库。

组件 workflow 由维护者通过唯一模板安装；先提交推送所有构建源码和模板，
再执行本仓库的 `tools/build/install-github-workflows.py`。同步使用各仓库默认
分支，commit 带 `[skip ci]`；编译由协调器显式独立调度。

## 构建和安装

在 arlinux 根目录运行：

```powershell
./build.ps1 doctor
./build.ps1 build -Configuration Debug
./build.ps1 build -Configuration Release
./build.ps1 rootfs
./build.ps1 rootfs -Distribution omarchy
./build.ps1 wine
./build.ps1 install -Serial DEVICE_SERIAL
./build.ps1 install -Configuration Release -Serial DEVICE_SERIAL -Apk EXACT_TESTED_APK
```

`build` 只构建 APK 必需的 Yibu；Wine 是独立产品，使用 `wine` 命令。
可用 `-FrameworkRef COMMIT` 固定构建框架，用 `-GitHubParallel N` 控制独立
workflow 并行数。Debug 与 Release 都走相同的原生依赖、Yibu、源码校验、
Gradle 包装与内置 ZIP 哈希校验；Release 只增加签名和发布校验。
构建不安装 APK、不修改设备实例、不上传 APK 或 Wine latest。
`install` 仍统一调用 `tools/install-apk.sh`，保留 X300 的安装确认处理。

## 缓存与交付

GitHub Actions Cache 的免费额度为每仓库 10 GB。组件必须在对应仓库启动
独立 workflow，其 cache 才归属该仓库；可复用 workflow 的调用不能实现
缓存额度拆分。不要提高仓库的付费缓存上限，也不要使用收费 larger runner。

使用标准 `actions/cache` 恢复对应组件输出、Make 工具及受限 ccache。缓存
命中后仍检查输入、输出及引用目录哈希；缺少或损坏上游产物时拒绝偷偷
重建整个依赖链。缓存丢失可重新构建，不从旧 ZIP、手机实例或旧 Wine 归档
恢复安装状态。提交相同源码不应使内容缓存失效。

Cache 与 Actions artifacts 是不同配额。跨仓库交付使用各组件仓库的不可变
`arlinux-组件-输入标识` 预发布产物，包括固定请求、分块 SHA-256 与归档
SHA-256。这类组件预发布不能覆盖应用 release、Wine latest 或下载清单。
协调器下载后再次验证哈希和最终产品收据；tar 保留符号链接及可执行位。

| 主机输出 | 路径 |
|---|---|
| APK 内置 Yibu | arlinux/build/cache/artifacts/desktop/default.zip、default.json |
| 其他发行版 | arlinux/build/cache/artifacts/rootfs/ID.zip、ID.json |
| 下载的 Wine | arlinux/build/cache/artifacts/github/wine/ |
| 各产品与调度记录 | arlinux/build/cache/artifacts/github/products.json、github-state/ |
| 精确源码校验视图 | arlinux/build/cache/sources/arlinux-rootfs/COMMIT/ |
| Debug APK | arlinux/out/arlinux-debug.apk、对应收据 |
| Release APK | arlinux/build/release/android/VERSION/arlinux-vVERSION-HASH.apk |

源码校验视图来自固定提交的 Git checkout，只读使用；不能手工修改它后
冒充 runner 的输入。Gradle 和 APK 打包结束时都验证内置发行版。
LXQt 当前仍保留 seed/首次安装协议，不能声称它是完整离线 Yibu。

## 验收和发布

遵循 arlinux/AGENTS.md 与诊断文档。设备验收必须删除被测实例，从当前 APK
内置发行版或当前产物导入全新实例；不能复用旧 home/rootfs/prefix。
Steam 认证仅按测试规范允许的显式备份例外复用。验证首次离线桌面、中文
输入、Downloads、应用及受影响功能；游戏另需验证本项目 Bionic Wine、
自定义兼容工具、GPU 和正常 Play，不能用编译或单元测试代替设备验收。

主机的统一发布命令只消费已经测试的确切产物，不隐式重建：

```powershell
./build.ps1 publish -Apk EXACT_TESTED_RELEASE_APK
./build.ps1 publish-wine -Archive EXACT_TESTED_WINE_TAR_GZ -Check
./build.ps1 publish-wine -Archive EXACT_TESTED_WINE_TAR_GZ
```

沿用 `.secrets/android-release-signing.env` 与
`android/keystores/arlinux-release.jks`，不输出签名密码。
Release 检查符号剥离、16 KB ELF/ZIP 对齐和 v1/v2/v3 签名。
Wine 发布器检查完整 Wine/FEX/DXVK/辅助程序源码，更新 `taowen/wine` latest
与固定下载清单。发布组件预产物不等于完成设备验收或发布正式产品。

官网/Android 发布继续使用现有 Wrangler/R2 配置。发布后检查
https://arlinux.com 和 https://download.arlinux.com/android/latest.json。

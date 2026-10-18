# 唯一构建与发布流程

这是 ARLinux、Linux 发行版和 Bionic Wine 的唯一构建操作文档。开发调试与
Release 使用同一套入口、依赖图、缓存校验及打包实现。其他文档只描述架构、
兼容性或诊断，不维护第二套构建步骤。

## 入口与产物

Android 项目的总入口是仓库根目录 `arlinux/build.ps1`，实现为
`arlinux/tools/build.ps1`。Windows 可以通过它调用 WSL；这不表示所有组件
都要在 Windows 构建。Linux 产品的唯一分派入口是本仓库 `build.sh`。
`tools/build/*.py`、`*.sh`、Gradle 和打包器均为内部阶段，不作为人工拼装流程。

| 产品 | 执行环境与工具 | 实现归属 | 输出 |
|---|---|---|---|
| Android 原生组件、APK | 主机 Android JDK/SDK/NDK；当前 Windows 使用 MSYS2 Bash 辅助 | arlinux；compositor fork | Debug APK 或签名 Release APK |
| Linux rootfs | Linux/WSL、Linux 交叉工具链、ARM64 QEMU、chroot | arlinux-rootfs | 独立发行版 ZIP 与构建收据 |
| Bionic Wine | Linux/WSL、Linux Android NDK、LLVM-MinGW | arlinux-rootfs | 独立 Bionic Wine tar.gz、校验和、源码包、构建收据 |

rootfs 不使用 Windows 工具、Android NDK 或手机安装软件包。Wine 面向 Android
Bionic，因此交叉编译需要 Linux 版 NDK；它不是 Linux rootfs，也不因为脚本
放在本仓库就成为 rootfs 的一部分。Steam 和 Windows 启动器使用同一 Wine 运行时。
Wine 相关的 Steamworks/无障碍辅助程序由 Wine 流水线编译，rootfs 只消费校验过
的辅助产物。APK 内置 Yibu ZIP；Wine 运行时仍为独立下载，不嵌入 rootfs。

## 配置一次

两个仓库及子模块必须位于固定提交；定制修改优先进入对应 fork。未修改的
上游依赖可使用固定版本、校验 SHA-256 的源码归档。不要在构建时自动 pull
源码，或用临时补丁、旧安装实例覆盖正式输入。

Windows 安装 PowerShell 7、JDK、Android SDK、`arlinux/toolchain.json` 指定
的 NDK、MSYS2 Bash/Python/Meson/Ninja。Android Python 使用原生 Windows Python
（默认 `C:/tools/python3.exe`），不使用 MSYS Python。通过 `JAVA_HOME`、
`ANDROID_HOME`、`ARLINUX_BASH`、`ARLINUX_PYTHON` 指定安装位置。

WSL 使用 Linux 文件系统（例如 `/root/src/arlinux-rootfs`）；源码、NDK、
LLVM-MinGW、编译目录不放在 `/mnt/c`。Windows 调度入口和 APK 输出可以在 Windows。
Linux 需要以下软件包，以及本仓库锁定版本的源码/厂商 Mono、Gecko 输入：

```sh
sudo dpkg --add-architecture arm64
sudo apt update
sudo apt install autoconf automake libtool build-essential bison flex curl git \
  cmake meson ninja-build patchelf pkg-config python3 python3-mako python3-zstandard \
  debootstrap qemu-user-static binfmt-support util-linux zstd libarchive-tools jq \
  gcc-aarch64-linux-gnu g++-aarch64-linux-gnu pkgconf:arm64 glslang-tools \
  wayland-protocols libfreetype-dev libexpat1-dev \
  libegl-dev:arm64 libgl-dev:arm64 libgles-dev:arm64 libglvnd-dev:arm64 \
  libwayland-dev:arm64 libx11-dev:arm64 libx11-xcb-dev:arm64 libxcb1-dev:arm64
```

WSL 的 rootfs 包安装阶段需要 root、ARM64 binfmt 和私有 mount namespace。
在 WSL 中配置默认执行用户为 root，或使用具备相应权限的 Linux 构建环境。
不能用手机 Builder APK 代替。Wine 要求支持 ARM64X 的 LLVM-MinGW（LLVM 23+），
Linux NDK 版本与 `arlinux/toolchain.json` 一致。

在 arlinux 中将 `tools/build/desktop-build.example.json` 复制到忽略的
`build/desktop-build.json`，只配置 `format: 1` 和 Linux `framework` 路径。
将 `tools/build/wine-build.example.json` 复制到 `build/wine-build.json`，配置
相同 `framework`、干净且固定提交的 `wineSource`、Linux `ndk`、`mingw`、`addons`。
`addons` 只含厂商 Mono/Gecko 输入，不能指向安装实例或 Wine prefix。
Wine 还需要四款 Arial 文件；默认读取 `/mnt/c/Windows/Fonts`，其他环境通过
`ARLINUX_WINDOWS_FONTS` 指定合法的输入目录。输入文件会记录哈希。

## 构建和安装

以下命令均在 arlinux 根目录执行。Debug 与 Release 只改变配置，经过同一
`Build-Native → Build-Apk` 调用链：原生组件、独立 Wine、rootfs、当前源码校验、
同一个 Gradle 包装流程、APK 内 ZIP 哈希核对。Release 随后签名及校验。

```powershell
./build.ps1 doctor
./build.ps1 build -Configuration Debug
./build.ps1 build -Configuration Release
./build.ps1 build -Configuration Debug -Rebuild
./build.ps1 install -Serial DEVICE_SERIAL
./build.ps1 install -Configuration Release -Serial DEVICE_SERIAL -Apk EXACT_TESTED_APK
```

构建不安装 APK、不修改设备实例、不发布。`install` 统一调用
`tools/install-apk.sh`，包含 X300 安装确认处理。构建无需设备序列号。
可用 `-LinuxDistro NAME`、`-DesktopConfig FILE`、`-WineConfig FILE` 选择本机环境。
两个配置必须引用同一 arlinux-rootfs checkout。

只开发某类组件时使用总入口的目标命令；这些命令调用同一内部阶段，不维护
替代打包方案。首次 rootfs 构建前先构建 Wine，准备匹配的兼容辅助程序。

```powershell
./build.ps1 native
./build.ps1 wine
./build.ps1 rootfs
./build.ps1 rootfs -Distribution omarchy
```

Linux 开发者可以直接使用同一个 Linux 分派器，`--android-repo` 指向 Android
源码（共享原生 recipe、WebView 商店集成和配置输入，不消费 Windows 编译产物）：

```sh
./build.sh doctor
./build.sh wine --config /path/to/wine-build.json --android-repo /path/to/arlinux
./build.sh rootfs --config /path/to/desktop-build.json --android-repo /path/to/arlinux \
  --distribution yibu --output /path/to/default.zip
./build.sh list
./build.sh validate distributions/my-linux
./build.sh verify /path/to/bundle.zip
```

发行版始终从当前 seed 和 recipe 构建。带 `guest/build-desktop.sh` 的发行版
通过 QEMU/chroot 安装桌面软件，再封装离线 ZIP；LXQt 当前保留其 seed/首次安装
协议，由同一流水线封装，不声称它是完整离线桌面。不能把它当作内置 Yibu。

## 缓存与可追溯性

`arlinux-rootfs/build/pipeline/<stage>/<identity>/generation-*` 保存分阶段编译
产物及收据；`arlinux/build/cache/native` 保存 Android 原生缓存收据。
只在输入内容、输出及所引用编译目录哈希均吻合时复用；提交相同源码不会
使内容缓存失效。失败构建不能覆盖成功收据。Wine 的 Make 缓存保留在原绝对
路径；不能搬动带编译路径的 work tree 后冒充有效缓存。

`-Rebuild` 绕过阶段复用，但仍允许复用校验过的不可变下载。
旧 `out/rootfs` ZIP、手机实例导出、旧 Wine runtime 的局部重打包、手工覆盖的
ZIP 都不是构建缓存；不支持恢复为流水线输入。更新 APK 不自动替换用户实例。

| 输出 | 路径 |
|---|---|
| APK 内置 Yibu | arlinux/build/cache/artifacts/desktop/default.zip、default.json |
| 其他 rootfs | arlinux/build/cache/artifacts/rootfs/ID.zip、ID.json |
| Debug APK | arlinux/out/arlinux-debug.apk、对应 .json 和 .desktop.json |
| Release APK | arlinux/build/release/android/VERSION/arlinux-vVERSION-HASH.apk、对应收据 |
| Wine | arlinux-rootfs/build/artifacts/wine/arlinux-wine-bionic.tar.gz、.sha256、源码包、runtime.json |

Gradle 拒绝缺少收据、缺模块或不匹配当前源码的内置 rootfs。APK 构建结束再次
核对 `assets/default.zip`，必须与通过校验的流水线产物相同。

## 验收和发布

遵循 arlinux/AGENTS.md 和诊断文档；设备测试删除被测实例，通过当前 APK 内置
安装或导入流程重装，不能恢复旧 home/rootfs/prefix。只允许明确的账号认证
备份例外及校验过的不可变厂商下载缓存。首次 Steam 安装/登录测试从无认证
状态开始。验收离线首次启动、输入、应用和受影响功能；Steam 游戏需验收
本项目 Bionic Wine、自定义兼容工具、GPU 和正常 Play 流程。发布器不代替验收。

Release 版本号在 `arlinux/android/host/build.gradle`，发布说明在
`arlinux/tools/release-notes/android-VERSION.txt`。签名材料保存在忽略的
`.secrets/android-release-signing.env` 和 `android/keystores/arlinux-release.jks`；
沿用现有证书。环境文件使用 `ARLINUX_RELEASE_STORE_PASSWORD`、
`ARLINUX_RELEASE_KEY_PASSWORD`、`ARLINUX_RELEASE_KEY_ALIAS`，不记录到日志或 Git。
Release 校验原生符号剥离、16 KB ELF/ZIP 对齐及 v1/v2/v3 签名。

提交源码及子模块后，在 arlinux 根目录发布确切验收产物；不重建：

```powershell
./build.ps1 publish -Apk EXACT_TESTED_RELEASE_APK
./build.ps1 publish-wine -Archive EXACT_TESTED_WINE_TAR_GZ -Check
./build.ps1 publish-wine -Archive EXACT_TESTED_WINE_TAR_GZ
```

Wine 发布使用本仓库同一个分派器的 `publish-wine` 阶段，验证配套源码包，上传
至 `taowen/wine` latest 并更新 `runtime/tools/windows-downloads.tsv` 固定 SHA-256。
发布新 Wine 后按当前源码重建 rootfs/APK，验收其首次自动下载路径。
发布独立发行版使用 `./build.sh publish-rootfs ID TAG EXACT_TESTED_ZIP`，仅上传。

APK 发布使用已登录的 Wrangler：`npm ci --prefix arlinux.com` 后检查
`npm --prefix arlinux.com run whoami`。目标为 R2 `arlinux-downloads`；版本 APK
和 latest 元数据上传后更新网站并部署。网络阻断 workers.dev 时可设置
`ARLINUX_RELEASE_UPLOAD_ZONE=arlinux.com`；临时域名/Worker 随上传结束删除。
检查 https://arlinux.com 和 https://download.arlinux.com/android/latest.json。

## 维护边界

删除的旧入口包括 `rootfs.ps1`、设备 Builder/prepare/offline 导出流程、独立的
Release 构建逻辑、逐阶段手工拼装 Wine 和旧 ZIP/runtime 刷新器。不要重新引入。
修复内部阶段后仍由上述入口构建和验收；诊断探针不是替代产品构建器。

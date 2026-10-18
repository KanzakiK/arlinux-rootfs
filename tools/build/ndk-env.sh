# Shared Android NDK discovery for Linux, macOS and Windows Bash hosts.

NDK_VERSION="$(python3 - "$ROOT/toolchain.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['androidNdk'])
PY
)"
ANDROID_API="${ARLINUX_ANDROID_API:-$(python3 - "$ROOT/toolchain.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['androidMinSdk'])
PY
)}"
ndk_sdk_root="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"
NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-$ndk_sdk_root/ndk/$NDK_VERSION}}"
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) NDK="$(cygpath -u "$NDK")" ;;
esac
ndk_prebuilt_root="$NDK/toolchains/llvm/prebuilt"

ndk_revision="$(sed -n 's/^Pkg\.Revision[[:space:]]*=[[:space:]]*//p' "$NDK/source.properties" 2>/dev/null | tr -d '\r')"
if [[ "$ndk_revision" != "$NDK_VERSION" ]]; then
    echo "Android NDK $NDK_VERSION is required; found '${ndk_revision:-unknown}' at $NDK" >&2
    echo "set ANDROID_NDK_HOME to the NDK $NDK_VERSION checkout" >&2
    exit 2
fi

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
        ndk_host_candidates=(windows-x86_64)
        # Meson is an MSYS program here and must spawn the MSYS Ninja. A
        # native Windows Ninja cannot execute generated /usr/bin commands.
        if [[ -x /usr/bin/ninja ]]; then export NINJA=/usr/bin/ninja; fi
        ;;
    Darwin*) ndk_host_candidates=(darwin-x86_64 darwin-arm64) ;;
    *) ndk_host_candidates=(linux-x86_64) ;;
esac

NDK_PREBUILT=
for ndk_host in "${ndk_host_candidates[@]}"; do
    if [[ -d "$ndk_prebuilt_root/$ndk_host" ]]; then
        NDK_PREBUILT="$ndk_prebuilt_root/$ndk_host"
        break
    fi
done
if [[ -z "$NDK_PREBUILT" ]]; then
    echo "Android NDK host toolchain not found under $ndk_prebuilt_root" >&2
    echo "set ANDROID_NDK_HOME to the NDK $NDK_VERSION checkout" >&2
    exit 2
fi

NDK_BIN="$NDK_PREBUILT/bin"
export NDK_VERSION ANDROID_API NDK NDK_PREBUILT NDK_BIN

// SPDX-License-Identifier: Apache-2.0
// Native Android implementations of the allocator/loader hooks used by the
// shared desktop WSI. No foreign libc or GPU-specific allocator is involved.
#include <android/hardware_buffer.h>
#include <android/hardware_buffer_jni.h>
#include <android/dlext.h>
#include <hybris/gralloc/gralloc.h>
#include <hardware/hardware.h>
#include <dlfcn.h>
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <mutex>
#include <unordered_map>

// The shared Android platform headers omit this exported libnativewindow API.
extern "C" const native_handle_t* AHardwareBuffer_getNativeHandle(const AHardwareBuffer*);

namespace {
struct Allocation { AHardwareBuffer* buffer; unsigned references; };
std::mutex allocationMutex;
std::unordered_map<buffer_handle_t, Allocation> allocations;
}

extern "C" void hybris_gralloc_initialize(int) {}
extern "C" void hybris_gralloc_deinitialize() {}

extern "C" int sync_wait(int fd, int timeout) {
    if (fd < 0) { errno = EINVAL; return -1; }
    pollfd fence{fd, POLLIN, 0};
    int result;
    do { result = poll(&fence, 1, timeout); } while (result < 0 && errno == EINTR);
    if (result > 0 && (fence.revents & POLLIN)) return 0;
    if (!result) errno = ETIME;
    else if (result > 0) errno = EINVAL;
    return -1;
}

extern "C" int hybris_gralloc_allocate(int width, int height, int format, int usage,
                                       buffer_handle_t* handle, uint32_t* stride) {
    if (width <= 0 || height <= 0 || !handle || !stride) return -EINVAL;
    AHardwareBuffer_Desc desc{};
    desc.width = width; desc.height = height; desc.layers = 1; desc.format = format;
    // Gralloc0 and AHardwareBuffer agree on CPU, texture and render-target bits.
    // Composer/framebuffer bits belong to Android's display service, not this WSI.
    constexpr uint64_t accepted = AHARDWAREBUFFER_USAGE_CPU_READ_MASK | AHARDWAREBUFFER_USAGE_CPU_WRITE_MASK |
        AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE | AHARDWAREBUFFER_USAGE_GPU_COLOR_OUTPUT |
        AHARDWAREBUFFER_USAGE_PROTECTED_CONTENT;
    desc.usage = uint32_t(usage) & accepted;
    AHardwareBuffer* buffer = nullptr;
    int error = AHardwareBuffer_allocate(&desc, &buffer);
    if (error) {
        fprintf(stderr, "Bionic WSI: AHardwareBuffer allocation failed: %d %dx%d format=%d gralloc=0x%x ahb=0x%llx\n",
                error, width, height, format, usage, (unsigned long long)desc.usage);
        return error;
    }
    AHardwareBuffer_describe(buffer, &desc);
    const auto native = reinterpret_cast<buffer_handle_t>(AHardwareBuffer_getNativeHandle(buffer));
    if (!native) { AHardwareBuffer_release(buffer); return -EINVAL; }
    std::lock_guard<std::mutex> lock(allocationMutex);
    allocations.emplace(native, Allocation{buffer, 1});
    *handle = native; *stride = desc.stride;
    return 0;
}

extern "C" AHardwareBuffer* hybris_gralloc_get_hardware_buffer(buffer_handle_t handle) {
    std::lock_guard<std::mutex> lock(allocationMutex);
    auto found = allocations.find(handle);
    return found == allocations.end() ? nullptr : found->second.buffer;
}

extern "C" int hybris_gralloc_retain(buffer_handle_t handle) {
    std::lock_guard<std::mutex> lock(allocationMutex);
    auto found = allocations.find(handle);
    if (found == allocations.end()) return -EINVAL;
    ++found->second.references;
    return 0;
}

extern "C" int hybris_gralloc_release(buffer_handle_t handle, int) {
    AHardwareBuffer* buffer = nullptr;
    {
        std::lock_guard<std::mutex> lock(allocationMutex);
        auto found = allocations.find(handle);
        if (found == allocations.end()) return -EINVAL;
        if (!--found->second.references) { buffer = found->second.buffer; allocations.erase(found); }
    }
    if (buffer) AHardwareBuffer_release(buffer);
    return 0;
}

extern "C" int hybris_gralloc_import_buffer(buffer_handle_t, buffer_handle_t*) { return -ENOTSUP; }

extern "C" int bionic_hw_get_module(const char* id, const hw_module_t** module) {
    static void* hardware = dlopen("/system/lib64/libhardware.so", RTLD_NOW | RTLD_LOCAL);
    using GetModule = int (*)(const char*, const hw_module_t**);
    static auto get = hardware ? reinterpret_cast<GetModule>(dlsym(hardware, "hw_get_module")) : nullptr;
    return get ? get(id, module) : -ENOENT;
}

extern "C" void* bionic_get_exported_namespace(const char* name) {
    using GetNamespace = void* (*)(const char*);
    static auto get = reinterpret_cast<GetNamespace>(dlsym(RTLD_DEFAULT, "android_get_exported_namespace"));
    return get ? get(name) : nullptr;
}

extern "C" void* bionic_dlopen_ext(const char* path, int flags, const android_dlextinfo* info) {
    return android_dlopen_ext(path, flags, info);
}

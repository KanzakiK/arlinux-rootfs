/* SPDX-License-Identifier: MIT
 * Run via the Bionic Steam compatibility tool with an owned SteamAppId.
 * Repeated interface creation catches accidental reuse of DLL control data.
 * Optional argv[1] is an installed game's unmodified steam_api[64].dll.
 */
#include <windows.h>
#include <stdio.h>
typedef void *(__cdecl *create_t)(const char *, int *);
typedef int (__thiscall *pipe_t)(void *);
typedef int (__thiscall *user_t)(void *, int);
typedef void *(__thiscall *get_t)(void *, int, int, const char *);
int main(int argc, char **argv)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    HWND window = CreateWindowExA(0, "STATIC", "ARLinux Steamworks check",
        WS_OVERLAPPEDWINDOW, 0, 0, 200, 100, NULL, NULL, NULL, NULL);
    if (!window) { printf("FAIL window error=%lu\n", GetLastError()); return 1; }
#ifdef _WIN64
    const char *dll = "C:\\Program Files (x86)\\Steam\\steamclient64.dll";
#else
    const char *dll = "C:\\Program Files (x86)\\Steam\\steamclient.dll";
#endif
    HMODULE module = LoadLibraryA(dll);
    if (!module) { printf("FAIL client DLL error=%lu\n", GetLastError()); return 2; }
    create_t create = (create_t)GetProcAddress(module, "CreateInterface");
    if (!create) return 3;
    for (int i = 0; i < 32; ++i) {
        void *client = create("SteamClient017", NULL);
        if (!client) return 4;
        void **v = *(void ***)client;
        int pipe = ((pipe_t)v[0])(client);
        int user = ((user_t)v[2])(client, pipe);
        if (!pipe || !user || !((get_t)v[5])(client, user, pipe, "SteamUser019")) return 5;
    }
    puts("PASS window and 32 repeated SteamClient017/SteamUser019 calls");
    if (argc > 1) {
        HMODULE api = LoadLibraryA(argv[1]);
        if (!api) { printf("FAIL game API DLL error=%lu\n", GetLastError()); return 6; }
        BOOL (__cdecl *init)(void) = (void *)GetProcAddress(api, "SteamAPI_Init");
        void (__cdecl *shutdown)(void) = (void *)GetProcAddress(api, "SteamAPI_Shutdown");
        if (!init || !shutdown || !init()) { puts("FAIL SteamAPI_Init"); return 7; }
        puts("PASS original game SteamAPI_Init");
        shutdown();
    }
    DestroyWindow(window);
    return 0;
}

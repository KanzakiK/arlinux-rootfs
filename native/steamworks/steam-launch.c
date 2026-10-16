/* SPDX-License-Identifier: MIT
 * Register a live Wine-side Steam process, then run and wait for its game.
 * Authentication and Steamworks calls remain with the real Linux client.
 */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <wchar.h>
#include <stdlib.h>

static BOOL string_value(HKEY key, const WCHAR *name, const WCHAR *value)
{
    return RegSetValueExW(key, name, 0, REG_SZ, (const BYTE *)value,
                         (wcslen(value)+1)*sizeof(WCHAR)) == ERROR_SUCCESS;
}

static BOOL register_client(void)
{
    WCHAR directory[MAX_PATH], dll[MAX_PATH];
    DWORD pid = GetCurrentProcessId();
    if (!GetModuleFileNameW(NULL, directory, MAX_PATH)) return FALSE;
    WCHAR *end = wcsrchr(directory, L'\\');
    if (!end) return FALSE;
    *end = 0;
    for (int view = 0; view < 2; ++view) {
        HKEY key;
        REGSAM access = KEY_WRITE | (view ? KEY_WOW64_64KEY : KEY_WOW64_32KEY);
        if (RegCreateKeyExW(HKEY_CURRENT_USER, L"Software\\Valve\\Steam", 0,
                           NULL, 0, access, NULL, &key, NULL)) return FALSE;
        BOOL ok = string_value(key, L"SteamPath", directory);
        WCHAR exe[MAX_PATH];
        swprintf(exe, MAX_PATH, L"%ls\\steam.exe", directory);
        ok = ok && string_value(key, L"SteamExe", exe);
        RegCloseKey(key);
        if (!ok || RegCreateKeyExW(HKEY_CURRENT_USER,
            L"Software\\Valve\\Steam\\ActiveProcess", 0, NULL, 0, access,
            NULL, &key, NULL)) return FALSE;
        ok = RegSetValueExW(key, L"PID", 0, REG_DWORD,
                           (const BYTE *)&pid, sizeof(pid)) == ERROR_SUCCESS;
        ok = ok && string_value(key, L"SteamPath", directory);
        swprintf(dll, MAX_PATH, L"%ls\\steamclient.dll", directory);
        ok = ok && string_value(key, L"SteamClientDll", dll);
        swprintf(dll, MAX_PATH, L"%ls\\steamclient64.dll", directory);
        ok = ok && string_value(key, L"SteamClientDll64", dll);
        RegCloseKey(key);
        if (!ok) return FALSE;
    }
    return TRUE;
}

/* Quote each argument according to CommandLineToArgvW/CRT backslash rules. */
static WCHAR *quote(WCHAR *out, const WCHAR *argument)
{
    *out++ = L'"';
    while (*argument) {
        unsigned slashes = 0;
        while (*argument == L'\\') { ++slashes; ++argument; }
        unsigned count = (*argument == L'"' || !*argument) ? slashes*2 : slashes;
        while (count--) *out++ = L'\\';
        if (!*argument) break;
        if (*argument == L'"') *out++ = L'\\';
        *out++ = *argument++;
    }
    *out++ = L'"';
    return out;
}

int wmain(int argc, WCHAR **argv)
{
    if (argc < 2 || !register_client()) return 2;
    size_t length = 1;
    for (int i = 1; i < argc; ++i) length += wcslen(argv[i])*2+4;
    WCHAR *command = calloc(length+3, sizeof(WCHAR));
    if (!command) return 3;
    WCHAR *out = command;
    for (int i = 1; i < argc; ++i) {
        if (i > 1) *out++ = L' ';
        if (i == 1 && argv[i][0] == L'/') {
            /* Android host paths are visible through Wine's Z: drive. */
            WCHAR *path = calloc(wcslen(argv[i])+3, sizeof(WCHAR));
            if (!path) { free(command); return 3; }
            wcscpy(path, L"Z:"); wcscat(path, argv[i]);
            for (WCHAR *p = path; *p; ++p) if (*p == L'/') *p = L'\\';
            out = quote(out, path);
            free(path);
        } else out = quote(out, argv[i]);
    }
    *out = 0;
    WCHAR cwd[32768];
    if (wcslen(argv[1]) >= 32765) { free(command); return 2; }
    if (argv[1][0] == L'/') {
        wcscpy(cwd, L"Z:"); wcscat(cwd, argv[1]);
        for (WCHAR *p = cwd; *p; ++p) if (*p == L'/') *p = L'\\';
    } else wcscpy(cwd, argv[1]);
    WCHAR *separator = wcsrchr(cwd, L'\\');
    if (separator) { *separator = 0; if (!SetCurrentDirectoryW(cwd)) { free(command); return 2; } }
    STARTUPINFOW startup = { .cb = sizeof(startup) };
    PROCESS_INFORMATION child;
    /* Bootstrap launchers can exit before their actual game. Keep the facade
     * (and the Linux Steamworks bridge waiting for it) alive for every child.
     * Suspend creation so even a very short bootstrapper joins the job before
     * it can spawn a process. No kill-on-close limit: normal game exit owns
     * cleanup, and closing our bookkeeping handle must not kill a game. */
    HANDLE job = CreateJobObjectW(NULL, NULL);
    if (!job) { free(command); return GetLastError(); }
    BOOL started = CreateProcessW(NULL, command, NULL, NULL, FALSE, CREATE_SUSPENDED,
                                  NULL, NULL, &startup, &child);
    free(command);
    if (!started) { DWORD error = GetLastError(); CloseHandle(job); return error; }
    if (!AssignProcessToJobObject(job, child.hProcess)) {
        DWORD error = GetLastError();
        TerminateProcess(child.hProcess, error);
        CloseHandle(child.hThread); CloseHandle(child.hProcess); CloseHandle(job);
        return error;
    }
    if (ResumeThread(child.hThread) == (DWORD)-1) {
        DWORD error = GetLastError();
        TerminateProcess(child.hProcess, error);
        CloseHandle(child.hThread); CloseHandle(child.hProcess); CloseHandle(job);
        return error;
    }
    CloseHandle(child.hThread);
    WaitForSingleObject(child.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(child.hProcess, &code);
    CloseHandle(child.hProcess);
    for (;;) {
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting;
        if (!QueryInformationJobObject(job, JobObjectBasicAccountingInformation,
                                       &accounting, sizeof(accounting), NULL)) {
            code = GetLastError();
            break;
        }
        if (!accounting.ActiveProcesses) break;
        Sleep(100);
    }
    CloseHandle(job);
    return code;
}

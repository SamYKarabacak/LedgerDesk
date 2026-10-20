/* LedgerDesk native Windows entry point. SPDX-License-Identifier: MIT */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <strsafe.h>

static int fail(const wchar_t *message) {
    MessageBoxW(NULL, message, L"LedgerDesk", MB_OK | MB_ICONERROR);
    return 1;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    (void)instance; (void)previous; (void)show;
    wchar_t folder[32768], runtime[32768], script[32768];
    DWORD length = GetModuleFileNameW(NULL, folder, 32768);
    if (!length || length >= 32768)
        return fail(L"LedgerDesk could not locate its application folder.");
    while (length && folder[length - 1] != L'\\') --length;
    if (!length) return fail(L"LedgerDesk could not locate its application folder.");
    folder[length - 1] = L'\0';
    if (FAILED(StringCchPrintfW(runtime, 32768, L"%ls\\runtime\\pythonw.exe", folder)) ||
        FAILED(StringCchPrintfW(script, 32768, L"%ls\\app\\start.pyw", folder)))
        return fail(L"The application folder path is too long.");
    if (GetFileAttributesW(runtime) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES)
        return fail(L"Extract the whole ZIP first, then open LedgerDesk.exe.\n\n"
                    L"Keep the app and runtime folders beside LedgerDesk.exe.");
    wchar_t *command = HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, 32768 * sizeof(wchar_t));
    if (!command) return fail(L"There is not enough memory to start LedgerDesk.");
    if (FAILED(StringCchPrintfW(command, 32768, L"\"%ls\" -I \"%ls\" %ls", runtime, script,
                               arguments ? arguments : L""))) {
        HeapFree(GetProcessHeap(), 0, command);
        return fail(L"The launch arguments are too long.");
    }
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    BOOL started = CreateProcessW(runtime, command, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                                 NULL, folder, &startup, &process);
    HeapFree(GetProcessHeap(), 0, command);
    if (!started)
        return fail(L"LedgerDesk could not start its bundled runtime.\n\n"
                    L"Extract the complete Windows x64 package to a writable folder and try again.");
    CloseHandle(process.hThread);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hProcess);
    return (int)code;
}

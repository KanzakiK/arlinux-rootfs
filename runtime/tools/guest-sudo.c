#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* The runtime honors this ELF's virtual set-id mode, never the Android UID. */
int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: sudo COMMAND [ARG...]\n");
        return 2;
    }
    if (setgid(0) != 0 || setuid(0) != 0) {
        perror("sudo: virtual root identity");
        return 1;
    }
    /* Login shells omit sbin for ordinary users. Like sudo's secure_path,
     * resolve privileged commands against the guest's system directories. */
    if (setenv("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", 1) != 0) {
        perror("sudo: system PATH");
        return 1;
    }
    execvp(argv[1], argv + 1);
    fprintf(stderr, "sudo: %s: %s\n", argv[1], strerror(errno));
    return 127;
}

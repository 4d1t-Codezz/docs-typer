/* The Mac app's main executable. It runs Python inside this process instead of starting a separate
 * python3 binary, so macOS sees "Docs Typer" as the app asking for Accessibility and Input
 * Monitoring access. A script launcher would pass those requests to python3, and switching Docs
 * Typer on in System Settings would then do nothing.
 *
 * It reads which Python to use from Contents/Resources/python.txt, which build-mac-app.sh writes:
 * the Python shared library on the first line and that Python's sys.base_prefix on the second.
 * Because nothing is baked in, scripts/mac-launcher (a universal build of this file) works on
 * Macs without a C compiler. To rebuild it after changing this file:
 *   cc -O2 -Wall -arch arm64 -arch x86_64 -mmacosx-version-min=11.0 \
 *      -o scripts/mac-launcher scripts/mac-launcher.c */

#include <dlfcn.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    (void)argc;
    char exe[PATH_MAX], real[PATH_MAX];
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0 || !realpath(exe, real)) {
        fprintf(stderr, "Docs Typer: can't find its own location\n");
        return 1;
    }
    /* real is .../Docs Typer.app/Contents/MacOS/DocsTyper; the code is in Contents/Resources/app. */
    char *slash = strrchr(real, '/');
    if (!slash) return 1;
    *slash = '\0';
    char app_dir[PATH_MAX], conf_path[PATH_MAX];
    snprintf(app_dir, sizeof app_dir, "%s/../Resources/app", real);
    snprintf(conf_path, sizeof conf_path, "%s/../Resources/python.txt", real);

    char libpython[PATH_MAX], pythonhome[PATH_MAX];
    FILE *conf = fopen(conf_path, "r");
    if (!conf || !fgets(libpython, sizeof libpython, conf) || !fgets(pythonhome, sizeof pythonhome, conf)) {
        fprintf(stderr, "Docs Typer: can't read %s. Reinstall it with install.sh.\n", conf_path);
        return 1;
    }
    fclose(conf);
    libpython[strcspn(libpython, "\n")] = '\0';
    pythonhome[strcspn(pythonhome, "\n")] = '\0';

    if (chdir(app_dir) != 0) {
        fprintf(stderr, "Docs Typer: can't open %s\n", app_dir);
        return 1;
    }

    setenv("PYTHONHOME", pythonhome, 1);
    void *lib = dlopen(libpython, RTLD_NOW | RTLD_GLOBAL);
    if (!lib) {
        fprintf(stderr, "Docs Typer: can't load Python (%s). Reinstall it with install.sh.\n",
                dlerror());
        return 1;
    }
    int (*py_main)(int, char **) = (int (*)(int, char **))dlsym(lib, "Py_BytesMain");
    if (!py_main) {
        fprintf(stderr, "Docs Typer: %s\n", dlerror());
        return 1;
    }
    char *args[] = {argv[0], "-m", "docstyper", NULL};
    return py_main(3, args);
}

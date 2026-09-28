/* The Mac app's main executable. It runs Python inside this process instead of starting a separate
 * python3 binary, so macOS sees "Docs Typer" as the app asking for Accessibility and Input
 * Monitoring access. A script launcher would pass those requests to python3, and switching Docs
 * Typer on in System Settings would then do nothing.
 *
 * build-mac-app.sh compiles this with LIBPYTHON (the Python shared library) and PYTHONHOME_DIR
 * (that Python's sys.base_prefix) baked in. */

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
    char app_dir[PATH_MAX];
    snprintf(app_dir, sizeof app_dir, "%s/../Resources/app", real);
    if (chdir(app_dir) != 0) {
        fprintf(stderr, "Docs Typer: can't open %s\n", app_dir);
        return 1;
    }

    setenv("PYTHONHOME", PYTHONHOME_DIR, 1);
    void *lib = dlopen(LIBPYTHON, RTLD_NOW | RTLD_GLOBAL);
    if (!lib) {
        fprintf(stderr, "Docs Typer: can't load Python (%s). Reinstall it with Install on Mac.command.\n",
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

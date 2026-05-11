/*
 * obs-open-spark — plugin entry point.
 *
 * Responsibilities of this thin native layer:
 *   1. Identify itself to OBS (OBS_DECLARE_MODULE).
 *   2. On load, register a Qt dock that embeds the Open Spark web UI.
 *   3. Stay out of the way — all heavy lifting (LLM calls, overlay
 *      generation, scene templates) lives in the external Python
 *      backend reachable on http://127.0.0.1:8765.
 *
 * The dock registration itself is implemented in C++ (open-spark-dock.cpp)
 * because Qt is C++. We expose a tiny C entry point so this file stays
 * pure C and matches the rest of the OBS plugin ABI.
 */

#include <obs-module.h>

#ifndef PLUGIN_NAME
#  define PLUGIN_NAME "obs-open-spark"
#endif
#ifndef PLUGIN_VERSION
#  define PLUGIN_VERSION "0.1.0"
#endif

OBS_DECLARE_MODULE()
OBS_MODULE_USE_DEFAULT_LOCALE(PLUGIN_NAME, "en-US")

MODULE_EXPORT const char *obs_module_name(void)
{
    return "Open Spark";
}

MODULE_EXPORT const char *obs_module_description(void)
{
    return "Embeds the Open Spark web UI as a native OBS dock and forwards "
           "user actions to the external backend on 127.0.0.1:8765.";
}

/* Implemented in open-spark-dock.cpp + open-spark-actions.cpp + open-spark-websocket-bootstrap.cpp */
extern bool openspark_dock_register(void);
extern void openspark_dock_unregister(void);
extern void openspark_actions_install(void);
extern void openspark_actions_uninstall(void);
extern void openspark_websocket_bootstrap(void);

bool obs_module_load(void)
{
    blog(LOG_INFO, "[%s] loading v%s", PLUGIN_NAME, PLUGIN_VERSION);
    // Auto-configure the obs-websocket plugin BEFORE its module reads
    // its config. We sort alphabetically before "obs-websocket" so OBS
    // loads us first, giving us a window to write the config file the
    // websocket plugin will read on its own load.
    openspark_websocket_bootstrap();
    // Both dock + actions install run on FINISHED_LOADING via the
    // event callback registered in openspark_dock_register(). Calling them
    // any earlier crashes OBS because the Qt application isn't ready.
    if (!openspark_dock_register()) {
        blog(LOG_WARNING, "[%s] dock registration failed; plugin will be inert",
             PLUGIN_NAME);
    }
    return true;
}

void obs_module_unload(void)
{
    blog(LOG_INFO, "[%s] unloading", PLUGIN_NAME);
    openspark_actions_uninstall();
    openspark_dock_unregister();
}

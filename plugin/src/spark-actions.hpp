// Menu items + hotkeys exposed by obs-spark-libre.
//
// All entry points are registered from C++ via Qt for ergonomics, then
// surfaced through tiny C wrappers so plugin-main.c can call them
// without dragging C++ headers into a .c file.

#pragma once

#ifdef __cplusplus
extern "C" {
#endif

/// Adds menu items under "Tools → Spark Libre" and registers the
/// frontend hotkeys (toggle dock, generate from prompt, open UI).
/// Idempotent — safe to call once on FINISHED_LOADING.
void spark_actions_install(void);

/// Removes registered hotkeys at module unload.
void spark_actions_uninstall(void);

#ifdef __cplusplus
}
#endif

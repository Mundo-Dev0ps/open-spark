cmake_minimum_required(VERSION 3.22)
project(obs-spark-libre VERSION 0.1.0 LANGUAGES C CXX)

#
# obs-spark-libre — thin native OBS plugin that hosts the Spark Libre web
# UI as a real OBS dock and talks to the external Python backend over
# loopback HTTP.
#
# Cross-platform: Linux (GCC/Clang + Qt6), Windows (MSVC + Qt6), macOS
# (Clang + Qt6). The CI matrix in .github/workflows/plugin-build.yml
# drives the per-platform builds; locally we build inside a dedicated
# Docker stage so it never touches the host system.
#

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC ON)
set(CMAKE_AUTORCC ON)

# --- Dependencies ---------------------------------------------------------

find_package(libobs REQUIRED)
find_package(obs-frontend-api REQUIRED)
# Network for the HTTP client that talks to the Python backend; Gui +
# Widgets for dialogs + dock; Core for everything else.
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Network)

# QtWebEngine is optional. Enabling it embeds a real browser view in
# the dock, but it crashes OBS unless `Qt::AA_ShareOpenGLContexts` is
# set BEFORE QGuiApplication construction — and as a plugin we load
# too late for that. Until we have a workaround in place, the default
# build is the fallback path: a status label + an "Open in browser"
# button. Override with `-DSPARK_WITH_WEBENGINE=ON` once the OpenGL
# context issue is resolved.
option(SPARK_WITH_WEBENGINE "Embed Qt WebEngine inside the dock (unstable)" OFF)

if(SPARK_WITH_WEBENGINE)
    find_package(Qt6 REQUIRED COMPONENTS WebEngineWidgets)
    set(SPARK_HAS_WEBENGINE ON)
    message(STATUS "Qt6 WebEngineWidgets enabled (experimental, may crash)")
else()
    set(SPARK_HAS_WEBENGINE OFF)
    message(STATUS "Qt6 WebEngineWidgets disabled — using button fallback")
endif()

# --- Plugin target --------------------------------------------------------

set(PLUGIN_NAME obs-spark-libre)

add_library(${PLUGIN_NAME} MODULE
    src/plugin-main.c
    src/spark-dock.cpp
    src/spark-dock.hpp
    src/spark-actions.cpp
    src/spark-actions.hpp
    src/spark-http.cpp
    src/spark-http.hpp
    src/spark-websocket-bootstrap.cpp
)

target_compile_definitions(${PLUGIN_NAME} PRIVATE
    PLUGIN_NAME="${PLUGIN_NAME}"
    PLUGIN_VERSION="${PROJECT_VERSION}"
    SPARK_DEFAULT_URL="http://127.0.0.1:8765/ui/"
)

if(SPARK_HAS_WEBENGINE)
    target_compile_definitions(${PLUGIN_NAME} PRIVATE SPARK_HAS_WEBENGINE=1)
    target_link_libraries(${PLUGIN_NAME} PRIVATE Qt6::WebEngineWidgets)
endif()

target_link_libraries(${PLUGIN_NAME} PRIVATE
    OBS::libobs
    OBS::obs-frontend-api
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    Qt6::Network
)

# Plugins must not have a "lib" prefix on the resulting binary. OBS scans
# its plugins directory for ${name}.so / ${name}.dll / ${name}.so on macOS.
set_target_properties(${PLUGIN_NAME} PROPERTIES
    PREFIX ""
    OUTPUT_NAME "${PLUGIN_NAME}"
)

# --- Install --------------------------------------------------------------
#
# Layout matches what OBS expects under its module path:
#   linux:   <prefix>/lib/obs-plugins/${PLUGIN_NAME}.so
#            <prefix>/share/obs/obs-plugins/${PLUGIN_NAME}/locale/*.ini
#   windows: <prefix>/obs-plugins/64bit/${PLUGIN_NAME}.dll
#   macos:   <prefix>/${PLUGIN_NAME}.plugin/Contents/MacOS/${PLUGIN_NAME}
#
# For the containerized OBS we build with PORTABLE_LAYOUT=ON which writes
# straight to ./build/portable/plugins/64bit/, ready to be copied into
# .portable-obs/plugins/64bit/.

option(PORTABLE_LAYOUT "Output plugin in OBS portable plugins/64bit layout" OFF)

if(PORTABLE_LAYOUT)
    set(PORTABLE_OUT "${CMAKE_BINARY_DIR}/portable/plugins/64bit")
    set_target_properties(${PLUGIN_NAME} PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${PORTABLE_OUT}"
        RUNTIME_OUTPUT_DIRECTORY "${PORTABLE_OUT}"
    )
elseif(WIN32)
    install(TARGETS ${PLUGIN_NAME}
        RUNTIME DESTINATION obs-plugins/64bit
        LIBRARY DESTINATION obs-plugins/64bit
    )
elseif(APPLE)
    set_target_properties(${PLUGIN_NAME} PROPERTIES
        BUNDLE TRUE
        BUNDLE_EXTENSION "plugin"
        OUTPUT_NAME "${PLUGIN_NAME}"
    )
    install(TARGETS ${PLUGIN_NAME}
        BUNDLE DESTINATION "."
    )
else()
    include(GNUInstallDirs)
    install(TARGETS ${PLUGIN_NAME}
        LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}/obs-plugins"
    )
    install(DIRECTORY data/locale
        DESTINATION "${CMAKE_INSTALL_DATADIR}/obs/obs-plugins/${PLUGIN_NAME}"
    )
endif()

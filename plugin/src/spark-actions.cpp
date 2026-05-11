#include "spark-actions.hpp"
#include "spark-http.hpp"
#include "spark-dock.hpp"

#include <QAction>
#include <QApplication>
#include <QDesktopServices>
#include <QDockWidget>
#include <QInputDialog>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMainWindow>
#include <QMenu>
#include <QMenuBar>
#include <QMessageBox>
#include <QString>
#include <QUrl>
#include <QWidget>

#include <obs-frontend-api.h>
#include <obs-module.h>

namespace {

/// Lazily-allocated HTTP client. Lifetime is tied to QApplication via
/// the qApp parent so it cleans up at program exit.
spark::SparkHttp *http_client()
{
    static spark::SparkHttp *c = nullptr;
    if (!c) {
        c = new spark::SparkHttp(qApp);
    }
    return c;
}

/// Find a sensible parent widget for our dialogs — OBS's main window if
/// we can locate it, otherwise the active modal widget, otherwise null.
QWidget *parent_widget()
{
    if (auto *w = static_cast<QWidget *>(obs_frontend_get_main_window())) {
        return w;
    }
    return QApplication::activeWindow();
}

void open_ui_in_browser()
{
    QDesktopServices::openUrl(QUrl(SparkLibreDock::defaultUrl()));
}

void show_status_toast(const QString &title, const QString &body, bool ok)
{
    auto *parent = parent_widget();
    if (ok) {
        QMessageBox::information(parent, title, body);
    } else {
        QMessageBox::warning(parent, title, body);
    }
}

void prompt_and_post(const QString &endpoint,
                     const QString &dialogTitle,
                     const QString &dialogLabel,
                     const QString &successKey)
{
    bool ok = false;
    const QString prompt = QInputDialog::getMultiLineText(
        parent_widget(), dialogTitle, dialogLabel, QString(), &ok);
    if (!ok || prompt.trimmed().isEmpty()) {
        return;
    }

    QJsonObject obj;
    obj[QStringLiteral("prompt")] = prompt;
    const QByteArray body = QJsonDocument(obj).toJson(QJsonDocument::Compact);

    blog(LOG_INFO, "[obs-spark-libre] POST %s prompt_len=%lld",
         endpoint.toUtf8().constData(),
         static_cast<long long>(prompt.size()));

    http_client()->postJson(
        endpoint, body, [endpoint, successKey](const spark::HttpResult &res) {
            if (!res.ok) {
                blog(LOG_WARNING,
                     "[obs-spark-libre] %s failed status=%d err=%s body=%s",
                     endpoint.toUtf8().constData(), res.status,
                     res.error.toUtf8().constData(),
                     res.body.constData());
                show_status_toast(
                    QStringLiteral("Spark Libre"),
                    QStringLiteral("Backend call failed (%1): %2")
                        .arg(res.status)
                        .arg(QString::fromUtf8(res.body)),
                    false);
                return;
            }
            const auto doc = QJsonDocument::fromJson(res.body);
            const auto obj = doc.object();
            const QString id = obj.value(successKey).toString();
            const QString scene = obj.value(QStringLiteral("scene")).toString();
            QString summary;
            if (!scene.isEmpty()) {
                summary = QStringLiteral("Scene: %1").arg(scene);
            } else if (!id.isEmpty()) {
                summary = QStringLiteral("Overlay id: %1").arg(id);
            } else {
                summary = QStringLiteral("Done.");
            }
            show_status_toast(QStringLiteral("Spark Libre"), summary, true);
        });
}

// ---- Menu / hotkey wiring ------------------------------------------------

QAction *g_view_action_toggle_dock = nullptr;
QMenu *g_view_submenu = nullptr;

obs_hotkey_id g_hk_open_ui = OBS_INVALID_HOTKEY_ID;
obs_hotkey_id g_hk_generate_overlay = OBS_INVALID_HOTKEY_ID;
obs_hotkey_id g_hk_generate_scene = OBS_INVALID_HOTKEY_ID;

void hotkey_open_ui_cb(void *, obs_hotkey_id, obs_hotkey_t *, bool pressed)
{
    if (pressed) {
        QMetaObject::invokeMethod(qApp, [] { open_ui_in_browser(); });
    }
}

void hotkey_generate_overlay_cb(void *, obs_hotkey_id, obs_hotkey_t *, bool pressed)
{
    if (pressed) {
        QMetaObject::invokeMethod(qApp, [] {
            prompt_and_post(
                QStringLiteral("/api/generate"),
                QStringLiteral("Spark Libre — Generate overlay"),
                QStringLiteral("Describe the overlay:"),
                QStringLiteral("overlay_id"));
        });
    }
}

void hotkey_generate_scene_cb(void *, obs_hotkey_id, obs_hotkey_t *, bool pressed)
{
    if (pressed) {
        QMetaObject::invokeMethod(qApp, [] {
            prompt_and_post(
                QStringLiteral("/api/scenes/templates"),
                QStringLiteral("Spark Libre — Generate scene"),
                QStringLiteral("Describe the multi-source scene:"),
                QStringLiteral("scene"));
        });
    }
}

/// Walk OBS's main window menubar and return the QMenu whose object
/// name or title looks like "View". Returns nullptr if not found —
/// every recent OBS version has it, so failure is rare and non-fatal.
QMenu *find_view_menu()
{
    auto *main = static_cast<QMainWindow *>(obs_frontend_get_main_window());
    if (!main || !main->menuBar()) {
        return nullptr;
    }
    for (auto *menu : main->menuBar()->findChildren<QMenu *>(
             QString(), Qt::FindDirectChildrenOnly)) {
        if (!menu) continue;
        const QString obj = menu->objectName();
        QString title = menu->title();
        title.remove(QChar('&'));  // strip Qt accelerator markers
        if (obj.compare("menuView", Qt::CaseInsensitive) == 0
            || title.compare("View", Qt::CaseInsensitive) == 0) {
            return menu;
        }
    }
    return nullptr;
}

/// Find the QDockWidget OBS wrapped around our SparkLibreDock content.
/// obs_frontend_add_dock_by_id uses the registration id as the
/// QDockWidget object name, so we just look that up.
QDockWidget *find_spark_dock_widget()
{
    auto *main = static_cast<QWidget *>(obs_frontend_get_main_window());
    if (!main) {
        return nullptr;
    }
    auto *dw = main->findChild<QDockWidget *>("spark-libre-dock");
    return dw;
}

void toggle_spark_dock()
{
    if (auto *dw = find_spark_dock_widget()) {
        const bool visible = dw->isVisible();
        dw->setVisible(!visible);
        if (!visible) {
            dw->raise();
        }
    } else {
        blog(LOG_WARNING,
             "[obs-spark-libre] toggle: dock widget not found");
    }
}

void install_view_menu_item()
{
    auto *view = find_view_menu();
    if (!view) {
        blog(LOG_WARNING,
             "[obs-spark-libre] could not locate View menu — skipping View entry");
        return;
    }

    // Add a Spark Libre submenu so we can grow it with extra view-only
    // actions later (open inspector, force-refresh, etc.) without
    // cluttering View's top level.
    g_view_submenu = view->addMenu(QStringLiteral("Spark Libre"));

    g_view_action_toggle_dock = g_view_submenu->addAction(
        QStringLiteral("Toggle dock"));
    QObject::connect(g_view_action_toggle_dock, &QAction::triggered, qApp,
                     [] { toggle_spark_dock(); });

    g_view_submenu->addAction(QStringLiteral("Open UI in browser"),
                              [] { open_ui_in_browser(); });

    blog(LOG_INFO,
         "[obs-spark-libre] View → Spark Libre submenu installed");
}

// (Tools-menu items intentionally removed: the dock UI exposes the same
// actions inline, so the Tools entries were redundant noise.)

void install_hotkeys()
{
    g_hk_open_ui = obs_hotkey_register_frontend(
        "spark_libre.open_ui",
        "Spark Libre: open UI",
        hotkey_open_ui_cb,
        nullptr);

    g_hk_generate_overlay = obs_hotkey_register_frontend(
        "spark_libre.generate_overlay",
        "Spark Libre: generate overlay (prompt)",
        hotkey_generate_overlay_cb,
        nullptr);

    g_hk_generate_scene = obs_hotkey_register_frontend(
        "spark_libre.generate_scene",
        "Spark Libre: generate scene (prompt)",
        hotkey_generate_scene_cb,
        nullptr);
}

}  // namespace

extern "C" void spark_actions_install(void)
{
    install_view_menu_item();
    install_hotkeys();
    blog(LOG_INFO,
         "[obs-spark-libre] View menu + hotkeys installed (backend=%s)",
         spark::SparkHttp::baseUrl().toUtf8().constData());
}

extern "C" void spark_actions_uninstall(void)
{
    if (g_hk_open_ui != OBS_INVALID_HOTKEY_ID) {
        obs_hotkey_unregister(g_hk_open_ui);
        g_hk_open_ui = OBS_INVALID_HOTKEY_ID;
    }
    if (g_hk_generate_overlay != OBS_INVALID_HOTKEY_ID) {
        obs_hotkey_unregister(g_hk_generate_overlay);
        g_hk_generate_overlay = OBS_INVALID_HOTKEY_ID;
    }
    if (g_hk_generate_scene != OBS_INVALID_HOTKEY_ID) {
        obs_hotkey_unregister(g_hk_generate_scene);
        g_hk_generate_scene = OBS_INVALID_HOTKEY_ID;
    }
    if (g_view_submenu) {
        g_view_submenu->deleteLater();
        g_view_submenu = nullptr;
    }
    g_view_action_toggle_dock = nullptr;
}

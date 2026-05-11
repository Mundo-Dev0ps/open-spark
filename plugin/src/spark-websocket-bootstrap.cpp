// Auto-configure obs-websocket on plugin load.
//
// We write the obs-websocket config.json BEFORE its module loads so the
// user never has to open Tools → WebSocket Server Settings manually.
// The plugin module name "obs-spark-libre" sorts alphabetically before
// "obs-websocket", so obs-studio loads us first; by the time the
// websocket plugin reads its config, it's already what we want.
//
// Password resolution order:
//   1. SPARK_OBS_PASSWORD env var (set by docker-compose)
//   2. existing password if config.json already exists
//   3. literal "test" (matches the bundled .env.compose.example)
//
// Idempotent: if the config already has server_enabled=true and a
// matching password, we don't touch it.

#include <obs-module.h>

#include <QByteArray>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QString>
#include <QStringList>

namespace {

QString websocket_config_path()
{
    // OBS stores plugin config under ${XDG_CONFIG_HOME}/obs-studio/plugin_config
    // (portable mode just remaps that prefix to <portable>/config).
    QString base = QString::fromUtf8(qgetenv("XDG_CONFIG_HOME"));
    if (base.isEmpty()) {
        base = QDir::homePath() + QStringLiteral("/.config");
    }
    return base + QStringLiteral(
        "/obs-studio/plugin_config/obs-websocket/config.json");
}

QString resolve_password(const QJsonObject &existing)
{
    const QByteArray env = qgetenv("SPARK_OBS_PASSWORD");
    if (!env.isEmpty()) {
        return QString::fromUtf8(env);
    }
    const QString cur = existing.value(QStringLiteral("server_password"))
                            .toString();
    if (!cur.isEmpty()) {
        return cur;
    }
    return QStringLiteral("test");
}

}  // namespace

extern "C" void spark_websocket_bootstrap(void)
{
    const QString path = websocket_config_path();
    QFileInfo fi(path);
    QDir().mkpath(fi.absolutePath());

    QJsonObject obj;
    if (fi.exists()) {
        QFile f(path);
        if (f.open(QIODevice::ReadOnly)) {
            const auto doc = QJsonDocument::fromJson(f.readAll());
            if (doc.isObject()) {
                obj = doc.object();
            }
        }
    }

    const QString password = resolve_password(obj);
    const bool already_ok =
        obj.value(QStringLiteral("server_enabled")).toBool(false)
        && obj.value(QStringLiteral("auth_required")).toBool(false)
        && obj.value(QStringLiteral("server_password")).toString() == password
        && obj.value(QStringLiteral("server_port")).toInt(0) == 4455;
    if (already_ok) {
        blog(LOG_INFO,
             "[obs-spark-libre] obs-websocket already configured (port 4455)");
        return;
    }

    obj.insert(QStringLiteral("server_enabled"), true);
    obj.insert(QStringLiteral("server_port"), 4455);
    obj.insert(QStringLiteral("auth_required"), true);
    obj.insert(QStringLiteral("server_password"), password);
    obj.insert(QStringLiteral("alerts_enabled"), false);
    obj.insert(QStringLiteral("first_load"), false);

    QFile out(path);
    if (!out.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        blog(LOG_WARNING,
             "[obs-spark-libre] could not write %s",
             path.toUtf8().constData());
        return;
    }
    out.write(QJsonDocument(obj).toJson(QJsonDocument::Indented));
    out.close();
    blog(LOG_INFO,
         "[obs-spark-libre] obs-websocket auto-configured at %s "
         "(port=4455, password from SPARK_OBS_PASSWORD env)",
         path.toUtf8().constData());
}

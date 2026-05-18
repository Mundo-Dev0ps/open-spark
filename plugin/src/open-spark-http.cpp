#include "open-spark-http.hpp"

#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUrl>

#include <memory>

namespace openspark {

OpenSparkHttp::OpenSparkHttp(QObject *parent)
    : QObject(parent), nam_(new QNetworkAccessManager(this))
{
}

OpenSparkHttp::~OpenSparkHttp() = default;

QString OpenSparkHttp::baseUrl()
{
    const QByteArray env = qgetenv("OPENSPARK_BACKEND_URL");
    if (!env.isEmpty()) {
        return QString::fromUtf8(env);
    }
    return QStringLiteral("http://127.0.0.1:8765");
}

static HttpResult buildResult(QNetworkReply *reply)
{
    HttpResult r;
    r.status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    r.body = reply->readAll();
    if (reply->error() != QNetworkReply::NoError && r.status == 0) {
        r.ok = false;
        r.error = reply->errorString();
    } else {
        r.ok = (r.status >= 200 && r.status < 300);
        if (!r.ok) {
            r.error = reply->errorString();
        }
    }
    return r;
}

void OpenSparkHttp::postJson(
    const QString &path, const QByteArray &body,
    std::function<void(const HttpResult &)> cb)
{
    QNetworkRequest req(QUrl(baseUrl() + path));
    req.setHeader(QNetworkRequest::ContentTypeHeader,
                  QStringLiteral("application/json"));
    QNetworkReply *reply = nam_->post(req, body);
    QObject::connect(reply, &QNetworkReply::finished, this, [reply, cb]() {
        cb(buildResult(reply));
        reply->deleteLater();
    });
}

void OpenSparkHttp::getJson(
    const QString &path, std::function<void(const HttpResult &)> cb)
{
    QNetworkRequest req(QUrl(baseUrl() + path));
    req.setHeader(QNetworkRequest::ContentTypeHeader,
                  QStringLiteral("application/json"));
    QNetworkReply *reply = nam_->get(req);
    QObject::connect(reply, &QNetworkReply::finished, this, [reply, cb]() {
        cb(buildResult(reply));
        reply->deleteLater();
    });
}

void OpenSparkHttp::putJson(
    const QString &path, const QByteArray &body,
    std::function<void(const HttpResult &)> cb)
{
    QNetworkRequest req(QUrl(baseUrl() + path));
    req.setHeader(QNetworkRequest::ContentTypeHeader,
                  QStringLiteral("application/json"));
    QNetworkReply *reply = nam_->put(req, body);
    QObject::connect(reply, &QNetworkReply::finished, this, [reply, cb]() {
        cb(buildResult(reply));
        reply->deleteLater();
    });
}

void OpenSparkHttp::del(
    const QString &path, std::function<void(const HttpResult &)> cb)
{
    QNetworkRequest req(QUrl(baseUrl() + path));
    QNetworkReply *reply = nam_->deleteResource(req);
    QObject::connect(reply, &QNetworkReply::finished, this, [reply, cb]() {
        cb(buildResult(reply));
        reply->deleteLater();
    });
}

void OpenSparkHttp::postSse(
    const QString &path, const QByteArray &body,
    std::function<void(const QString &, const QByteArray &)> onEvent,
    std::function<void(const QString &)> onDone)
{
    QNetworkRequest req(QUrl(baseUrl() + path));
    req.setHeader(QNetworkRequest::ContentTypeHeader,
                  QStringLiteral("application/json"));
    req.setRawHeader("Accept", "text/event-stream");
    QNetworkReply *reply = nam_->post(req, body);

    // Incremental SSE parser. We accumulate bytes, split on the blank
    // line that terminates each frame, and pull out the `event:` and
    // `data:` fields.
    auto buf = std::make_shared<QByteArray>();

    QObject::connect(
        reply, &QNetworkReply::readyRead, this, [reply, buf, onEvent]() {
            buf->append(reply->readAll());
            int sep;
            while ((sep = buf->indexOf("\n\n")) != -1) {
                const QByteArray frame = buf->left(sep);
                buf->remove(0, sep + 2);
                QString evName = QStringLiteral("message");
                QByteArray data;
                for (const QByteArray &lineRaw : frame.split('\n')) {
                    const QByteArray line = lineRaw.trimmed();
                    if (line.startsWith("event:")) {
                        evName = QString::fromUtf8(line.mid(6).trimmed());
                    } else if (line.startsWith("data:")) {
                        data = line.mid(5).trimmed();
                    }
                }
                if (!data.isEmpty()) {
                    onEvent(evName, data);
                }
            }
        });

    QObject::connect(
        reply, &QNetworkReply::finished, this, [reply, onDone]() {
            const QString err =
                reply->error() == QNetworkReply::NoError
                    ? QString()
                    : reply->errorString();
            onDone(err);
            reply->deleteLater();
        });
}

}  // namespace openspark

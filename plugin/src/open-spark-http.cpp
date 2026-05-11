#include "open-spark-http.hpp"

#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUrl>

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

}  // namespace openspark

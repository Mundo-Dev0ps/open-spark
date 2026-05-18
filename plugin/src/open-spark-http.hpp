// Tiny HTTP client used by the plugin to talk to the local Python
// backend (FastAPI on 127.0.0.1:8765). We use Qt's QNetworkAccessManager
// instead of pulling in libcurl so the plugin has no extra deps.

#pragma once

#include <QByteArray>
#include <QObject>
#include <QString>
#include <functional>

class QNetworkAccessManager;
class QNetworkReply;

namespace openspark {

/// Result of a backend call. Stays small — UI code just needs to know
/// whether it succeeded and what the response body said.
struct HttpResult {
    bool ok = false;
    int status = 0;
    QByteArray body;
    QString error;
};

class OpenSparkHttp : public QObject {
    Q_OBJECT
public:
    explicit OpenSparkHttp(QObject *parent = nullptr);
    ~OpenSparkHttp() override;

    /// Base URL of the backend. Defaults to ``http://127.0.0.1:8765``;
    /// override with the ``OPENSPARK_BACKEND_URL`` environment variable.
    static QString baseUrl();

    /// POST a JSON body to ``baseUrl + path``. Calls ``cb`` on the GUI
    /// thread when the reply lands. Safe to call multiple times in a
    /// row — replies are tracked individually.
    void postJson(const QString &path,
                  const QByteArray &body,
                  std::function<void(const HttpResult &)> cb);

    /// GET a JSON resource at ``baseUrl + path``. Same callback model.
    void getJson(const QString &path,
                 std::function<void(const HttpResult &)> cb);

    /// PUT a JSON body. Mirrors postJson semantics.
    void putJson(const QString &path,
                 const QByteArray &body,
                 std::function<void(const HttpResult &)> cb);

    /// DELETE on ``baseUrl + path``. Same callback model as the others.
    void del(const QString &path,
             std::function<void(const HttpResult &)> cb);

    /// POST a JSON body and consume a Server-Sent-Events response.
    /// ``onEvent(eventName, dataJson)`` fires per SSE frame as it
    /// arrives; ``onDone(error)`` fires once the stream closes (empty
    /// error string = clean finish).
    void postSse(const QString &path,
                 const QByteArray &body,
                 std::function<void(const QString &, const QByteArray &)> onEvent,
                 std::function<void(const QString &)> onDone);

private:
    QNetworkAccessManager *nam_;
};

}  // namespace openspark

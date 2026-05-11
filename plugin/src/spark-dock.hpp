// Spark Libre dock — native Qt panel hosted as an OBS dock.
//
// The dock renders the same actions as the web UI (generate overlay,
// generate scene, list/inject/regenerate/delete overlays) but using
// pure Qt widgets, so it works inside any OBS build regardless of
// browser-panel availability and feels like a real plugin pane.
//
// All backend traffic goes through ``spark::SparkHttp`` over loopback.

#pragma once

#ifdef __cplusplus

#include <QFrame>
#include <QString>

class QComboBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QPushButton;
class QSpinBox;
class QCheckBox;
class QPlainTextEdit;
class QTimer;
class QTabWidget;

namespace spark {
class SparkHttp;
struct HttpResult;
}  // namespace spark

class SparkLibreDock : public QFrame {
    Q_OBJECT
public:
    explicit SparkLibreDock(QWidget *parent = nullptr);
    ~SparkLibreDock() override;

    /// URL the dock loads on construction (also used by the actions
    /// menu's "Open in browser" entry, hence ``static``).
    static QString defaultUrl();

private slots:
    void refreshStatus();
    void refreshStyles();
    void refreshOverlays();
    void refreshSettings();
    void saveSettings();
    void doGenerate();
    void doGenerateScene();
    void doInjectLast();
    void onOpenInBrowser();

private:
    QWidget *buildInputTab();
    QWidget *buildSettingsTab();
    void wire();
    void setStatusLine(const QString &text, bool ok);
    void appendLog(const QString &text);

    /// Reference-counted "thinking" indicator — increments on every
    /// in-flight HTTP call, decrements when the callback fires; the
    /// animated label only hides when the counter is 0.
    void beginThinking(const QString &label);
    void endThinking();

    QString url_;
    QString lastOverlayId_;
    spark::SparkHttp *http_ = nullptr;

    // Top status row.
    QLabel *statusLabel_ = nullptr;

    // Tabs.
    QTabWidget *tabs_ = nullptr;

    // Settings tab widgets.
    QLineEdit *settingsModelEdit_ = nullptr;
    QLineEdit *settingsLlmBaseEdit_ = nullptr;
    QLineEdit *settingsObsHostEdit_ = nullptr;
    QSpinBox *settingsObsPortSpin_ = nullptr;
    QLineEdit *settingsSceneNameEdit_ = nullptr;
    QPushButton *settingsSaveBtn_ = nullptr;
    QPushButton *settingsReloadBtn_ = nullptr;
    QLabel *settingsKeysLabel_ = nullptr;
    QComboBox *settingsKeyProviderCombo_ = nullptr;
    QLineEdit *settingsKeyValueEdit_ = nullptr;
    QPushButton *settingsKeySaveBtn_ = nullptr;

    // "Generate overlay" group.
    QPlainTextEdit *promptEdit_ = nullptr;
    QComboBox *styleCombo_ = nullptr;
    QSpinBox *widthSpin_ = nullptr;
    QSpinBox *heightSpin_ = nullptr;
    QPushButton *generateBtn_ = nullptr;
    QPushButton *injectLastBtn_ = nullptr;

    // "Generate scene" group.
    QPlainTextEdit *scenePromptEdit_ = nullptr;
    QComboBox *sceneStyleCombo_ = nullptr;
    QCheckBox *sceneReplaceCheck_ = nullptr;
    QPushButton *sceneGenerateBtn_ = nullptr;

    // Overlays list + actions.
    QListWidget *overlaysList_ = nullptr;
    QPushButton *refreshOverlaysBtn_ = nullptr;

    // Footer.
    QPushButton *openBrowserBtn_ = nullptr;
    QPushButton *reloadBtn_ = nullptr;
    QPlainTextEdit *logArea_ = nullptr;

    // Thinking indicator (chatbot-style "…" pulse).
    QLabel *thinkingLabel_ = nullptr;
    QTimer *statusTimer_ = nullptr;
    QTimer *thinkingTimer_ = nullptr;
    int thinkingTick_ = 0;
    int thinkingCount_ = 0;
    QString thinkingMessage_;
};

extern "C" {
#endif /* __cplusplus */

bool spark_dock_register(void);
void spark_dock_unregister(void);

#ifdef __cplusplus
}
#endif

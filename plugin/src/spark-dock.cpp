// Spark Libre dock implementation — native Qt UI.

#include "spark-dock.hpp"
#include "spark-actions.hpp"
#include "spark-http.hpp"

#include <QCheckBox>
#include <QComboBox>
#include <QDateTime>
#include <QDesktopServices>
#include <QDockWidget>
#include <QFormLayout>
#include <QInputDialog>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QListWidgetItem>
#include <QMainWindow>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QTabWidget>
#include <QTimer>
#include <QUrl>
#include <QVBoxLayout>

#include <obs-frontend-api.h>
#include <obs-module.h>

#ifndef SPARK_DEFAULT_URL
#  define SPARK_DEFAULT_URL "http://127.0.0.1:8765/ui/"
#endif

namespace {

/// Lightweight collapsible section: clickable header that toggles a
/// content widget under it. Used in place of fixed QGroupBoxes so the
/// dock fits in narrow side-attached layouts without forcing the user
/// to scroll past every panel.
class CollapsibleSection : public QWidget {
public:
    CollapsibleSection(const QString &title, bool expanded, QWidget *parent)
        : QWidget(parent), title_(title)
    {
        auto *outer = new QVBoxLayout(this);
        outer->setContentsMargins(0, 0, 0, 0);
        outer->setSpacing(0);

        toggle_ = new QPushButton(this);
        toggle_->setCheckable(true);
        toggle_->setChecked(expanded);
        toggle_->setCursor(Qt::PointingHandCursor);
        toggle_->setStyleSheet(
            "text-align: left; font-weight: 600; padding: 5px 8px; font-size: 12px; "
            "background: #1c1f26; color: #e6e8ee; "
            "border: 1px solid #2a2e38; border-radius: 3px;");
        outer->addWidget(toggle_);

        content_ = new QWidget(this);
        contentLayout_ = new QVBoxLayout(content_);
        contentLayout_->setContentsMargins(6, 4, 6, 6);
        contentLayout_->setSpacing(5);
        outer->addWidget(content_);

        QObject::connect(toggle_, &QPushButton::toggled, this,
                         [this](bool on) {
                             content_->setVisible(on);
                             updateHeader();
                         });
        content_->setVisible(expanded);
        updateHeader();
    }

    QVBoxLayout *contentLayout() const { return contentLayout_; }

private:
    void updateHeader()
    {
        const QString arrow = toggle_->isChecked()
                                  ? QStringLiteral("▾  ")
                                  : QStringLiteral("▸  ");
        toggle_->setText(arrow + title_);
    }

    QString title_;
    QPushButton *toggle_ = nullptr;
    QWidget *content_ = nullptr;
    QVBoxLayout *contentLayout_ = nullptr;
};

}  // namespace

QString SparkLibreDock::defaultUrl()
{
    const QByteArray env = qgetenv("SPARK_DOCK_URL");
    if (!env.isEmpty()) {
        return QString::fromUtf8(env);
    }
    return QString::fromUtf8(SPARK_DEFAULT_URL);
}

SparkLibreDock::SparkLibreDock(QWidget *parent)
    : QFrame(parent),
      url_(defaultUrl()),
      http_(new spark::SparkHttp(this))
{
    setObjectName("SparkLibreDock");
    setFrameShape(QFrame::NoFrame);
    setMinimumSize(360, 480);

    // Match the look of the existing web UI (same palette + accent) so
    // the plugin feels like part of the same product instead of an
    // arbitrary Qt widget.
    setStyleSheet(R"qss(
        QFrame#SparkLibreDock { background: #15171c; color: #e6e8ee; }
        QLabel { color: #e6e8ee; }
        QGroupBox {
            border: 1px solid #2a2e38;
            border-radius: 4px;
            margin-top: 10px;
            padding-top: 4px;
            font-weight: 600;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
            color: #8a8f9c;
            font-size: 10px;
            font-weight: 600;
        }
        QPushButton {
            background: #1c1f26;
            color: #e6e8ee;
            border: 1px solid #2a2e38;
            border-radius: 3px;
            padding: 4px 10px;
            font-size: 12px;
        }
        QPushButton:hover { border-color: #39ff8a; }
        QPushButton:pressed { background: #2a2e38; }
        QPushButton:disabled { color: #4d525c; border-color: #2a2e38; }
        QPushButton[primary="true"] {
            background: #39ff8a;
            color: #052613;
            border-color: #39ff8a;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        QPushButton[primary="true"]:hover { background: #6dffa4; border-color: #6dffa4; }
        QPushButton[primary="true"]:pressed { background: #18d469; }
        QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {
            background: #1c1f26;
            border: 1px solid #2a2e38;
            border-radius: 3px;
            padding: 3px 6px;
            color: #e6e8ee;
            font-size: 12px;
        }
        /* Only the editable text widgets get the neon-on-dark text
           selection — applying it to QComboBox makes the closed combo
           look like a filled green button instead of a select. */
        QLineEdit, QPlainTextEdit, QSpinBox {
            selection-background-color: #39ff8a;
            selection-color: #1a1100;
        }
        QComboBox QAbstractItemView {
            background: #1c1f26;
            color: #e6e8ee;
            selection-background-color: #39ff8a;
            selection-color: #052613;
            border: 1px solid #2a2e38;
        }
        QLineEdit:focus, QPlainTextEdit:focus,
        QSpinBox:focus, QComboBox:focus {
            border-color: #39ff8a;
        }
        QListWidget {
            background: #1c1f26;
            border: 1px solid #2a2e38;
            border-radius: 4px;
        }
        QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #15171c; }
        QListWidget::item:selected {
            background: #2a2e38;
            color: #39ff8a;
        }
        QTabWidget::pane {
            border: 1px solid #2a2e38;
            background: #15171c;
            top: -1px;
        }
        QTabBar::tab {
            background: #15171c;
            color: #8a8f9c;
            padding: 5px 14px;
            font-size: 11px;
            border: 1px solid #2a2e38;
            border-bottom: none;
            border-top-left-radius: 3px;
            border-top-right-radius: 3px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background: #1c1f26;
            color: #39ff8a;
            border-bottom: 2px solid #39ff8a;
        }
        QTabBar::tab:hover:!selected { color: #e6e8ee; }
        QScrollBar:vertical { background: #15171c; width: 10px; }
        QScrollBar::handle:vertical {
            background: #2a2e38;
            min-height: 20px;
            border-radius: 5px;
        }
        QScrollBar::handle:vertical:hover { background: #3a3f4a; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0;
        }
    )qss");

    auto *outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);

    statusLabel_ = new QLabel(QStringLiteral("…"), this);
    statusLabel_->setMargin(0);
    statusLabel_->setContentsMargins(8, 4, 8, 4);
    statusLabel_->setTextInteractionFlags(Qt::TextSelectableByMouse);
    statusLabel_->setStyleSheet(
        "background: #1c1f26; border-bottom: 1px solid #2a2e38; "
        "font-family: ui-monospace, monospace; font-size: 11px;");
    outer->addWidget(statusLabel_);

    tabs_ = new QTabWidget(this);
    tabs_->setDocumentMode(true);
    tabs_->addTab(buildInputTab(), QStringLiteral("Input"));
    tabs_->addTab(buildSettingsTab(), QStringLiteral("Settings"));
    outer->addWidget(tabs_, 1);

    wire();

    statusTimer_ = new QTimer(this);
    statusTimer_->setInterval(5000);
    QObject::connect(statusTimer_, &QTimer::timeout, this,
                     &SparkLibreDock::refreshStatus);
    statusTimer_->start();

    // ChatGPT-style thinking indicator: animated braille spinner +
    // gradient pulse on a label. Driven by a 80ms QTimer.
    thinkingTimer_ = new QTimer(this);
    thinkingTimer_->setInterval(80);
    QObject::connect(thinkingTimer_, &QTimer::timeout, this, [this]() {
        if (!thinkingLabel_ || !thinkingLabel_->isVisible()) return;
        static const QStringList frames = {
            "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏",
        };
        thinkingTick_ = (thinkingTick_ + 1) % frames.size();
        // Smooth bar that grows/shrinks in width as the spinner cycles
        // gives a more "thinking" vibe than just a spinner alone.
        const int bars = (thinkingTick_ % 6) + 1;
        QString fill;
        for (int i = 0; i < bars; ++i) fill += "▰";
        for (int i = bars; i < 6; ++i) fill += "▱";
        thinkingLabel_->setText(
            QStringLiteral("%1  %2  %3")
                .arg(frames.at(thinkingTick_))
                .arg(thinkingMessage_)
                .arg(fill));
    });

    // Initial state.
    refreshStatus();
    refreshStyles();
    refreshOverlays();
    refreshSettings();
}

SparkLibreDock::~SparkLibreDock() = default;

// --------------------------------------------------------------------------
// UI construction — Input tab
// --------------------------------------------------------------------------

QWidget *SparkLibreDock::buildInputTab()
{
    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);

    auto *body = new QWidget(scroll);
    auto *bodyLayout = new QVBoxLayout(body);
    bodyLayout->setContentsMargins(4, 4, 4, 4);
    bodyLayout->setSpacing(3);

    // ---- "Generate overlay" — collapsible section ----------------------
    auto *genSection = new CollapsibleSection(
        QStringLiteral("Generate overlay"), /*expanded=*/true, body);
    QWidget *genBox = body;  // alias to satisfy parent param of legacy widgets
    auto *genLayout = genSection->contentLayout();
    promptEdit_ = new QPlainTextEdit(genBox);
    promptEdit_->setPlaceholderText(
        QStringLiteral("Describe the overlay (e.g. neon countdown 5 min)"));
    promptEdit_->setMinimumHeight(48);
    promptEdit_->setMaximumHeight(120);
    genLayout->addWidget(promptEdit_);

    auto *gRow = new QHBoxLayout();
    gRow->addWidget(new QLabel(QStringLiteral("Style:"), genBox));
    styleCombo_ = new QComboBox(genBox);
    styleCombo_->addItem(QStringLiteral("(none)"), QString());
    gRow->addWidget(styleCombo_, 1);
    gRow->addWidget(new QLabel(QStringLiteral("W:"), genBox));
    widthSpin_ = new QSpinBox(genBox);
    widthSpin_->setRange(64, 7680);
    widthSpin_->setValue(1920);
    gRow->addWidget(widthSpin_);
    gRow->addWidget(new QLabel(QStringLiteral("H:"), genBox));
    heightSpin_ = new QSpinBox(genBox);
    heightSpin_->setRange(64, 4320);
    heightSpin_->setValue(1080);
    gRow->addWidget(heightSpin_);
    genLayout->addLayout(gRow);

    auto *gBtnRow = new QHBoxLayout();
    generateBtn_ = new QPushButton(QStringLiteral("Generate"), genBox);
    generateBtn_->setProperty("primary", true);
    injectLastBtn_ = new QPushButton(QStringLiteral("Inject last"), genBox);
    injectLastBtn_->setEnabled(false);
    gBtnRow->addWidget(generateBtn_);
    gBtnRow->addWidget(injectLastBtn_);
    gBtnRow->addStretch(1);
    genLayout->addLayout(gBtnRow);
    bodyLayout->addWidget(genSection);

    // ---- "Generate scene" — collapsible section -------------------------
    auto *sceneSection = new CollapsibleSection(
        QStringLiteral("Generate scene (multi-source)"),
        /*expanded=*/false, body);
    QWidget *sceneBox = body;
    auto *sceneLayout = sceneSection->contentLayout();
    scenePromptEdit_ = new QPlainTextEdit(sceneBox);
    scenePromptEdit_->setPlaceholderText(
        QStringLiteral("Describe the whole scene (background + chat + alerts + ...)"));
    scenePromptEdit_->setMinimumHeight(44);
    scenePromptEdit_->setMaximumHeight(100);
    sceneLayout->addWidget(scenePromptEdit_);

    auto *sceneRow = new QHBoxLayout();
    sceneRow->addWidget(new QLabel(QStringLiteral("Style:"), sceneBox));
    sceneStyleCombo_ = new QComboBox(sceneBox);
    sceneStyleCombo_->addItem(QStringLiteral("(none)"), QString());
    sceneRow->addWidget(sceneStyleCombo_, 1);
    sceneReplaceCheck_ = new QCheckBox(QStringLiteral("Replace existing"), sceneBox);
    sceneRow->addWidget(sceneReplaceCheck_);
    sceneGenerateBtn_ = new QPushButton(QStringLiteral("Generate scene"), sceneBox);
    sceneGenerateBtn_->setProperty("primary", true);
    sceneRow->addWidget(sceneGenerateBtn_);
    sceneLayout->addLayout(sceneRow);
    bodyLayout->addWidget(sceneSection);

    // ---- Overlays list — collapsible section ----------------------------
    auto *ovSection = new CollapsibleSection(
        QStringLiteral("Overlays"), /*expanded=*/true, body);
    QWidget *ovBox = body;
    auto *ovLayout = ovSection->contentLayout();
    overlaysList_ = new QListWidget(ovBox);
    overlaysList_->setSelectionMode(QAbstractItemView::SingleSelection);
    overlaysList_->setMinimumHeight(120);
    ovLayout->addWidget(overlaysList_);

    auto *ovBtns = new QHBoxLayout();
    refreshOverlaysBtn_ = new QPushButton(QStringLiteral("Refresh"), ovBox);
    auto *injectSelBtn = new QPushButton(QStringLiteral("Inject"), ovBox);
    auto *refineSelBtn = new QPushButton(QStringLiteral("Refine…"), ovBox);
    refineSelBtn->setToolTip(
        QStringLiteral("Iterative edit: describe a delta and the LLM patches "
                       "the existing HTML in place"));
    auto *regenSelBtn = new QPushButton(QStringLiteral("Regen"), ovBox);
    auto *deleteSelBtn = new QPushButton(QStringLiteral("Delete"), ovBox);
    auto *deleteAllBtn = new QPushButton(QStringLiteral("Delete all"), ovBox);
    deleteAllBtn->setStyleSheet(
        "color: #ff5470; border-color: #ff5470;");
    ovBtns->addWidget(refreshOverlaysBtn_);
    ovBtns->addWidget(injectSelBtn);
    ovBtns->addWidget(refineSelBtn);
    ovBtns->addWidget(regenSelBtn);
    ovBtns->addWidget(deleteSelBtn);
    ovBtns->addWidget(deleteAllBtn);
    ovBtns->addStretch(1);
    ovLayout->addLayout(ovBtns);
    bodyLayout->addWidget(ovSection);

    // Selected-row helpers.
    auto sel_id = [this]() -> QString {
        auto *it = overlaysList_->currentItem();
        return it ? it->data(Qt::UserRole).toString() : QString();
    };

    // Lock the per-row action buttons while any of them is in-flight so
    // the user can't double-click and end up with two concurrent
    // requests against the same overlay.
    auto lockRowButtons = [injectSelBtn, refineSelBtn, regenSelBtn,
                          deleteSelBtn, deleteAllBtn,
                          refreshBtn = refreshOverlaysBtn_](bool busy) {
        for (auto *b : {injectSelBtn, refineSelBtn, regenSelBtn,
                        deleteSelBtn, deleteAllBtn, refreshBtn}) {
            if (b) b->setEnabled(!busy);
        }
    };

    QObject::connect(injectSelBtn, &QPushButton::clicked, this,
                     [this, sel_id, lockRowButtons]() {
        const QString id = sel_id();
        if (id.isEmpty()) return;
        const QByteArray body =
            QJsonDocument(QJsonObject{{QStringLiteral("overlay_id"), id}})
                .toJson(QJsonDocument::Compact);
        appendLog(QStringLiteral("Inject %1…").arg(id));
        lockRowButtons(true);
        beginThinking(QStringLiteral("Injecting %1 into OBS…").arg(id));
        http_->postJson(
            QStringLiteral("/api/inject"), body,
            [this, id, lockRowButtons](const spark::HttpResult &r) {
                endThinking();
                lockRowButtons(false);
                if (r.ok) {
                    appendLog(QStringLiteral("Injected %1 ✓").arg(id));
                } else {
                    appendLog(QStringLiteral("Inject failed (%1): %2")
                                  .arg(r.status)
                                  .arg(QString::fromUtf8(r.body)));
                }
            });
    });

    QObject::connect(regenSelBtn, &QPushButton::clicked, this,
                     [this, sel_id, lockRowButtons]() {
        const QString id = sel_id();
        if (id.isEmpty()) return;
        QJsonObject obj;
        obj.insert(QStringLiteral("style"),
                   styleCombo_->currentData().toString());
        const QByteArray body = QJsonDocument(obj).toJson(QJsonDocument::Compact);
        appendLog(QStringLiteral("Regenerate %1…").arg(id));
        lockRowButtons(true);
        beginThinking(QStringLiteral("LLM thinking — regenerating %1…").arg(id));
        http_->postJson(
            QStringLiteral("/api/overlays/%1/regenerate").arg(id), body,
            [this, id, lockRowButtons](const spark::HttpResult &r) {
                endThinking();
                lockRowButtons(false);
                if (r.ok) {
                    appendLog(QStringLiteral("Regenerated %1 ✓").arg(id));
                    refreshOverlays();
                } else {
                    appendLog(QStringLiteral("Regen failed (%1): %2")
                                  .arg(r.status)
                                  .arg(QString::fromUtf8(r.body)));
                }
            });
    });

    QObject::connect(refineSelBtn, &QPushButton::clicked, this,
                     [this, sel_id, lockRowButtons]() {
        const QString id = sel_id();
        if (id.isEmpty()) return;
        bool ok = false;
        const QString instruction = QInputDialog::getMultiLineText(
            this,
            QStringLiteral("Refine overlay"),
            QStringLiteral(
                "Describe the change (e.g. \"make the background darker\","
                "\n\"shrink the chat box and move it 80px down\")."),
            QString(), &ok);
        if (!ok || instruction.trimmed().isEmpty()) return;
        QJsonObject obj;
        obj.insert(QStringLiteral("instruction"), instruction);
        const QString style = styleCombo_->currentData().toString();
        if (!style.isEmpty()) obj.insert(QStringLiteral("style"), style);
        const QByteArray body =
            QJsonDocument(obj).toJson(QJsonDocument::Compact);
        appendLog(QStringLiteral("Refine %1: %2…").arg(id, instruction));
        lockRowButtons(true);
        beginThinking(QStringLiteral("LLM patching %1…").arg(id));
        http_->postJson(
            QStringLiteral("/api/overlays/%1/refine").arg(id), body,
            [this, id, lockRowButtons](const spark::HttpResult &r) {
                endThinking();
                lockRowButtons(false);
                if (r.ok) {
                    appendLog(QStringLiteral("Refined %1 ✓").arg(id));
                    refreshOverlays();
                } else {
                    appendLog(QStringLiteral("Refine failed (%1): %2")
                                  .arg(r.status)
                                  .arg(QString::fromUtf8(r.body)));
                }
            });
    });

    QObject::connect(deleteSelBtn, &QPushButton::clicked, this,
                     [this, sel_id, lockRowButtons]() {
        const QString id = sel_id();
        if (id.isEmpty()) return;
        appendLog(QStringLiteral("Delete %1…").arg(id));
        lockRowButtons(true);
        beginThinking(QStringLiteral("Deleting %1…").arg(id));
        http_->del(
            QStringLiteral("/api/overlays/%1").arg(id),
            [this, id, lockRowButtons](const spark::HttpResult &r) {
                endThinking();
                lockRowButtons(false);
                if (r.ok) {
                    appendLog(QStringLiteral("Deleted %1 ✓").arg(id));
                    refreshOverlays();
                } else {
                    appendLog(QStringLiteral("Delete failed (%1): %2")
                                  .arg(r.status)
                                  .arg(QString::fromUtf8(r.body)));
                }
            });
    });

    QObject::connect(deleteAllBtn, &QPushButton::clicked, this,
                     [this, lockRowButtons]() {
        const auto reply = QMessageBox::warning(
            this, QStringLiteral("Spark Libre"),
            QStringLiteral("Delete EVERY overlay (HTML files + index)?\n"
                           "This cannot be undone."),
            QMessageBox::Yes | QMessageBox::Cancel,
            QMessageBox::Cancel);
        if (reply != QMessageBox::Yes) return;
        appendLog(QStringLiteral("Delete ALL overlays…"));
        lockRowButtons(true);
        beginThinking(QStringLiteral("Wiping all overlays…"));
        http_->del(
            QStringLiteral("/api/overlays"),
            [this, lockRowButtons](const spark::HttpResult &r) {
                endThinking();
                lockRowButtons(false);
                if (r.ok) {
                    const auto o = QJsonDocument::fromJson(r.body).object();
                    appendLog(QStringLiteral("Wiped %1 overlays ✓")
                                  .arg(o.value("deleted_count").toInt()));
                    refreshOverlays();
                } else {
                    appendLog(QStringLiteral("Delete-all failed (%1): %2")
                                  .arg(r.status)
                                  .arg(QString::fromUtf8(r.body)));
                }
            });
    });

    // ---- Thinking indicator (always visible) ---------------------------
    thinkingLabel_ = new QLabel(QString(), body);
    thinkingLabel_->setStyleSheet(
        "color: #39ff8a; font-family: ui-monospace, monospace; "
        "font-size: 11px; font-weight: 700; padding: 4px 6px; "
        "background: #1c1f26; border: 1px solid #2a2e38; border-radius: 3px;");
    thinkingLabel_->setVisible(false);
    bodyLayout->addWidget(thinkingLabel_);

    // ---- Activity log — collapsible section -----------------------------
    auto *logSection = new CollapsibleSection(
        QStringLiteral("Activity log"), /*expanded=*/false, body);
    logArea_ = new QPlainTextEdit(body);
    logArea_->setReadOnly(true);
    logArea_->setMaximumHeight(110);
    logArea_->setStyleSheet("font-family: monospace; font-size: 11px;");
    logSection->contentLayout()->addWidget(logArea_);
    bodyLayout->addWidget(logSection);

    // (Refresh status + Open UI in browser moved to the Settings tab —
    // they aren't part of the create-flow and used to clutter the
    // Input tab footer.)

    bodyLayout->addStretch(1);
    scroll->setWidget(body);
    return scroll;
}

// --------------------------------------------------------------------------
// UI construction — Settings tab
// --------------------------------------------------------------------------

QWidget *SparkLibreDock::buildSettingsTab()
{
    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);

    auto *body = new QWidget(scroll);
    auto *layout = new QVBoxLayout(body);
    layout->setContentsMargins(6, 6, 6, 6);
    layout->setSpacing(6);

    auto *llmBox = new QGroupBox(QStringLiteral("LLM"), body);
    auto *llmForm = new QFormLayout(llmBox);
    settingsModelEdit_ = new QLineEdit(llmBox);
    settingsModelEdit_->setPlaceholderText(
        QStringLiteral("e.g. nvidia_nim/meta/llama-3.3-70b-instruct"));
    llmForm->addRow(QStringLiteral("Default model:"), settingsModelEdit_);
    settingsLlmBaseEdit_ = new QLineEdit(llmBox);
    settingsLlmBaseEdit_->setPlaceholderText(
        QStringLiteral("(optional) http://127.0.0.1:11434  for Ollama"));
    llmForm->addRow(QStringLiteral("Base URL:"), settingsLlmBaseEdit_);
    settingsKeysLabel_ = new QLabel(QStringLiteral("API keys: …"), llmBox);
    settingsKeysLabel_->setStyleSheet("color: #8a8f9c;");
    settingsKeysLabel_->setWordWrap(true);
    llmForm->addRow(QStringLiteral("Configured:"), settingsKeysLabel_);

    // --- Add / replace API key row -------------------------------------
    auto *keyRow = new QHBoxLayout();
    settingsKeyProviderCombo_ = new QComboBox(llmBox);
    // Match _ENV_OVERRIDES in secrets_store; backend translates to
    // the right env var (e.g. anthropic → ANTHROPIC_API_KEY).
    for (const QString &p : {
             QStringLiteral("anthropic"),
             QStringLiteral("openai"),
             QStringLiteral("gemini"),
             QStringLiteral("groq"),
             QStringLiteral("deepseek"),
             QStringLiteral("nvidia_nim"),
             QStringLiteral("openrouter"),
             QStringLiteral("mistral"),
             QStringLiteral("cohere"),
             QStringLiteral("ollama"),
         }) {
        settingsKeyProviderCombo_->addItem(p, p);
    }
    settingsKeyValueEdit_ = new QLineEdit(llmBox);
    settingsKeyValueEdit_->setEchoMode(QLineEdit::Password);
    settingsKeyValueEdit_->setPlaceholderText(QStringLiteral("paste API key…"));
    settingsKeySaveBtn_ = new QPushButton(QStringLiteral("Save key"), llmBox);
    keyRow->addWidget(settingsKeyProviderCombo_);
    keyRow->addWidget(settingsKeyValueEdit_, 1);
    keyRow->addWidget(settingsKeySaveBtn_);
    llmForm->addRow(QStringLiteral("Add key:"), keyRow);
    layout->addWidget(llmBox);

    auto *obsBox = new QGroupBox(QStringLiteral("OBS WebSocket"), body);
    auto *obsForm = new QFormLayout(obsBox);
    settingsObsHostEdit_ = new QLineEdit(obsBox);
    settingsObsHostEdit_->setPlaceholderText(QStringLiteral("127.0.0.1"));
    obsForm->addRow(QStringLiteral("Host:"), settingsObsHostEdit_);
    settingsObsPortSpin_ = new QSpinBox(obsBox);
    settingsObsPortSpin_->setRange(1, 65535);
    settingsObsPortSpin_->setValue(4455);
    obsForm->addRow(QStringLiteral("Port:"), settingsObsPortSpin_);
    settingsSceneNameEdit_ = new QLineEdit(obsBox);
    settingsSceneNameEdit_->setPlaceholderText(
        QStringLiteral("Spark Libre"));
    obsForm->addRow(QStringLiteral("Scene name:"), settingsSceneNameEdit_);

    auto *obsHint = new QLabel(
        QStringLiteral("If \"OBS: offline\" above: Tools → WebSocket Server "
                       "Settings → Enable, password = SPARK_OBS_PASSWORD."),
        obsBox);
    obsHint->setStyleSheet("color: #39ff8a; font-size: 11px;");
    obsHint->setWordWrap(true);
    obsForm->addRow(obsHint);
    layout->addWidget(obsBox);

    auto *btnRow = new QHBoxLayout();
    settingsReloadBtn_ = new QPushButton(
        QStringLiteral("Reload from backend"), body);
    settingsSaveBtn_ = new QPushButton(QStringLiteral("Save"), body);
    settingsSaveBtn_->setProperty("primary", true);
    btnRow->addWidget(settingsReloadBtn_);
    btnRow->addWidget(settingsSaveBtn_);
    btnRow->addStretch(1);
    layout->addLayout(btnRow);

    // ---- Diagnostics row (moved from Input tab footer) ----------------
    auto *diagBox = new QGroupBox(QStringLiteral("Diagnostics"), body);
    auto *diagLayout = new QHBoxLayout(diagBox);
    reloadBtn_ = new QPushButton(QStringLiteral("Refresh status"), diagBox);
    openBrowserBtn_ = new QPushButton(
        QStringLiteral("Open UI in browser"), diagBox);
    diagLayout->addWidget(reloadBtn_);
    diagLayout->addWidget(openBrowserBtn_);
    diagLayout->addStretch(1);
    layout->addWidget(diagBox);

    layout->addStretch(1);
    scroll->setWidget(body);
    return scroll;
}

void SparkLibreDock::wire()
{
    QObject::connect(generateBtn_, &QPushButton::clicked, this,
                     &SparkLibreDock::doGenerate);
    QObject::connect(injectLastBtn_, &QPushButton::clicked, this,
                     &SparkLibreDock::doInjectLast);
    QObject::connect(sceneGenerateBtn_, &QPushButton::clicked, this,
                     &SparkLibreDock::doGenerateScene);

    // Disable Generate buttons while their prompt is empty so the user
    // doesn't fire a no-op LLM call against the backend.
    auto syncGen = [this]() {
        generateBtn_->setEnabled(!promptEdit_->toPlainText().trimmed().isEmpty());
    };
    auto syncScene = [this]() {
        sceneGenerateBtn_->setEnabled(
            !scenePromptEdit_->toPlainText().trimmed().isEmpty());
    };
    QObject::connect(promptEdit_, &QPlainTextEdit::textChanged, this, syncGen);
    QObject::connect(scenePromptEdit_, &QPlainTextEdit::textChanged, this, syncScene);
    syncGen();
    syncScene();
    QObject::connect(refreshOverlaysBtn_, &QPushButton::clicked, this,
                     &SparkLibreDock::refreshOverlays);
    QObject::connect(reloadBtn_, &QPushButton::clicked, this,
                     &SparkLibreDock::refreshStatus);
    QObject::connect(openBrowserBtn_, &QPushButton::clicked, this,
                     &SparkLibreDock::onOpenInBrowser);
    if (settingsSaveBtn_) {
        QObject::connect(settingsSaveBtn_, &QPushButton::clicked, this,
                         &SparkLibreDock::saveSettings);
    }
    if (settingsReloadBtn_) {
        QObject::connect(settingsReloadBtn_, &QPushButton::clicked, this,
                         &SparkLibreDock::refreshSettings);
    }
    if (settingsKeySaveBtn_) {
        QObject::connect(settingsKeySaveBtn_, &QPushButton::clicked, this, [this]() {
            const QString provider = settingsKeyProviderCombo_->currentData().toString();
            const QString value = settingsKeyValueEdit_->text().trimmed();
            if (provider.isEmpty() || value.isEmpty()) {
                appendLog(QStringLiteral("Pick a provider and paste a key first."));
                return;
            }
            QJsonObject obj;
            obj.insert(QStringLiteral("kind"), QStringLiteral("llm"));
            obj.insert(QStringLiteral("provider"), provider);
            obj.insert(QStringLiteral("value"), value);
            const QByteArray body =
                QJsonDocument(obj).toJson(QJsonDocument::Compact);
            settingsKeySaveBtn_->setEnabled(false);
            appendLog(QStringLiteral("Saving %1 API key…").arg(provider));
            beginThinking(QStringLiteral("Saving %1 API key…").arg(provider));
            http_->postJson(
                QStringLiteral("/api/secrets"), body,
                [this, provider](const spark::HttpResult &r) {
                    endThinking();
                    settingsKeySaveBtn_->setEnabled(true);
                    if (r.ok) {
                        appendLog(QStringLiteral("Saved %1 key ✓").arg(provider));
                        settingsKeyValueEdit_->clear();
                        refreshSettings();   // refresh "Configured" line
                        refreshStatus();     // status badge may flip green
                    } else {
                        appendLog(QStringLiteral("Save key failed (%1): %2")
                                      .arg(r.status)
                                      .arg(QString::fromUtf8(r.body)));
                    }
                });
        });
    }
}

void SparkLibreDock::refreshSettings()
{
    http_->getJson(
        QStringLiteral("/api/settings"),
        [this](const spark::HttpResult &r) {
            if (!r.ok) {
                appendLog(QStringLiteral("Settings reload failed (%1)").arg(r.status));
                return;
            }
            const auto o = QJsonDocument::fromJson(r.body).object();
            settingsModelEdit_->setText(o.value("default_model").toString());
            settingsLlmBaseEdit_->setText(o.value("llm_base_url").toString());
            settingsObsHostEdit_->setText(o.value("obs_host").toString());
            settingsObsPortSpin_->setValue(o.value("obs_port").toInt(4455));
            settingsSceneNameEdit_->setText(
                o.value("obs_scene_name").toString());
            const auto arr = o.value("providers_with_key").toArray();
            QStringList list;
            for (const auto &v : arr) list << v.toString();
            settingsKeysLabel_->setText(list.isEmpty()
                                            ? QStringLiteral("(none)")
                                            : list.join(", "));
        });
}

void SparkLibreDock::saveSettings()
{
    QJsonObject obj;
    obj.insert(QStringLiteral("default_model"), settingsModelEdit_->text());
    obj.insert(QStringLiteral("llm_base_url"), settingsLlmBaseEdit_->text());
    obj.insert(QStringLiteral("obs_host"), settingsObsHostEdit_->text());
    obj.insert(QStringLiteral("obs_port"), settingsObsPortSpin_->value());
    obj.insert(QStringLiteral("obs_scene_name"),
               settingsSceneNameEdit_->text());
    const QByteArray body = QJsonDocument(obj).toJson(QJsonDocument::Compact);
    settingsSaveBtn_->setEnabled(false);
    appendLog(QStringLiteral("Saving settings…"));
    beginThinking(QStringLiteral("Saving settings…"));
    http_->putJson(
        QStringLiteral("/api/settings"), body,
        [this](const spark::HttpResult &r) {
            endThinking();
            settingsSaveBtn_->setEnabled(true);
            if (r.ok) {
                appendLog(QStringLiteral("Settings saved."));
                refreshStatus();
            } else {
                appendLog(QStringLiteral("Save failed (%1): %2")
                              .arg(r.status)
                              .arg(QString::fromUtf8(r.body)));
            }
        });
}

// --------------------------------------------------------------------------
// Backend interactions
// --------------------------------------------------------------------------

void SparkLibreDock::setStatusLine(const QString &text, bool ok)
{
    statusLabel_->setText(text);
    // Keep the bg/border style from the constructor; only swap color.
    statusLabel_->setStyleSheet(QStringLiteral(
        "background: #1c1f26; border-bottom: 1px solid #2a2e38; "
        "font-family: ui-monospace, monospace; font-size: 10px; font-weight: 600; "
        "letter-spacing: 0.3px; padding: 4px 8px; color: %1;"
    ).arg(ok ? "#39ff8a" : "#ff5470"));
}

void SparkLibreDock::appendLog(const QString &text)
{
    if (!logArea_) return;
    const QString stamp = QDateTime::currentDateTime().toString("HH:mm:ss");
    logArea_->appendPlainText(QStringLiteral("[%1] %2").arg(stamp, text));
}

void SparkLibreDock::beginThinking(const QString &label)
{
    thinkingCount_++;
    thinkingMessage_ = label.isEmpty() ? QStringLiteral("Thinking…") : label;
    if (thinkingLabel_) {
        thinkingLabel_->setVisible(true);
    }
    if (thinkingTimer_ && !thinkingTimer_->isActive()) {
        thinkingTick_ = 0;
        thinkingTimer_->start();
    }
}

void SparkLibreDock::endThinking()
{
    thinkingCount_ = std::max(0, thinkingCount_ - 1);
    if (thinkingCount_ > 0) return;
    if (thinkingTimer_) thinkingTimer_->stop();
    if (thinkingLabel_) {
        thinkingLabel_->setVisible(false);
        thinkingLabel_->clear();
    }
    thinkingMessage_.clear();
}

void SparkLibreDock::refreshStatus()
{
    http_->getJson(QStringLiteral("/api/status"),
                   [this](const spark::HttpResult &r) {
                       if (!r.ok) {
                           setStatusLine(QStringLiteral("backend offline"), false);
                           return;
                       }
                       const auto obj = QJsonDocument::fromJson(r.body).object();
                       const bool obsConnected = obj.value("obs_connected").toBool();
                       const bool hasKey = obj.value("has_default_llm_key").toBool();
                       const QString model = obj.value("default_model").toString();
                       const QString line =
                           QStringLiteral("%1 OBS  %2 LLM  ·  %3")
                               .arg(obsConnected ? QStringLiteral("●") : QStringLiteral("○"))
                               .arg(hasKey ? QStringLiteral("●") : QStringLiteral("○"))
                               .arg(model);
                       setStatusLine(line, obsConnected && hasKey);
                   });
}

void SparkLibreDock::refreshStyles()
{
    http_->getJson(QStringLiteral("/api/styles"),
                   [this](const spark::HttpResult &r) {
                       if (!r.ok) return;
                       const auto arr = QJsonDocument::fromJson(r.body).array();
                       for (auto *combo : {styleCombo_, sceneStyleCombo_}) {
                           if (!combo) continue;
                           // keep the "(none)" entry at index 0
                           while (combo->count() > 1) combo->removeItem(1);
                           for (const auto &v : arr) {
                               const auto o = v.toObject();
                               const QString key = o.value("key").toString();
                               combo->addItem(key, key);
                           }
                       }
                   });
}

void SparkLibreDock::refreshOverlays()
{
    http_->getJson(QStringLiteral("/api/overlays"),
                   [this](const spark::HttpResult &r) {
                       if (!r.ok) return;
                       const auto arr = QJsonDocument::fromJson(r.body).array();
                       overlaysList_->clear();
                       for (const auto &v : arr) {
                           const auto o = v.toObject();
                           const QString id = o.value("id").toString();
                           const QString title = o.value("title").toString();
                           const QString model = o.value("model").toString();
                           auto *item = new QListWidgetItem(
                               QStringLiteral("%1\n  %2 · %3")
                                   .arg(title.isEmpty() ? id : title)
                                   .arg(model, id),
                               overlaysList_);
                           item->setData(Qt::UserRole, id);
                       }
                   });
}

void SparkLibreDock::doGenerate()
{
    const QString prompt = promptEdit_->toPlainText().trimmed();
    if (prompt.isEmpty()) return;
    QJsonObject obj;
    obj.insert(QStringLiteral("prompt"), prompt);
    obj.insert(QStringLiteral("width"), widthSpin_->value());
    obj.insert(QStringLiteral("height"), heightSpin_->value());
    const QString style = styleCombo_->currentData().toString();
    if (!style.isEmpty()) obj.insert(QStringLiteral("style"), style);
    const QByteArray body = QJsonDocument(obj).toJson(QJsonDocument::Compact);

    appendLog(QStringLiteral("Generate (style=%1)…")
                  .arg(style.isEmpty() ? "none" : style));
    generateBtn_->setEnabled(false);
    generateBtn_->setText(QStringLiteral("GENERATING…"));
    sceneGenerateBtn_->setEnabled(false);
    injectLastBtn_->setEnabled(false);
    beginThinking(QStringLiteral("LLM thinking — overlay (%1)")
                      .arg(style.isEmpty() ? "no style" : style));
    http_->postJson(
        QStringLiteral("/api/generate"), body,
        [this](const spark::HttpResult &r) {
            endThinking();
            generateBtn_->setEnabled(true);
            generateBtn_->setText(QStringLiteral("Generate"));
            sceneGenerateBtn_->setEnabled(true);
            if (!r.ok) {
                appendLog(QStringLiteral("Generate failed (%1): %2")
                              .arg(r.status)
                              .arg(QString::fromUtf8(r.body)));
                return;
            }
            const auto o = QJsonDocument::fromJson(r.body).object();
            lastOverlayId_ = o.value("overlay_id").toString();
            injectLastBtn_->setEnabled(!lastOverlayId_.isEmpty());
            appendLog(QStringLiteral("Generated %1 ✓ (model=%2)")
                          .arg(lastOverlayId_)
                          .arg(o.value("model").toString()));
            refreshOverlays();
        });
}

void SparkLibreDock::doGenerateScene()
{
    const QString prompt = scenePromptEdit_->toPlainText().trimmed();
    if (prompt.isEmpty()) return;
    QJsonObject obj;
    obj.insert(QStringLiteral("prompt"), prompt);
    obj.insert(QStringLiteral("replace"), sceneReplaceCheck_->isChecked());
    const QString style = sceneStyleCombo_->currentData().toString();
    if (!style.isEmpty()) obj.insert(QStringLiteral("style"), style);
    const QByteArray body = QJsonDocument(obj).toJson(QJsonDocument::Compact);

    appendLog(QStringLiteral("Generate scene (style=%1)…")
                  .arg(style.isEmpty() ? "none" : style));
    sceneGenerateBtn_->setEnabled(false);
    sceneGenerateBtn_->setText(QStringLiteral("GENERATING…"));
    generateBtn_->setEnabled(false);
    beginThinking(QStringLiteral("LLM thinking — multi-source scene (%1)")
                      .arg(style.isEmpty() ? "no style" : style));
    http_->postJson(
        QStringLiteral("/api/scenes/templates"), body,
        [this](const spark::HttpResult &r) {
            endThinking();
            sceneGenerateBtn_->setEnabled(true);
            sceneGenerateBtn_->setText(QStringLiteral("Generate scene"));
            generateBtn_->setEnabled(true);
            if (!r.ok) {
                appendLog(QStringLiteral("Scene gen failed (%1): %2")
                              .arg(r.status)
                              .arg(QString::fromUtf8(r.body)));
                return;
            }
            const auto o = QJsonDocument::fromJson(r.body).object();
            const QString scene = o.value("scene").toString();
            const int n = o.value("sources").toArray().size();
            appendLog(QStringLiteral("Scene '%1' built ✓ (%2 sources)")
                          .arg(scene)
                          .arg(n));
            refreshOverlays();
        });
}

void SparkLibreDock::doInjectLast()
{
    if (lastOverlayId_.isEmpty()) return;
    QJsonObject obj{{"overlay_id", lastOverlayId_}};
    const QByteArray body = QJsonDocument(obj).toJson(QJsonDocument::Compact);
    appendLog(QStringLiteral("Inject %1…").arg(lastOverlayId_));
    injectLastBtn_->setEnabled(false);
    beginThinking(QStringLiteral("Injecting overlay into OBS…"));
    http_->postJson(QStringLiteral("/api/inject"), body,
                    [this](const spark::HttpResult &r) {
                        endThinking();
                        injectLastBtn_->setEnabled(!lastOverlayId_.isEmpty());
                        if (r.ok) {
                            appendLog(QStringLiteral("Inject ok ✓"));
                        } else {
                            appendLog(QStringLiteral("Inject failed (%1): %2")
                                          .arg(r.status)
                                          .arg(QString::fromUtf8(r.body)));
                        }
                    });
}

void SparkLibreDock::onOpenInBrowser()
{
    QDesktopServices::openUrl(QUrl(url_));
}

// --------------------------------------------------------------------------
// C glue
// --------------------------------------------------------------------------

static SparkLibreDock *g_dock_instance = nullptr;
static bool g_dock_added = false;

static void spark_actually_add_dock()
{
    if (g_dock_added) {
        return;
    }
    auto *dock = new SparkLibreDock(nullptr);
#if LIBOBS_API_VER >= MAKE_SEMANTIC_VERSION(30, 0, 0)
    const bool ok = obs_frontend_add_dock_by_id(
        "spark-libre-dock",
        "Spark Libre",
        dock);
    if (!ok) {
        blog(LOG_WARNING, "obs_frontend_add_dock_by_id returned false");
        delete dock;
        return;
    }
#else
    auto *wrapper = new QDockWidget("Spark Libre");
    wrapper->setObjectName("spark-libre-dock");
    wrapper->setWidget(dock);
    obs_frontend_add_dock(wrapper);
#endif
    g_dock_instance = dock;
    g_dock_added = true;

    // First-time placement: register features, then dock to the right
    // edge so the user sees a real attached pane (not a free-floating
    // window). We tabify over Controls if it exists, falling back to a
    // plain right-edge dock. Subsequent OBS launches restore whatever
    // the user moved it to via Qt's saveState/restoreState path.
    auto *main = static_cast<QMainWindow *>(obs_frontend_get_main_window());
    QDockWidget *dw = main ? main->findChild<QDockWidget *>("spark-libre-dock")
                           : nullptr;
    if (dw) {
        dw->setAllowedAreas(Qt::AllDockWidgetAreas);
        dw->setFeatures(QDockWidget::DockWidgetClosable
                        | QDockWidget::DockWidgetMovable
                        | QDockWidget::DockWidgetFloatable);

        // Try to find an existing right-side dock to tabify with so we
        // don't shove the user's layout. "Controls" is always there.
        QDockWidget *anchor = nullptr;
        for (auto *cand : main->findChildren<QDockWidget *>()) {
            if (!cand || cand == dw) continue;
            if (main->dockWidgetArea(cand) == Qt::RightDockWidgetArea) {
                anchor = cand;
                break;
            }
        }

        if (dw->isFloating() || main->dockWidgetArea(dw) == Qt::NoDockWidgetArea) {
            if (anchor) {
                main->tabifyDockWidget(anchor, dw);
                blog(LOG_INFO,
                     "[obs-spark-libre] tabified with %s on right edge",
                     anchor->objectName().toUtf8().constData());
            } else {
                main->addDockWidget(Qt::RightDockWidgetArea, dw);
                blog(LOG_INFO,
                     "[obs-spark-libre] attached to right dock area");
            }
            dw->setFloating(false);
        }
        dw->show();
        dw->raise();
    } else {
        blog(LOG_WARNING,
             "[obs-spark-libre] could not find QDockWidget post-register");
    }
    blog(LOG_INFO, "[obs-spark-libre] dock registered (url=%s)",
         dock->defaultUrl().toUtf8().constData());
}

static void on_frontend_event(enum obs_frontend_event event, void *)
{
    if (event == OBS_FRONTEND_EVENT_FINISHED_LOADING) {
        spark_actually_add_dock();
        spark_actions_install();
    }
}

extern "C" bool spark_dock_register(void)
{
    obs_frontend_add_event_callback(on_frontend_event, nullptr);
    blog(LOG_INFO,
         "[obs-spark-libre] queued dock registration for FINISHED_LOADING");
    return true;
}

extern "C" void spark_dock_unregister(void)
{
    obs_frontend_remove_event_callback(on_frontend_event, nullptr);
    g_dock_instance = nullptr;
}

// Open Spark dock implementation — native Qt UI.

#include "open-spark-dock.hpp"
#include "open-spark-actions.hpp"
#include "open-spark-http.hpp"

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
#include <QScrollBar>
#include <QSpinBox>
#include <QTabWidget>
#include <QTextBrowser>
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

QString OpenSparkDock::defaultUrl()
{
    const QByteArray env = qgetenv("OPENSPARK_DOCK_URL");
    if (!env.isEmpty()) {
        return QString::fromUtf8(env);
    }
    return QString::fromUtf8(SPARK_DEFAULT_URL);
}

OpenSparkDock::OpenSparkDock(QWidget *parent)
    : QFrame(parent),
      url_(defaultUrl()),
      http_(new openspark::OpenSparkHttp(this))
{
    setObjectName("OpenSparkDock");
    setFrameShape(QFrame::NoFrame);
    setMinimumSize(360, 480);

    // Match the look of the existing web UI (same palette + accent) so
    // the plugin feels like part of the same product instead of an
    // arbitrary Qt widget.
    setStyleSheet(R"qss(
        QFrame#OpenSparkDock { background: #15171c; color: #e6e8ee; }
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
    // The Input tab is gone — the Agent does generate / scene / inject /
    // list / delete via natural language + tools, so a parallel form UI
    // was redundant. (The browser UI at /ui/ keeps the full form for
    // power users who want exact-pixel control.)
    tabs_->addTab(buildAgentTab(), QStringLiteral("Agent"));
    tabs_->addTab(buildSettingsTab(), QStringLiteral("Settings"));
    outer->addWidget(tabs_, 1);

    wire();

    statusTimer_ = new QTimer(this);
    statusTimer_->setInterval(5000);
    QObject::connect(statusTimer_, &QTimer::timeout, this,
                     &OpenSparkDock::refreshStatus);
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

    // Initial state. (refreshStyles/refreshOverlays only fed the old
    // Input tab which no longer exists.)
    refreshStatus();
    refreshSettings();
    agentLoadSession();
}

OpenSparkDock::~OpenSparkDock() = default;

// --------------------------------------------------------------------------
// UI construction — Input tab
// --------------------------------------------------------------------------

QWidget *OpenSparkDock::buildAgentTab()
{
    auto *w = new QWidget(this);
    auto *v = new QVBoxLayout(w);
    v->setContentsMargins(6, 6, 6, 6);
    v->setSpacing(6);

    agentView_ = new QTextBrowser(w);
    agentView_->setOpenExternalLinks(true);
    agentView_->setStyleSheet(
        "background:#1c1f26; border:1px solid #2a2e38; border-radius:4px; "
        "font-size:12px;");
    v->addWidget(agentView_, 1);

    agentInput_ = new QPlainTextEdit(w);
    agentInput_->setPlaceholderText(QStringLiteral(
        "Tell the agent what to do — e.g. \"add my webcam bottom-right "
        "with a chroma key and a neon frame, then a chat box on the left\""));
    agentInput_->setMaximumHeight(70);
    v->addWidget(agentInput_);

    auto *row = new QHBoxLayout();
    agentDryRun_ = new QCheckBox(QStringLiteral("Dry-run (confirm destructive)"), w);
    agentDryRun_->setChecked(true);
    agentUndoBtn_ = new QPushButton(QStringLiteral("Undo last"), w);
    agentUndoBtn_->setToolTip(QStringLiteral(
        "Remove the inputs the agent added in its last turn"));
    agentUndoBtn_->setStyleSheet("color:#ff5470; border-color:#ff5470;");
    agentUndoBtn_->setEnabled(false);
    auto *agentNewBtn = new QPushButton(QStringLiteral("New chat"), w);
    agentNewBtn->setToolTip(QStringLiteral(
        "Clear the conversation so an old goal can't carry over"));
    agentSendBtn_ = new QPushButton(QStringLiteral("Send"), w);
    agentSendBtn_->setProperty("primary", true);
    row->addWidget(agentDryRun_);
    row->addStretch(1);
    row->addWidget(agentNewBtn);
    row->addWidget(agentUndoBtn_);
    row->addWidget(agentSendBtn_);
    v->addLayout(row);
    QObject::connect(agentUndoBtn_, &QPushButton::clicked, this,
                     &OpenSparkDock::agentDoUndo);
    QObject::connect(agentNewBtn, &QPushButton::clicked, this, [this]() {
        agentHistory_.clear();
        agentLastCreatedInputs_.clear();
        agentUndoBtn_->setEnabled(false);
        agentView_->setHtml(
            "<div style='color:#8a8f9c'>New conversation. Old context "
            "cleared.</div>");
        http_->del(QStringLiteral("/api/agent/session"),
                   [](const openspark::HttpResult &) {});
    });

    agentView_->setHtml(
        "<div style='color:#8a8f9c'>Open Spark agent. It can build "
        "overlays, whole scenes, add your camera, set transforms and "
        "apply filters (chroma key, color, sharpen, LUT, borders). "
        "Ask in plain language.</div>");

    QObject::connect(agentSendBtn_, &QPushButton::clicked, this,
                     &OpenSparkDock::doAgentSend);
    return w;
}

QWidget *OpenSparkDock::buildInputTab()
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
            [this, id, lockRowButtons](const openspark::HttpResult &r) {
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
            [this, id, lockRowButtons](const openspark::HttpResult &r) {
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
            [this, id, lockRowButtons](const openspark::HttpResult &r) {
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
            [this, id, lockRowButtons](const openspark::HttpResult &r) {
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
            this, QStringLiteral("Open Spark"),
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
            [this, lockRowButtons](const openspark::HttpResult &r) {
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

QWidget *OpenSparkDock::buildSettingsTab()
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

    settingsAgentModelEdit_ = new QLineEdit(llmBox);
    settingsAgentModelEdit_->setPlaceholderText(QStringLiteral(
        "(optional) strong tool-calling model for the Agent — "
        "blank = Default model"));
    auto *agentModelRow = new QWidget(llmBox);
    auto *amrl = new QHBoxLayout(agentModelRow);
    amrl->setContentsMargins(0, 0, 0, 0);
    amrl->addWidget(settingsAgentModelEdit_, 1);
    settingsAgentModelStatus_ = new QLabel(QString(), agentModelRow);
    settingsAgentModelStatus_->setMinimumWidth(90);
    amrl->addWidget(settingsAgentModelStatus_);
    llmForm->addRow(QStringLiteral("Agent model:"), agentModelRow);

    // Validate tool-calling support when the user finishes editing the
    // field, so they don't save a model the agent can't use.
    QObject::connect(
        settingsAgentModelEdit_, &QLineEdit::editingFinished, this, [this]() {
            const QString m = settingsAgentModelEdit_->text().trimmed();
            if (m.isEmpty()) {
                settingsAgentModelStatus_->setText(
                    QStringLiteral("<span style='color:#8a8f9c'>= Default</span>"));
                return;
            }
            settingsAgentModelStatus_->setText(
                QStringLiteral("<span style='color:#8a8f9c'>checking…</span>"));
            http_->getJson(
                QStringLiteral("/api/agent/model-check?model=%1")
                    .arg(QString::fromUtf8(QUrl::toPercentEncoding(m))),
                [this](const openspark::HttpResult &r) {
                    if (!r.ok) return;
                    const auto o = QJsonDocument::fromJson(r.body).object();
                    const QJsonValue sup = o.value("supported");
                    QString html;
                    if (sup.isBool() && sup.toBool()) {
                        html = "<span style='color:#39ff8a'>✓ tool-ready</span>";
                    } else if (sup.isBool() && !sup.toBool()) {
                        html = "<span style='color:#ff5470'>✗ no tools</span>";
                    } else {
                        html = "<span style='color:#ffb14a'>? unverified</span>";
                    }
                    settingsAgentModelStatus_->setText(html);
                });
        });

    settingsQualitySpin_ = new QSpinBox(llmBox);
    settingsQualitySpin_->setRange(1, 3);
    settingsQualitySpin_->setToolTip(QStringLiteral(
        "1 = fast single pass. 2 = generate + art-director critique "
        "refine (slower, more premium)."));
    llmForm->addRow(QStringLiteral("Overlay quality passes:"),
                    settingsQualitySpin_);

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
        QStringLiteral("Open Spark"));
    obsForm->addRow(QStringLiteral("Scene name:"), settingsSceneNameEdit_);

    auto *obsHint = new QLabel(
        QStringLiteral("If \"OBS: offline\" above: Tools → WebSocket Server "
                       "Settings → Enable, password = OPENSPARK_OBS_PASSWORD."),
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

void OpenSparkDock::wire()
{
    // Input-tab widgets no longer exist (Agent replaces that flow).
    // The Settings tab's "Open in browser" button is wired below if
    // present.
    if (openBrowserBtn_) {
        QObject::connect(openBrowserBtn_, &QPushButton::clicked, this,
                         &OpenSparkDock::onOpenInBrowser);
    }
    if (reloadBtn_) {
        QObject::connect(reloadBtn_, &QPushButton::clicked, this,
                         &OpenSparkDock::refreshStatus);
    }
    if (settingsSaveBtn_) {
        QObject::connect(settingsSaveBtn_, &QPushButton::clicked, this,
                         &OpenSparkDock::saveSettings);
    }
    if (settingsReloadBtn_) {
        QObject::connect(settingsReloadBtn_, &QPushButton::clicked, this,
                         &OpenSparkDock::refreshSettings);
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
                [this, provider](const openspark::HttpResult &r) {
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

void OpenSparkDock::refreshSettings()
{
    http_->getJson(
        QStringLiteral("/api/settings"),
        [this](const openspark::HttpResult &r) {
            if (!r.ok) {
                appendLog(QStringLiteral("Settings reload failed (%1)").arg(r.status));
                return;
            }
            const auto o = QJsonDocument::fromJson(r.body).object();
            settingsModelEdit_->setText(o.value("default_model").toString());
            settingsAgentModelEdit_->setText(
                o.value("agent_model").toString());
            settingsQualitySpin_->setValue(
                o.value("overlay_quality_passes").toInt(1));
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

void OpenSparkDock::saveSettings()
{
    QJsonObject obj;
    obj.insert(QStringLiteral("default_model"), settingsModelEdit_->text());
    obj.insert(QStringLiteral("agent_model"),
               settingsAgentModelEdit_->text());
    obj.insert(QStringLiteral("overlay_quality_passes"),
               settingsQualitySpin_->value());
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
        [this](const openspark::HttpResult &r) {
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

void OpenSparkDock::setStatusLine(const QString &text, bool ok)
{
    statusLabel_->setText(text);
    // Keep the bg/border style from the constructor; only swap color.
    statusLabel_->setStyleSheet(QStringLiteral(
        "background: #1c1f26; border-bottom: 1px solid #2a2e38; "
        "font-family: ui-monospace, monospace; font-size: 10px; font-weight: 600; "
        "letter-spacing: 0.3px; padding: 4px 8px; color: %1;"
    ).arg(ok ? "#39ff8a" : "#ff5470"));
}

void OpenSparkDock::appendLog(const QString &text)
{
    if (!logArea_) return;
    const QString stamp = QDateTime::currentDateTime().toString("HH:mm:ss");
    logArea_->appendPlainText(QStringLiteral("[%1] %2").arg(stamp, text));
}

void OpenSparkDock::beginThinking(const QString &label)
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

void OpenSparkDock::endThinking()
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

void OpenSparkDock::refreshStatus()
{
    http_->getJson(QStringLiteral("/api/status"),
                   [this](const openspark::HttpResult &r) {
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

void OpenSparkDock::refreshStyles()
{
    http_->getJson(QStringLiteral("/api/styles"),
                   [this](const openspark::HttpResult &r) {
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

void OpenSparkDock::refreshOverlays()
{
    http_->getJson(QStringLiteral("/api/overlays"),
                   [this](const openspark::HttpResult &r) {
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

void OpenSparkDock::doGenerate()
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
        [this](const openspark::HttpResult &r) {
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

void OpenSparkDock::doGenerateScene()
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
        [this](const openspark::HttpResult &r) {
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

void OpenSparkDock::doInjectLast()
{
    if (lastOverlayId_.isEmpty()) return;
    QJsonObject obj{{"overlay_id", lastOverlayId_}};
    const QByteArray body = QJsonDocument(obj).toJson(QJsonDocument::Compact);
    appendLog(QStringLiteral("Inject %1…").arg(lastOverlayId_));
    injectLastBtn_->setEnabled(false);
    beginThinking(QStringLiteral("Injecting overlay into OBS…"));
    http_->postJson(QStringLiteral("/api/inject"), body,
                    [this](const openspark::HttpResult &r) {
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

void OpenSparkDock::onOpenInBrowser()
{
    QDesktopServices::openUrl(QUrl(url_));
}

// --------------------------------------------------------------------------
// Agent chat
// --------------------------------------------------------------------------

void OpenSparkDock::agentAppend(const QString &role, const QString &html)
{
    if (!agentView_) return;
    QString color = "#e6e8ee";
    QString label = role;
    if (role == "user") { color = "#39ff8a"; label = "you"; }
    else if (role == "assistant") { color = "#9be8ff"; label = "agent"; }
    else if (role == "tool") { color = "#ffb14a"; label = "tool"; }
    else if (role == "error") { color = "#ff5470"; label = "error"; }
    agentView_->append(
        QStringLiteral(
            "<div style='margin:6px 0'>"
            "<span style='color:%1;font-weight:700;text-transform:uppercase;"
            "font-size:10px;letter-spacing:0.5px'>%2</span><br>"
            "<span style='color:#e6e8ee'>%3</span></div>")
            .arg(color, label, html));
    agentView_->verticalScrollBar()->setValue(
        agentView_->verticalScrollBar()->maximum());
}

void OpenSparkDock::doAgentSend()
{
    const QString text = agentInput_->toPlainText().trimmed();
    if (text.isEmpty()) return;

    agentHistory_ << text;  // store raw user content; role inferred by index
    agentAppend(QStringLiteral("user"), text.toHtmlEscaped());
    agentInput_->clear();
    agentSendBtn_->setEnabled(false);
    beginThinking(QStringLiteral("Agent thinking…"));

    // Rebuild the full transcript: even indices = user, odd = assistant.
    QJsonArray msgs;
    for (int i = 0; i < agentHistory_.size(); ++i) {
        QJsonObject m;
        m.insert(QStringLiteral("role"),
                 (i % 2 == 0) ? QStringLiteral("user")
                              : QStringLiteral("assistant"));
        m.insert(QStringLiteral("content"), agentHistory_.at(i));
        msgs.append(m);
    }
    QJsonObject body;
    body.insert(QStringLiteral("messages"), msgs);
    body.insert(QStringLiteral("dry_run"), agentDryRun_->isChecked());

    // Stream: tool cards appear live as each step finishes instead of
    // after the whole loop.
    http_->postSse(
        QStringLiteral("/api/agent/chat/stream"),
        QJsonDocument(body).toJson(QJsonDocument::Compact),
        // onEvent(name, dataJson)
        [this](const QString &ev, const QByteArray &data) {
            const auto o = QJsonDocument::fromJson(data).object();
            if (ev == QStringLiteral("step")) {
                const QString tool = o.value("tool").toString();
                const bool exec = o.value("executed").toBool();
                const QString badge = exec ? QStringLiteral("✓ ran")
                                           : QStringLiteral("⏸ skipped");
                const QString args = QString::fromUtf8(
                    QJsonDocument(o.value("args").toObject())
                        .toJson(QJsonDocument::Compact));
                // If a tool produced an overlay URL, surface it as a
                // clickable link (preview in browser).
                QString extra;
                const auto res = o.value("result").toObject();
                const QString url = res.value("url").toString();
                if (!url.isEmpty()) {
                    extra = QStringLiteral(
                        " <a href='%1' style='color:#39ff8a'>preview</a>")
                        .arg(url);
                }
                agentAppend(
                    QStringLiteral("tool"),
                    QStringLiteral("<code>%1</code> %2 "
                                   "<span style='color:#8a8f9c'>%3</span>%4")
                        .arg(tool.toHtmlEscaped(), badge,
                             args.toHtmlEscaped(), extra));
            } else if (ev == QStringLiteral("final")) {
                const auto pending =
                    o.value("pending_confirmation").toArray();
                if (!pending.isEmpty()) {
                    QString lines;
                    for (const auto &pv : pending) {
                        const auto p = pv.toObject();
                        const QString t = p.value("tool").toString();
                        const QString a = QString::fromUtf8(
                            QJsonDocument(p.value("args").toObject())
                                .toJson(QJsonDocument::Compact));
                        lines += QStringLiteral(
                            "<br>&nbsp;&nbsp;• <code>%1</code> "
                            "<span style='color:#8a8f9c'>%2</span>")
                            .arg(t.toHtmlEscaped(), a.toHtmlEscaped());
                    }
                    agentAppend(
                        QStringLiteral("tool"),
                        QStringLiteral(
                            "%1 destructive action(s) need confirmation. "
                            "Review the exact target(s), then UNCHECK "
                            "Dry-run and resend to apply:%2")
                            .arg(pending.size())
                            .arg(lines));
                }
                agentLastCreatedInputs_.clear();
                for (const auto &iv : o.value("created_inputs").toArray()) {
                    agentLastCreatedInputs_ << iv.toString();
                }
                agentUndoBtn_->setEnabled(!agentLastCreatedInputs_.isEmpty());

                const QString fin = o.value("final_message").toString();
                agentHistory_ << fin;  // odd index = assistant next send
                agentAppend(QStringLiteral("assistant"),
                            fin.toHtmlEscaped());
            } else if (ev == QStringLiteral("error")) {
                agentAppend(QStringLiteral("error"),
                            o.value("error").toString().toHtmlEscaped());
            }
        },
        // onDone(error)
        [this](const QString &err) {
            endThinking();
            agentSendBtn_->setEnabled(true);
            if (!err.isEmpty()) {
                agentAppend(QStringLiteral("error"), err.toHtmlEscaped());
            }
        });
}

void OpenSparkDock::agentLoadSession()
{
    http_->getJson(
        QStringLiteral("/api/agent/session"),
        [this](const openspark::HttpResult &r) {
            if (!r.ok) return;
            const auto o = QJsonDocument::fromJson(r.body).object();
            const auto msgs = o.value("messages").toArray();
            if (msgs.isEmpty()) return;
            agentHistory_.clear();
            for (const auto &mv : msgs) {
                const auto m = mv.toObject();
                const QString role = m.value("role").toString();
                const QString content = m.value("content").toString();
                if (content.isEmpty()) continue;
                agentHistory_ << content;
                agentAppend(role == QStringLiteral("user")
                                ? QStringLiteral("user")
                                : QStringLiteral("assistant"),
                            content.toHtmlEscaped());
            }
            agentLastCreatedInputs_.clear();
            for (const auto &iv : o.value("created_inputs").toArray()) {
                agentLastCreatedInputs_ << iv.toString();
            }
            agentUndoBtn_->setEnabled(!agentLastCreatedInputs_.isEmpty());
            agentAppend(QStringLiteral("tool"),
                        QStringLiteral("— resumed previous session —"));
        });
}

void OpenSparkDock::agentDoUndo()
{
    if (agentLastCreatedInputs_.isEmpty()) return;
    QJsonArray arr;
    for (const auto &n : agentLastCreatedInputs_) arr.append(n);
    QJsonObject body;
    body.insert(QStringLiteral("inputs"), arr);
    agentUndoBtn_->setEnabled(false);
    beginThinking(QStringLiteral("Undoing…"));
    http_->postJson(
        QStringLiteral("/api/agent/undo"),
        QJsonDocument(body).toJson(QJsonDocument::Compact),
        [this](const openspark::HttpResult &r) {
            endThinking();
            if (r.ok) {
                const auto o = QJsonDocument::fromJson(r.body).object();
                const int n = o.value("removed").toArray().size();
                agentAppend(QStringLiteral("tool"),
                            QStringLiteral("Undid — removed %1 input(s)")
                                .arg(n));
                agentLastCreatedInputs_.clear();
            } else {
                agentAppend(QStringLiteral("error"),
                            QStringLiteral("Undo failed: %1")
                                .arg(QString::fromUtf8(r.body)
                                         .toHtmlEscaped()));
                agentUndoBtn_->setEnabled(true);
            }
        });
}

// --------------------------------------------------------------------------
// C glue
// --------------------------------------------------------------------------

static OpenSparkDock *g_dock_instance = nullptr;
static bool g_dock_added = false;

static void openspark_actually_add_dock()
{
    if (g_dock_added) {
        return;
    }
    auto *dock = new OpenSparkDock(nullptr);
#if LIBOBS_API_VER >= MAKE_SEMANTIC_VERSION(30, 0, 0)
    const bool ok = obs_frontend_add_dock_by_id(
        "open-spark-dock",
        "Open Spark",
        dock);
    if (!ok) {
        blog(LOG_WARNING, "obs_frontend_add_dock_by_id returned false");
        delete dock;
        return;
    }
#else
    auto *wrapper = new QDockWidget("Open Spark");
    wrapper->setObjectName("open-spark-dock");
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
    QDockWidget *dw = main ? main->findChild<QDockWidget *>("open-spark-dock")
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
                     "[obs-open-spark] tabified with %s on right edge",
                     anchor->objectName().toUtf8().constData());
            } else {
                main->addDockWidget(Qt::RightDockWidgetArea, dw);
                blog(LOG_INFO,
                     "[obs-open-spark] attached to right dock area");
            }
            dw->setFloating(false);
        }
        dw->show();
        dw->raise();
    } else {
        blog(LOG_WARNING,
             "[obs-open-spark] could not find QDockWidget post-register");
    }
    blog(LOG_INFO, "[obs-open-spark] dock registered (url=%s)",
         dock->defaultUrl().toUtf8().constData());
}

static void on_frontend_event(enum obs_frontend_event event, void *)
{
    if (event == OBS_FRONTEND_EVENT_FINISHED_LOADING) {
        openspark_actually_add_dock();
        openspark_actions_install();
    }
}

extern "C" bool openspark_dock_register(void)
{
    obs_frontend_add_event_callback(on_frontend_event, nullptr);
    blog(LOG_INFO,
         "[obs-open-spark] queued dock registration for FINISHED_LOADING");
    return true;
}

extern "C" void openspark_dock_unregister(void)
{
    obs_frontend_remove_event_callback(on_frontend_event, nullptr);
    g_dock_instance = nullptr;
}

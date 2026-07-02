#include <sys/resource.h>
#include <unistd.h>

#include <QApplication>
#include <QSurfaceFormat>
#include <QTranslator>

#include "common/swaglog.h"
#include "common/util.h"
#include "system/hardware/hw.h"
#include "selfdrive/ui/qt/qt_window.h"
#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/window.h"

// Qt 5.12.8's qErrnoWarning() emits QtCriticalMsg then calls abort() directly,
// bypassing the fatal-message path. Intercept critical+fatal Wayland messages
// before the unconditional abort() fires and clean-exit so the manager restarts
// us quickly instead of going through the slow abort/crash-handler path.
void waylandAwareMessageHandler(QtMsgType type, const QMessageLogContext &context, const QString &msg) {
  if (type == QtCriticalMsg || type == QtFatalMsg) {
    QByteArray bytes = msg.toUtf8();
    if (bytes.contains("ayland") || bytes.contains("wl_display")) {
      swagLogMessageHandler(type, context, msg);
      LOGE("UI WAYLAND EXIT: %s", bytes.constData());
      _exit(0);  // clean exit; manager restarts us
    }
  }
  swagLogMessageHandler(type, context, msg);
  // Non-Wayland fatal: let Qt abort normally; crash_handler will capture it.
}

int main(int argc, char *argv[]) {
  setpriority(PRIO_PROCESS, 0, -20);

  qInstallMessageHandler(waylandAwareMessageHandler);

  // Triple-buffer the GL backing store. The onroad camera is a QOpenGLWidget, so every
  // frame is composited to the window via composeAndFlush -> EGL DequeueBuffer on the
  // Adreno/Wayland driver. With only 2 buffers that dequeue occasionally deadlocks
  // (main render thread + driver's EglWaylandUpdater both block waiting for a buffer),
  // hanging the UI main thread until the manager watchdog restarts us. A third buffer
  // keeps a free buffer available so the dequeue never has to block.
  {
    QSurfaceFormat fmt = QSurfaceFormat::defaultFormat();
    fmt.setSwapBehavior(QSurfaceFormat::TripleBuffer);
    QSurfaceFormat::setDefaultFormat(fmt);
  }

  initApp(argc, argv);

  QTranslator translator;
  QString translation_file = QString::fromStdString(Params().get("LanguageSetting"));
  if (!translator.load(QString(":/%1").arg(translation_file)) && translation_file.length()) {
    qCritical() << "Failed to load translation file:" << translation_file;
  }

  QApplication a(argc, argv);
  a.installTranslator(&translator);

  MainWindow w;
  setMainWindow(&w);
  a.installEventFilter(&w);

  // Pin the UI to cores 0-3 + 6-7 AFTER startup, i.e. everything EXCEPT the two
  // safety-critical loops: core 4 (card/controlsd, SCHED_FIFO) and core 5 (selfdrived).
  // The UI stays off those so a UI stall can't preempt them, but adding big cores 6-7
  // gives the render + EGL updater threads enough CPU headroom that GL buffers cycle
  // reliably (starved little-core-only rendering widened the DequeueBuffer deadlock
  // window). Done after MainWindow init so restart recovery can still use all cores;
  // the per-second reaffine in UIState::update keeps it pinned thereafter.
  if (!Hardware::PC()) {
    util::set_core_affinity({0, 1, 2, 3, 6, 7});
  }

  return a.exec();
}

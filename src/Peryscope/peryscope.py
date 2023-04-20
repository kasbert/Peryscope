#!/usr/bin/env python3

import sys
import logging
import argparse
from PerytechDsoApi import (
    PerytechDsoApi,
    SampleRate,
    Coupling,
    VoltageDIV,
    Channel,
    TriggerEdge,
    voltages,
    sampleTimeDivider,
)
from time import sleep
import signal
import socket
from enum import Enum

from PyQt5 import QtNetwork
from PyQt5 import (
    QtCore, QtGui, QtWidgets, uic
)
from PyQt5.QtCore import (
    Qt,
    QObject,
    QThread,
    pyqtSignal,
    QPoint,
    QLine,
    QLineF,
    QMutex,
    QWaitCondition,
    QEvent,
)
from PyQt5.QtGui import (
    QKeySequence,
    QPolygon,
    QPen,
    QBrush,
)
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QRadioButton,
    QSlider,
    QAction,
    QCheckBox,
    QSpinBox,
    QSizePolicy,
    QShortcut,
)


class RunMode(Enum):
    Stopped = 0,
    Continuous = 1,
    Waiting = 2,


class DsoData:
    initialized = False
    data = ''
    off = 0
    triggered = False
    i = -1
    error = None


class DsoConfig:
    sampleRate = SampleRate.kS100
    ch1Couple = Coupling.DC
    ch2Couple = Coupling.DC
    ch1VoltageDIV = VoltageDIV.V1
    ch2VoltageDIV = VoltageDIV.V1
    trigChannel = Channel.Ch1
    trigEdge = TriggerEdge.Rising
    ch1TrigVoltage = 10
    ch2TrigVoltage = 10
    trigOffset = 0
    width = 500
    changed = True
    runMode = RunMode.Continuous
    debug = False
    exit = False

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.data = DsoData()
        self.config = DsoConfig()
        self.initGUI()
        self.startWorker()
        self.configChanged()

    def initGUI(self):
        self.setWindowTitle("PeryScope")

        layout = QVBoxLayout()
        bar = self.menuBar()
        file = bar.addMenu("File")
        # file.addAction("New")

        # save = QAction("Save",self)
        # save.setShortcut("Ctrl+S")
        # file.addAction(save)

        # edit = file.addMenu("Edit")
        # edit.addAction("copy")
        # edit.addAction("paste")

        quit = QAction("Quit", self)
        file.addAction(quit)
        file.triggered[QAction].connect(self.close)
        quit.setShortcut(QKeySequence("Ctrl+Q"))

        device = bar.addMenu("Device")
        reset = QAction("Reset", self)
        device.addAction(reset)
        device.triggered[QAction].connect(self.resetDevice)
        reset.setShortcut(QKeySequence("Ctrl+R"))

        layoutTop = QHBoxLayout()

        # self.b1 = QCheckBox("Enable")
        # self.b1.setChecked(self.config.running)
        # self.b1.stateChanged.connect(self.running)
        # layoutTop.addWidget(self.b1)

        self.rm = QComboBox()
        for idx, e in enumerate(RunMode):
            self.rm.addItem(e.name, e)
            if e == self.config.runMode:
                self.rm.setCurrentIndex(idx)
        self.rm.currentIndexChanged.connect(self.runMode)
        # self.rm.grabShortcut(QKeySequence("Key_Return"))
        layoutTop.addWidget(self.rm)

        layoutTop.addWidget(QtWidgets.QLabel('Sample rate'))
        self.sr = QComboBox()
        for idx, e in enumerate(SampleRate):
            self.sr.addItem(e.name, e)
            if e == self.config.sampleRate:
                self.sr.setCurrentIndex(idx)
        self.sr.currentIndexChanged.connect(self.sampleRate)
        layoutTop.addWidget(self.sr)

        layoutTop.addWidget(QtWidgets.QLabel("Status:"))
        self.status = QtWidgets.QLabel('')
        self.status.setMinimumWidth(100)
        layoutTop.addWidget(self.status)
        layoutTop.addStretch()

        self.off = QSpinBox()
        self.off.setMinimum(-200)
        self.off.setMaximum(200)
        self.off.setValue(int(self.config.trigOffset))
        self.off.valueChanged.connect(self.trigOffset)
        layoutTop.addWidget(self.off)

        self.db = QCheckBox("Debug")
        self.db.setChecked(self.config.debug)
        self.db.stateChanged.connect(self.debug)
        layoutTop.addWidget(self.db)

        # self.btn = QPushButton("doit1!", self)
        # self.btn.clicked.connect(self.doIt1)
        # layoutTop.addWidget(self.btn)

        # self.btn2 = QPushButton("doit2!", self)
        # self.btn2.clicked.connect(self.doIt2)
        # layoutTop.addWidget(self.btn2)

        layout.addLayout(layoutTop)

        # Drawing area
        layout1 = QHBoxLayout()

        layout1.setContentsMargins(0, 0, 0, 0)
        layout1.setSpacing(10)
        layout1.addStrut(512)

        self.drawArea = QtWidgets.QLabel()
        self.drawArea.setMinimumWidth(self.config.width)
        self.drawArea.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.drawArea.resize(self.config.width, 512)
        # self.drawArea.setMinimumWidth(500)
        layout1.addWidget(self.drawArea, 1)

        self.markers = QtWidgets.QLabel()
        self.markers.setMinimumWidth(20)
        self.markers.setMaximumWidth(20)
        canvas = QtGui.QPixmap(20, 512)
        canvas.fill(Qt.white)
        self.markers.setPixmap(canvas)
        layout1.addWidget(self.markers, 1)

        # Right bar
        layoutRight = QVBoxLayout()

        layoutRight.addWidget(QtWidgets.QLabel('Channel 1'))

        self.v1 = QComboBox()
        for idx, e in enumerate(VoltageDIV):
            self.v1.addItem(e.name, e)
            if e == self.config.ch1VoltageDIV:
                self.v1.setCurrentIndex(idx)
        self.v1.currentIndexChanged.connect(self.ch1VoltageDIV)
        layoutRight.addWidget(self.v1)

        self.coupling1 = QComboBox()
        for idx, e in enumerate(Coupling):
            self.coupling1.addItem(e.name, e)
            if e == self.config.ch1Couple:
                self.coupling1.setCurrentIndex(idx)
        self.coupling1.currentIndexChanged.connect(self.ch1Couple)
        layoutRight.addWidget(self.coupling1)

        # self.b1 = QRadioButton("Trigger")
        # self.b1.setChecked(True)
        # self.b1.toggled.connect(lambda:self.btnstate(self.b1))
        # layoutRight.addWidget(self.b1)

        # self.tv1 = QSlider(Qt.Horizontal)
        # self.tv1.setMinimum(10)
        # self.tv1.setMaximum(30)
        # self.tv1.setValue(20)
        # self.tv1.setTickPosition(QSlider.TicksBelow)
        # self.tv1.setTickInterval(5)
        # self.tv1.valueChanged.connect(self.ch1TriggerVoltage)
        # layoutRight.addWidget(self.tv1)

        self.tv1 = QSpinBox()
        self.tv1.setMinimum(-127)
        self.tv1.setMaximum(127)
        self.tv1.setValue(int(self.config.ch1TrigVoltage))
        self.tv1.valueChanged.connect(self.ch1TriggerVoltage)
        layoutRight.addWidget(self.tv1)

        layoutRight.addWidget(QtWidgets.QLabel('Channel 2'))

        self.v2 = QComboBox()
        for idx, e in enumerate(VoltageDIV):
            self.v2.addItem(e.name, e)
            if e == self.config.ch2VoltageDIV:
                self.v2.setCurrentIndex(idx)
        self.v2.currentIndexChanged.connect(self.ch2VoltageDIV)
        layoutRight.addWidget(self.v2)

        self.coupling2 = QComboBox()
        for idx, e in enumerate(Coupling):
            self.coupling2.addItem(e.name, e)
            if e == self.config.ch2Couple:
                self.coupling2.setCurrentIndex(idx)
        self.coupling2.currentIndexChanged.connect(self.ch2Couple)
        layoutRight.addWidget(self.coupling2)

        self.tv2 = QSpinBox()
        self.tv2.setMinimum(-100)
        self.tv2.setMaximum(100)
        self.tv2.setValue(int(self.config.ch2TrigVoltage))
        self.tv2.valueChanged.connect(self.ch2TriggerVoltage)
        layoutRight.addWidget(self.tv2)

        # self.b2 = QRadioButton("Trigger")
        # self.b2.toggled.connect(lambda:self.btnstate(self.b2))
        # layoutRight.addWidget(self.b2)

        layoutRight.addWidget(QtWidgets.QLabel('Trigger'))

        self.te = QComboBox()
        for idx, e in enumerate(TriggerEdge):
            self.te.addItem(e.name, e)
            if e == self.config.trigEdge:
                self.te.setCurrentIndex(idx)
        self.te.currentIndexChanged.connect(self.triggerEdge)
        layoutRight.addWidget(self.te)

        self.tc = QComboBox()
        for idx, e in enumerate(Channel):
            self.tc.addItem(e.name, e)
            if e == self.config.trigChannel:
                self.tc.setCurrentIndex(idx)
        self.tc.currentIndexChanged.connect(self.triggerChannel)
        layoutRight.addWidget(self.tc)

        layoutRight.addStretch()
        layout1.addLayout(layoutRight)
        layout.addLayout(layout1)

        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

        # TODO copy from openHantek
        QShortcut(QKeySequence('Q'), self).activated.connect(self.close)
        QShortcut(QKeySequence('W'), self).activated.connect(
            self.runModeWaiting)
        QShortcut(QKeySequence('C'), self).activated.connect(
            self.runModeContinuous)
        QShortcut(QKeySequence('S'), self).activated.connect(self.runModeStopped)
        QShortcut(QKeySequence('D'), self).activated.connect(self.db.toggle)
        QShortcut(QKeySequence('T'), self).activated.connect(self.rollTrigger1)
        QShortcut(QKeySequence('Shift+T'),
                  self).activated.connect(self.rollTrigger2)
        QShortcut(QKeySequence('1'), self).activated.connect(self.v1.setFocus)
        QShortcut(QKeySequence('2'), self).activated.connect(self.v2.setFocus)

    def runModeWaiting(self):
        if self.config.runMode == RunMode.Waiting:
            self.configChanged()
        else:
            self.rm.setCurrentIndex(RunMode.Waiting.value[0])

    def runModeContinuous(self):
        self.rm.setCurrentIndex(RunMode.Continuous.value[0])

    def runModeStopped(self):
        self.rm.setCurrentIndex(RunMode.Stopped.value[0])

    def rollTrigger1(self):
        self.tc.setCurrentIndex(self.tc.currentIndex(
        ) + 1 if self.tc.currentIndex() < Channel.Ext.value else 0)

    def rollTrigger2(self):
        self.tc.setCurrentIndex(self.tc.currentIndex(
        ) - 1 if self.tc.currentIndex() > 0 else Channel.Ext.value)

    #
    def runMode(self, i):
        self.config.runMode = self.rm.itemData(i)
        self.configChanged()

    def sampleRate(self, i):
        self.config.sampleRate = self.sr.itemData(i)
        self.configChanged()

    def ch1VoltageDIV(self, i):
        self.config.ch1VoltageDIV = self.v1.itemData(i)
        self.configChanged()

    def ch2VoltageDIV(self, i):
        self.config.ch2VoltageDIV = self.v2.itemData(i)
        self.configChanged()

    def ch1Couple(self, i):
        self.config.ch1Couple = self.coupling1.itemData(i)
        self.configChanged()

    def ch2Couple(self, i):
        self.config.ch2Couple = self.coupling2.itemData(i)
        self.configChanged()

    def ch1TriggerVoltage(self, value):
        self.config.ch1TrigVoltage = value
        self.configChanged()

    def ch2TriggerVoltage(self, value):
        self.config.ch2TrigVoltage = value
        self.configChanged()

    def triggerChannel(self, i):
        self.config.trigChannel = self.tc.itemData(i)
        self.configChanged()

    def triggerEdge(self, i):
        self.config.trigEdge = self.te.itemData(i)
        self.configChanged()

    def trigOffset(self, value):
        self.config.trigOffset = value
        self.configChanged()

    # def running(self):
    #    self.config.running = self.b1.isChecked()
    #    self.configChanged()

    def debug(self):
        self.config.debug = self.db.isChecked()
        if self.config.debug:
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)
        self.configChanged()

    def resetDevice(self):
        self.data.initialized = False
        self.configChanged()

    #
    #

    def resizeEvent(self, event):
        logger.debug("Resized, width=", self.drawArea.size().width())
        QtWidgets.QMainWindow.resizeEvent(self, event)
        self.config.width = self.drawArea.size().width()
        self.drawData([])

    # def closeEvent(self, e):
    #    self.config.exit = True
    #    self.configChanged()

    def drawData(self, data):
        # self.drawArea.pixmap().fill()

        canvas = QtGui.QPixmap(self.config.width, 512)
        canvas.fill(Qt.white)

        painter = QtGui.QPainter(canvas)  # self.drawArea.pixmap()

        painter.setPen(QtGui.QPen(Qt.lightGray, 2, Qt.SolidLine))
        painter.drawLine(0, 128, self.config.width, 128)
        painter.drawLine(0, 128 + 256, self.config.width, 128 + 256)
        painter.setPen(QtGui.QPen(Qt.lightGray, 1, Qt.SolidLine))
        i = 0
        while i < 128:
            painter.drawLine(0, int(128+i), self.config.width, int(128+i))
            painter.drawLine(0, int(128-i), self.config.width, int(128-i))
            i += 14 / voltages[self.config.ch1VoltageDIV]
        i = 0
        while i < 128:
            painter.drawLine(0, int(128 + 256+i),
                             self.config.width, int(128 + 256+i))
            painter.drawLine(0, int(128 + 256-i),
                             self.config.width, int(128 + 256-i))
            i += 14 / voltages[self.config.ch2VoltageDIV]

        painter.drawLine(self.data.off, 0, self.data.off, 512)

        x = 0
        x = 1
        lines1 = []
        lines2 = []
        for i in range(2, len(data), 2):
            # for i in range(0, len(data), 2):
            # lines1.append(QPoint(x, 256-data[i]))
            # lines2.append(QPoint(x, 512-data[i+1]))
            lines1.append(QLineF(x-1, 256-data[i-2], x, 256-data[i]))
            lines2.append(QLineF(x-1, 512-data[i-1], x, 512-data[i+1]))
            x += 1
            if x >= self.config.width - 10:
                break
        if len(lines1):
            painter.setPen(QtGui.QPen(Qt.black, 1, Qt.SolidLine))
            # painter.drawLines(*lines1)
            painter.drawLines(lines1)
        if len(lines2):
            painter.setPen(QtGui.QPen(Qt.black, 1, Qt.SolidLine))
            # painter.drawLines(*lines2)
            painter.drawLines(lines2)
        painter.end()
        self.drawArea.setPixmap(canvas)
        # self.drawArea.update()

    def drawMarkers(self):
        self.markers.pixmap().fill()
        painter = QtGui.QPainter(self.markers.pixmap())
        # painter.setPen(QPen(Qt.black, 5, Qt.SolidLine))

        points = QPolygon([
            QPoint(0, 128-self.config.ch1TrigVoltage),
            QPoint(19, 128-self.config.ch1TrigVoltage - 10),
            QPoint(19, 128-self.config.ch1TrigVoltage + 10),
        ])
        if (self.config.trigChannel == Channel.Ch1):
            painter.setBrush(QBrush(Qt.black, Qt.SolidPattern))
        else:
            painter.setBrush(QBrush(Qt.white, Qt.SolidPattern))
        painter.drawPolygon(points)

        points = QPolygon([
            QPoint(0, 384-self.config.ch2TrigVoltage),
            QPoint(19, 384-self.config.ch2TrigVoltage - 10),
            QPoint(19, 384-self.config.ch2TrigVoltage + 10),
        ])
        if (self.config.trigChannel == Channel.Ch2):
            painter.setBrush(QBrush(Qt.black, Qt.SolidPattern))
        else:
            painter.setBrush(QBrush(Qt.white, Qt.SolidPattern))
        painter.drawPolygon(points)

        painter.end()
        self.markers.update()

    def reportProgress(self, i):
        data = self.data.data
        self.drawData(data)
        # Show status
        if self.data.error is not None:
            status = self.data.error
            self.data.error = None
        elif not self.data.initialized:
            status = "Initializing"
        elif self.config.runMode == RunMode.Stopped:
            status = "Stopped"
        elif self.data.triggered:
            status = "Triggered"
        elif self.config.runMode == RunMode.Waiting:
            status = "Waiting"
        else:
            status = "Running"
        self.status.setText(status)
        if self.data.i != i:
            logger.error("Drawing too slow")

    def configChanged(self):
        self.drawMarkers()
        self.config.changed = True
        self.worker.configChanged.wakeAll()

    def startWorker(self):
        self.thread = QThread()
        self.worker = Worker(self.config, self.data)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.reportProgress)
        self.thread.start()

    def cleanup(self):
        self.config.exit = True
        self.thread.quit()
        self.thread.wait()
        # sys.exit(0)


class Worker(QObject):
    progress = pyqtSignal(int)
    mutex = QMutex()
    configChanged = QWaitCondition()

    def __init__(self, config, data):
        super().__init__()
        self.data = data
        self.config = config
        self.dso = PerytechDsoApi()

    def initDevice(self):
        self.sampleRate = None
        self.ch1VoltageDIV = None
        self.ch2VoltageDIV = None
        self.ch1Couple = None
        self.ch2Couple = None
        self.ch1TrigVoltage = None
        self.ch2TrigVoltage = None
        self.trigChannel = None
        self.trigEdge = None

        udevs = self.dso.findDevices()
        self.dso.initDevice(udevs[0], forceInit=True)
        self.dso.show_registers()
        self.data.initialized = True

    def setConfig(self):
        self.dso.setDebug(self.config.debug)
        if self.config.debug:
            self.dso.show_registers()
        if self.sampleRate != self.config.sampleRate:
            self.dso.setSampleRate(self.config.sampleRate)
            self.sampleRate = self.config.sampleRate
        if self.ch1VoltageDIV != self.config.ch1VoltageDIV:
            self.dso.setVoltageDIV(Channel.Ch1, self.config.ch1VoltageDIV)
            self.ch1VoltageDIV = self.config.ch1VoltageDIV
        if self.ch2VoltageDIV != self.config.ch2VoltageDIV:
            self.dso.setVoltageDIV(Channel.Ch2, self.config.ch2VoltageDIV)
            self.ch2VoltageDIV = self.config.ch2VoltageDIV
        if self.ch1Couple != self.config.ch1Couple:
            self.dso.setCh1Couple(self.config.ch1Couple)
            self.ch1Couple = self.config.ch1Couple
        if self.ch2Couple != self.config.ch2Couple:
            self.dso.setCh2Couple(self.config.ch2Couple)
            self.ch2Couple = self.config.ch2Couple
        if self.ch1TrigVoltage != self.config.ch1TrigVoltage:
            self.dso.setTrigVoltage(Channel.Ch1, self.config.ch1TrigVoltage)
            self.ch1TrigVoltage = self.config.ch1TrigVoltage
        if self.ch2TrigVoltage != self.config.ch2TrigVoltage:
            self.dso.setTrigVoltage(Channel.Ch2, self.config.ch2TrigVoltage)
            self.ch2TrigVoltage = self.config.ch2TrigVoltage
        if self.trigChannel != self.config.trigChannel:
            self.dso.setTrigChannel(self.config.trigChannel)
            self.trigChannel = self.config.trigChannel
        if self.trigEdge != self.config.trigEdge:
            self.dso.setTrigEdge(self.config.trigEdge)
            self.trigEdge = self.config.trigEdge
        logger.info("Config set")
        if self.config.debug:
            self.dso.show_registers()

    def waitConfigChange(self):
        while not self.config.exit and not self.config.changed:
            self.mutex.lock()
            try:
                self.configChanged.wait(self.mutex, 1000)
            finally:
                self.mutex.unlock()

    def run(self):
        """Data aquisition task."""
        i = 0
        while not self.config.exit:
            if not self.data.initialized:
                try:
                    self.initDevice()
                    self.config.changed = True
                except Exception as inst:
                    logger.error(inst)
                    self.data.error = str(inst)
                    self.config.changed = False
                self.progress.emit(self.data.i)
            if not self.data.initialized:
                self.waitConfigChange()
                continue
            if self.config.changed:
                self.setConfig()
                self.config.changed = False
                self.progress.emit(self.data.i)
            if self.config.runMode == RunMode.Stopped:
                self.waitConfigChange()
                continue
            # FIXME find a correct offset from registers
            # offset = 902 if self.config.runMode == RunMode.Waiting else 2
            offset = self.config.trigOffset
            # TODO set trigger timeout according to sample rate
            # Or draw partial data
            size = self.config.width if self.config.runMode != RunMode.Waiting else self.config.width + 0x780
            timeout = 1 if self.config.runMode != RunMode.Waiting else 10.0
            data = self.dso.readData(
                size, triggerTimeout=timeout, triggerOffset=offset)
            self.data.triggered = data[1]
            self.data.data = data[0]
            if self.data.triggered and self.config.runMode == RunMode.Waiting:
                # 0x3e6<<1 is just some picked random value
                self.data.data = self.data.data[0x3e6 << 1:]
                pass
            self.data.off = data[2]
            self.data.i = i
            self.progress.emit(i)
            i += 1
            if self.data.triggered and self.config.runMode == RunMode.Waiting:
                # self.data.data = self.data.data[0x380*2:]
                logger.info("Triggered and stopped")
                # self.dso.print_values(self.data.data)
                self.waitConfigChange()
        logger.info("worker exiting")
        self.dso.close()
        logger.info("worker exited")


parser = argparse.ArgumentParser(description='peryscope')
args = parser.parse_args()

logging.basicConfig(encoding='utf-8', level=logging.INFO)
# filename='example.log',
logger = logging.getLogger('peryscope')
logger.setLevel(logging.INFO)


app = QtWidgets.QApplication(sys.argv)
window = MainWindow()
signal.signal(signal.SIGINT, lambda sig, _: window.close())
window.show()
app.exec_()
window.cleanup()

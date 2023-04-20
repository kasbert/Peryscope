
import binascii
import time
import usb1
from datetime import datetime
from struct import pack, unpack
from enum import Enum
from threading import Lock
import logging

logger = logging.getLogger('peryscope')

class Reg(Enum):
    # Read registers
    # ==============

    HELLO = 0x01
    # 0x01 __linkDSO and __dsoInitial: 0x1101

    MAYBE_DEVICE_STATUS = 0x02
    # 0x02 Same as value written to 0x69, __linkDSO and __dsoInitial
    # Maybe some status
    # 1: enabled ?
    # 2: not ok ?
    # 8+1: connect to ground, calibrating ?

    BUFFER_VALUE_03 = 0x03
    # 0x03 Current A/D value

    MAYBE_TRIGGER_COUNT_04 = 0x04
    # 0x04 Amount of data in buffer ?
    # or trigger byte count

    MAYBE_SOME_STATUS = 0x05
    # 0x05 __dsoInitial 0x0008/0x0009/0x000b . Triggered ?
    # 8 ok ?
    # 2 triggered ?
    # 1 data available ?
    # Some status

    MAYBE_BUFFER_COUNT_06 = 0x06
    # 0x06 Buffer counter
    # value = reg(0x04) + 0x03FA, when triggered
    # truncated to 0x1fff (buffer size 0x2000 ?)

    # Write Registers
    # ===============

    UNKNOWN_55 = 0x55
    # 0x55 ???
    # := __get_reg(Reg.MAYBE_BUFFER_COUNT_06) - 0x7d1
    # := __get_reg(Reg.MAYBE_TRIGGER_COUNT_04) - 0x03ea
    # Always after __get_reg Reg.MAYBE_BUFFER_COUNT_06 or MAYBE_TRIGGER_COUNT_04 
    # and before bulk read
    # Calibration ? Skip values ? Trigger offset in buffer ?

    MAYBE_AD_CONTROL = 0x56
    # 0x56 Reset ?
    # 3: logging start
    # 2: freezes the device ;-)
    # 1: reset ?
    # 0: A/D on ?

    TRIG_LEVEL = 0x57
    # 0x57 Trigger value
    # aaaaaaaa bbbbbbbb
    # a ch2
    # b ch1

    # 0x58

    SAMPLE_RATE = 0x59
    # 0x59 Sample rate
    # 0:Reserve
    # 1:1S/s      2:2S/s      3:4S/s
    # 4:10S/s     5:20S/s     6:40S/s
    # 7:100S/s    8:200S/s    9:400S/s
    # 10:1KS/s    11:2KS/s    12:4KS/s
    # 13:10KS/s   14:20KS/s   15:40KS/s
    # 16:100KS/s  17:200KS/s  18:400KS/s
    # 19:1MS/s    20:2MS/s    21:4MS/s
    # 22:10MS/s   23:20MS/s   24:40MS/s
    # 25:100MS/s  26:200MS/s  27:400MS/s
    # 28:1GS/s    29:2GS/s    30:4GS/s

    UNKNOWN_5A = 0x5A
    # 0x5A  __dsoInitial 0x03F8
    # Start calibration ?

    MAYBE_SOME_RESET = 0x5B
    # 0x5B  Reset. Value 1 -> 0

    VOLTAGE_DIV1 = 0x5C
    # 0x5C aaaa bbbb Voltage Div lower part
    # aaaa Channel 2
    # bbbb Channel 1
    # cccc Channel 4 ?
    # dddd Channel 3 ?

    TRIG_CHANNEL = 0x5D
    # 0x5D Trig channel
    #  0:CH1  1:CH2  2:CH3  3:CH4  4:EXT

    TRIG_EDGE = 0x5E
    # 0x5E Trigger edge
    # 0:Rising, 1:Falling

    # 0x5F
    # 0x60

    UNKNOWN_61 = 0x61
    # 0x61 __dsoInitial, set 0

    # 0x62
    # 0x63
    # 0x64
    # 0x65

    VOLTAGE_COUPLING = 0x66
    # 0x66 aa cc dd bb xxxx xxxx Coupling & Voltage
    # a ch1 coupling  10: AC, 01: DC
    # b ch2 coupling  10: AC, 01: DC
    # c ch1 voltage div  10: HIGH (0.1-10V), 01: LOW
    # d ch2 voltage div  10: HIGH (0.1-10V), 01: LOW

    UNKNOWN_67 = 0x67
    # 0x67 __dsoInitial end, set 0

    UNKNOWN_68 = 0x68
    # 0x68 __dsoInitial end, set 3

    MAYBE_DEVICE_CONTROL = 0x69
    # 0x69 xxxx axxb , __linkDSO: set 9, __dsoInitial: set 9 -> 1. Read same from reg 2
    # 8: connect to ground (calibrate ?)

    PERYTECH_MAGIC = 0x6A
    # 0x6A __dsoInitial magic 'PERYTECH'


class SampleRate(Enum):
    S1 = 1
    S2 = 2
    S4 = 3
    S10 = 4
    S20 = 5
    S40 = 6
    S100 = 7
    S200 = 8
    S400 = 9
    kS1 = 10
    kS2 = 11
    kS4 = 12
    kS10 = 13
    kS20 = 14
    kS40 = 15
    kS100 = 16
    kS200 = 17
    kS400 = 18
    MS1 = 19
    MS2 = 20
    MS4 = 21
    MS10 = 22
    MS20 = 23
    MS40 = 24
    MS100 = 25
    MS200 = 26
    MS400 = 27

sampleTimeDivider = {
    # Sampletime = 1.0 / divider
    SampleRate.S1:    1,
    SampleRate.S2:    2,
    SampleRate.S4:    4,
    SampleRate.S10:   10,
    SampleRate.S20:   20,
    SampleRate.S40:   40,
    SampleRate.S100:  100,
    SampleRate.S200:  200,
    SampleRate.S400:  400,
    SampleRate.kS1:   1000,
    SampleRate.kS2:   2000,
    SampleRate.kS4:   4000,
    SampleRate.kS10:  10000,
    SampleRate.kS20:  20000,
    SampleRate.kS40:  40000,
    SampleRate.kS100: 100000,
    SampleRate.kS200: 200000,
    SampleRate.kS400: 400000,
    SampleRate.MS1:   1000000,
    SampleRate.MS2:   2000000,
    SampleRate.MS4:   4000000,
    SampleRate.MS10:  10000000,
    SampleRate.MS20:  20000000,
    SampleRate.MS40:  40000000,
    SampleRate.MS100: 100000000,
    SampleRate.MS200: 200000000,
    SampleRate.MS400: 400000000,
}

class Channel(Enum):
    Ch1 = 0
    Ch2 = 1
    Ch3 = 2
    Ch4 = 3
    Ext = 4

class VoltageDIV(Enum):
    mV10 = 101
    mV20 = 102
    mV50 = 103
    mV100 = 104
    mV200 = 105
    mV500 = 106
    V1 = 107
    V2 = 108
    V5 = 109
    V10 = 110

voltages = {
    VoltageDIV.mV10: 0.010,
    VoltageDIV.mV20: 0.020,
    VoltageDIV.mV50: 0.050,
    VoltageDIV.mV100: 0.100,
    VoltageDIV.mV200: 0.200,
    VoltageDIV.mV500: 0.500,
    VoltageDIV.V1: 1.0,
    VoltageDIV.V2: 2.0,
    VoltageDIV.V5: 5.0,
    VoltageDIV.V10: 10.0,
}

class TriggerEdge(Enum):
    Rising = 2
    Falling = 1

class Coupling(Enum):
    DC = 0
    AC = 1

#
#
#

class PerytechDsoApi:

    def __init__(self):
        self.b1s = 0x55
        self.b2s = 0x2800
        self.tv1 = 0
        self.tv2 = 0
        self.debug = True
        self.dev = None
        self.lock = Lock()
        pass

    #
    # Public methods
    #

    def findDevices(self, usbcontext=None):
        with self.lock:
                if usbcontext is None:
                        usbcontext = usb1.USBContext()
                logger.debug('Scanning for devices...')
                devices = []
                for udev in usbcontext.getDeviceList(skip_on_error=True):
                        vid = udev.getVendorID()
                        pid = udev.getProductID()
                        if (vid, pid) == (0x23E9, 0x0001):
                                logger.debug('Found device')
                                logger.debug('Bus %03i Device %03i: ID %04x:%04x' % (
                                        udev.getBusNumber(),
                                        udev.getDeviceAddress(),
                                        vid,
                                        pid))
                                devices.append(udev)
                if len(devices) == 0:
                        raise Exception("Failed to find a device")
                return devices

    def initDevice(self, udev, forceInit=True):
        self.dev = udev.open()
        with self.lock:
            self.dev.claimInterface(0)
            self.dev.resetDevice()
            if (forceInit or self.__get_reg(Reg.MAYBE_DEVICE_STATUS) != 1):
                self.__linkDSO()
                self.__dsoInitial()

    def close(self):
        with self.lock:
            if self.dev is not None:
                self.dev.close()

    def setDebug(self, val):
        self.debug = val

    def setSampleRate(self, rate):
        with self.lock:
            logger.info("setSampleRate %s" % rate)
            self.__set_reg(Reg.SAMPLE_RATE, rate.value)

    def setCh1Couple(self, CouplingValue):
        with self.lock:
            logger.info("setCh1Couple %s" % CouplingValue)
            self.__setCh1Couple(CouplingValue)

    def setCh2Couple(self, CouplingValue):
        with self.lock:
            logger.info("setCh2Couple %s" % CouplingValue)
            self.__setCh2Couple(CouplingValue)

    def setVoltageDIV(self, channel, voltageDIV):
        with self.lock:
            logger.info("setVoltageDIV %s %s" % (channel, voltageDIV))
            self.__setVoltageDIV(channel, voltageDIV)

    def setTrigChannel(self, channel):
        with self.lock:
            logger.info("setTrigChannel %s" % (channel))
            self.__set_reg(Reg.TRIG_CHANNEL, channel.value)

    def setTrigVoltage(self, channel, trigVoltage):
        with self.lock:
            logger.info("setTrigVoltage %s %+2.2f" % (channel, trigVoltage))
            self.__setTrigVoltage(channel, trigVoltage)

    def setTrigEdge(self, edge):
        with self.lock:
            logger.info("setTrigEdge %s" % (edge))
            self.__set_reg(Reg.TRIG_EDGE, edge.value)
            self.__set_reg(Reg.TRIG_LEVEL, self.tv1 | (self.tv2 << 8))

    #
    # Reading data
    #

    def readData(self, size, triggerTimeout=0.1, triggerOffset=0):
        # Write register twice ?
        self.__controlWrite83(b"\x5A")
        self.__data_bulk_write(b"\xF8\x03")
        self.__data_bulk_write(b"\xF8\x03")
        self.__set_reg(Reg.MAYBE_SOME_RESET, 0x0001)
        self.__set_reg(Reg.MAYBE_SOME_RESET, 0x0000)
        self.__set_reg(Reg.MAYBE_AD_CONTROL, 0x0001)

        # Status goes 0x08 -> 0x09 -> 0x0b
        """
                0x1101 0x0001 0x91ad 0x0000 0x0008 0x0000
                0x1101 0x0001 0x91ae 0x0404 0x0009 0x07fe
                0x1101 0x0001 0x91ae 0x0404 0x000b 0x07fe
                DATA b'ae91ae90ae90ad8fad8fae8eae8eae8dae8eae8dad8dae8dae8dad8dae8cae'
                """
        timeout = time.time() + triggerTimeout
        while True:
            regs = self.__getStatusRegisters()
            if self.debug:
                    self.showRegisters(regs)
            triggered = (regs[Reg.MAYBE_SOME_STATUS.value] == 0x0b)
            if triggered or time.time() > timeout:
                break

        self.__set_reg(Reg.MAYBE_AD_CONTROL, 0x0000)
        val = self.__get_reg(Reg.MAYBE_TRIGGER_COUNT_04)
        # TODO What is  0x03EA
        self.__set_reg(Reg.UNKNOWN_55, (val - 0x03EA + triggerOffset) & 0xffff)
        #self.__set_reg(Reg.UNKNOWN_55, 0x0003)

        self.__controlWrite83(b"\x03")

        b = size << 1
        buff = bytearray()
        while b > 0:
            # self.controlWrite(0x40, 0x04, 0x0082, 0x0000, b"\x00\x00\x82\x00\x00\x02\x00\x00")
            # self.controlWrite(0x40, 0x04, 0x0082, 0x0000, pack("<BBBBHBB", 0x00,0x00,0x82,0x00, min(b, 0x0200), 0x00,0x00))
            data = self.__data_bulk_read(min(b, 0x0200))
            # logger.debug('DATA', b, len(buff), len(data), binascii.hexlify(data[0:31]))
            buff += data
            b -= len(data)

        logger.debug('DATA %s [%d] %s', ("TRIG" if triggered else "NO TRIG"), len(buff), binascii.hexlify(buff[0:31]))
        return (buff, triggered, triggerOffset*-1, regs)

    def readData2(self, size=2000, triggerTimeout=0.1):
        with self.lock:
            logger.debug('readData2')
            self.controlWrite(0x40, 0x0C, 0x008C, 0x000F, b"\x01")
            self.__set_reg(Reg.MAYBE_SOME_RESET, 0x0001)
            self.__set_reg(Reg.MAYBE_SOME_RESET, 0x0000)
            self.__set_reg(Reg.MAYBE_AD_CONTROL, 0x0003)
            # time.sleep(0.411)
            timeout = time.time() + triggerTimeout
            while True:
                val = self.__get_reg(Reg.MAYBE_SOME_STATUS)
                triggered = (val == 0x0b)
                if triggered or time.time() > timeout:
                    break
            self.__controlWrite83(b"\x03")
            data = self.__data_bulk_read(size)
            logger.debug('DATA %d [%d] %s', triggered, len(data), binascii.hexlify(data[0:31]))
            return (data, triggered)

    def readData3(self, size=2000):
        with self.lock:
            #self.__controlWrite83(b"\x03")
            data = self.__data_bulk_read(size)
            logger.debug('DATA [%d] %s', len(data), binascii.hexlify(data[0:31]))
            return (data, False)

    """
        def CalMaxValue(self):
                pass
        #DLLEXPORT double CalMaxValue(double *data, int DataCount);
        #// Calculate the maximum value in the buffer
        def CalMinValue(self):
                pass
        #DLLEXPORT double CalMinValue(double *data, int DataCount);
        #// Calculate the Minimum value in the buffer
        def CalPeak2Peak(self):
                pass
        #DLLEXPORT double CalPeak2Peak(double *data, int DataCount);
        #// Calculate the Peak to Peak in the buffer
        def CalPeriod(self):
                pass
        #DLLEXPORT double CalPeriod(double *data, int DataCount);
        #// Calculate the Period in the buffer
        def CalFrequency(self):
                pass
        #DLLEXPORT double CalFrequency(double *data, int DataCount);
        #// Calculate the Frequency in the buffer
        def CalRMS(self):
                pass
        #DLLEXPORT double CalRMS(double *data, int DataCount);
        #// Calculate the RMS value in the buffer
        def CalAverage(self):
                pass
        #DLLEXPORT double CalAverage(double *data, int DataCount);
        #// Calculate the Average value in the buffer
        def CalDutyCycle(self):
                pass
        #DLLEXPORT double CalDutyCycle(double *data, int DataCount);
        #// Calculate the Duty Cycle in the buffer
        """

    def getRegister(self, addr):
        with self.lock:
            return self.__get_reg(addr)

    #
    # Internal methods
    #

    def bulkRead(self, endpoint, length, timeout=None):
        return self.dev.bulkRead(endpoint, length, timeout=(1000 if timeout is None else timeout))

    def bulkWrite(self, endpoint, data, timeout=None):
        self.dev.bulkWrite(endpoint, data, timeout=(
            1000 if timeout is None else timeout))

    def controlRead(self, bRequestType, bRequest, wValue, wIndex, wLength,
                    timeout=None):
        return self.dev.controlRead(bRequestType, bRequest, wValue, wIndex, wLength,
                                    timeout=(1000 if timeout is None else timeout))

    def controlWrite(self, bRequestType, bRequest, wValue, wIndex, data,
                     timeout=None):
        self.dev.controlWrite(bRequestType, bRequest, wValue, wIndex, data,
                              timeout=(1000 if timeout is None else timeout))

    def interruptRead(self, endpoint, size, timeout=None):
        return self.dev.interruptRead(endpoint, size,
                                      timeout=(1000 if timeout is None else timeout))

    def interruptWrite(self, endpoint, data, timeout=None):
        self.dev.interruptWrite(endpoint, data, timeout=(
            1000 if timeout is None else timeout))

    #

    def __controlWrite8B(self, data, timeout=None):
        for d in data:
            self.controlWrite(0x40, 0x0C, 0x008B,  0x0000,
                              pack('B', d), timeout)

    def __controlWrite89(self, data):
        self.controlWrite(0x40, 0x0C, 0x0089, 0x0000, data)

    def __controlWrite83(self, data):
        self.controlWrite(0x40, 0x0C, 0x0083, 0x0000, data)

    def __data_bulk_read(self, size):
        self.controlWrite(0x40, 0x04, 0x0082, 0x0000, pack(
            "<BBBBHBB", 0x00, 0x00, 0x82, 0x00, size, 0x00, 0x00))
        # controlWrite(0x40, 0x04, 0x0082, 0x0000, b"\x00\x00\x82\x00\x02\x00\x00\x00" )
        # controlWrite(0x40, 0x04, 0x0082, 0x0000, b"\x00\x00\x82\x00\x00\x02\x00\x00")
        buff = self.bulkRead(0x81, size)
        # buff = bulkRead(0x81, 0x0002)
        # buff = bulkRead(0x81, 0x0200)
        return buff

    def __data_bulk_write(self, data):
        size = 2
        self.controlWrite(0x40, 0x04, 0x0082, 0x0000, pack(
            "<BBBBHBB", 0x01, 0x00, 0x82, 0x00, size, 0x00, 0x00))
        self.bulkWrite(0x02, data)  # b"\x01\x00"

    def __set_reg(self, addr, data):
        if not isinstance(addr, int):
            addr = addr.value
        if isinstance(data, (bytes, bytearray)):
            data = unpack('H', data)[0]
        logger.debug("Set register 0x%x : 0x%04x" % (addr, data))
        self.__controlWrite83(pack('B', addr))
        self.__data_bulk_write(pack('H', data))

    def __get_reg(self, addr, expected=None, comment=''):
        if not isinstance(addr, int):
            addr = addr.value
        if isinstance(expected, (bytes, bytearray)):
            expected = unpack('H', expected)[0]
        self.__controlWrite83(pack('B', addr))
        data = self.__data_bulk_read(2)
        data = unpack('H', data)[0]
        if expected is not None and data != expected:
            logger.error("Get register 0x%2x : 0x%04x != expected 0x%04x" %
                  (addr, data, expected))
        else:
            logger.debug("Get register 0x%2x : 0x%04x" % (addr, data))
        return data

    def __getStatusRegisters(self):
            values = [0]
            for addr in range(1, 7):
                self.__controlWrite83(pack('B', addr))
                data = self.__data_bulk_read(2)
                data = unpack('H', data)[0]
                values.append(data)
            return values

    def __setCh1Couple(self, CouplingValue):
        b = 0x8000 if CouplingValue == Coupling.AC else 0x4000
        self.__set_couple_div(b)

    def __setCh2Couple(self, CouplingValue):
        b = 0x0200 if CouplingValue == Coupling.AC else 0x0100
        self.__set_couple_div(b)

    def __setVoltageDIV(self, channel, voltageDIV):
        if (voltageDIV.value < VoltageDIV.mV100.value):
            b1 = voltageDIV.value
            b2 = 0x01
        else:
            b1 = voltageDIV.value - VoltageDIV.mV100.value
            b2 = 0x02
        if channel == Channel.Ch2:
            self.b1s &= 0x0f
            self.b1s |= b1 << 4
            self.b2s &= 0b1111001111111111
            self.b2s |= b2 << 10
        elif channel == Channel.Ch1:
            self.b1s &= 0xf0
            self.b1s |= b1
            self.b2s &= 0b1100111111111111
            self.b2s |= b2 << 12
        else:
            raise "Invalid channel: " + str(channel)
            # TODO other channels ?
        self.__set_reg(Reg.VOLTAGE_DIV1, self.b1s)
        self.__set_couple_div(self.b2s)

    def __setTrigVoltage(self, channel, trigVoltage):
        if channel == Channel.Ch1:
            self.tv1 = int(trigVoltage) + 0x80
        if channel == Channel.Ch2:
            self.tv2 = int(trigVoltage) + 0x80
        self.__set_reg(Reg.TRIG_LEVEL, self.tv1 | (self.tv2 << 8))

    def __set_couple_div(self, val):
        self.__set_reg(Reg.MAYBE_AD_CONTROL, 0x0000)
        self.__set_reg(Reg.VOLTAGE_COUPLING, val)
        self.__set_reg(Reg.VOLTAGE_COUPLING, val)
        self.__set_reg(Reg.VOLTAGE_COUPLING, 0x0000)
        self.__set_reg(Reg.MAYBE_SOME_RESET, 0x0001)
        self.__set_reg(Reg.MAYBE_SOME_RESET, 0x0000)
        self.__set_reg(Reg.MAYBE_AD_CONTROL, 0x0001)

    # Init code

    def __linkDSO(self):
        # with self.lock:
        logger.info('__linkDSO init')

        self.__link_init_seq()

        val = self.__get_reg(Reg.HELLO, 0x1101)
        val = self.__get_reg(Reg.MAYBE_DEVICE_STATUS, 0x0001)
        self.__set_reg(Reg.MAYBE_DEVICE_CONTROL, 0x0001)
        val = self.__get_reg(Reg.MAYBE_DEVICE_STATUS, 0x0001)

        self.__set_reg(Reg.MAYBE_DEVICE_CONTROL, 0x0001)

        self.__set_reg(Reg.TRIG_CHANNEL, Channel.Ext.value)
        # __set_reg(Reg.TRIG_CHANNEL, 0x0004)

        self.__set_reg(Reg.SAMPLE_RATE, SampleRate.kS100.value)
        # __set_reg(Reg.SAMPLE_RATE, 0x0016)

        self.__set_reg(Reg.MAYBE_SOME_RESET, 0x0001)
        self.__set_reg(Reg.MAYBE_SOME_RESET, 0x0000)
        self.__set_reg(Reg.MAYBE_AD_CONTROL, 0x0001)

        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        val = self.__get_reg(Reg.MAYBE_SOME_STATUS, 0x0008)
        self.__set_reg(Reg.MAYBE_AD_CONTROL, 0x0000)

        val = self.__get_reg(Reg.MAYBE_DEVICE_STATUS, 0x0001)
        self.__set_reg(Reg.MAYBE_DEVICE_CONTROL, 0x0009)

        # FIXME check status somehow
        logger.info('__linkDSO finish')

    def __dsoInitial(self):
        # with self.lock:
        logger.info('__dsoInitial')

        val = self.__get_reg(Reg.HELLO, 0x1101)
        val = self.__get_reg(Reg.MAYBE_DEVICE_STATUS, 0x0009)
        self.__set_reg(Reg.MAYBE_DEVICE_CONTROL, 0x0009)
        val = self.__get_reg(Reg.MAYBE_DEVICE_STATUS, 0x0009)
        self.__set_reg(Reg.MAYBE_DEVICE_CONTROL, 0x0009)

        self.__dso_init_seq1()

        self.__set_reg(Reg.PERYTECH_MAGIC, 0x0050)  # P
        self.__data_bulk_write(b"\x45\x00")  # E
        self.__data_bulk_write(b"\x52\x00")  # R
        self.__data_bulk_write(b"\x59\x00")  # Y
        self.__data_bulk_write(b"\x54\x00")  # T
        self.__data_bulk_write(b"\x45\x00")  # E
        self.__data_bulk_write(b"\x43\x00")  # C
        self.__data_bulk_write(b"\x48\x00")  # H

        # Some self.init ?
        self.__set_reg(Reg.UNKNOWN_61, 0x0000)

        val = self.__get_reg(Reg.MAYBE_DEVICE_STATUS, 0x0009)
        self.__set_reg(Reg.MAYBE_DEVICE_CONTROL, 0x0009)
        val = self.__get_reg(Reg.MAYBE_DEVICE_STATUS, 0x0009)
        self.__set_reg(Reg.MAYBE_DEVICE_CONTROL, 0x0009)

        self.__set_reg(Reg.SAMPLE_RATE, SampleRate.MS200.value)
        # __set_reg(Reg.SAMPLE_RATE, 0x001A)

        self.__dso_init_seq2()

        self.__setCh1Couple(Coupling.AC)
        # __set_couple_div(b"\x00\x80")

        self.__setCh2Couple(Coupling.AC)
        # __set_couple_div(b"\x00\x02")

        self.__set_reg(Reg.TRIG_CHANNEL, Channel.Ch1.value)
        # __set_reg(Reg.TRIG_CHANNEL, 0x0000)
        # setTrigVoltage(...)
        self.__set_reg(Reg.TRIG_LEVEL, 0x0095)

        self.__set_reg(Reg.UNKNOWN_5A, 0x03F8)

        for v in [VoltageDIV.mV10, VoltageDIV.mV20, VoltageDIV.mV50, VoltageDIV.mV100,
                  VoltageDIV.mV200, VoltageDIV.mV500, VoltageDIV.V1, VoltageDIV.V5, VoltageDIV.V10]:
            # FIXME calibration ??
            self.__setVoltageDIV(Channel.Ch1, v)
            self.__setVoltageDIV(Channel.Ch2, v)

            self.__set_reg(Reg.MAYBE_SOME_RESET, 0x0001)
            self.__set_reg(Reg.MAYBE_SOME_RESET, 0x0000)
            self.__set_reg(Reg.MAYBE_AD_CONTROL, 0x0001)

            time.sleep(0.064)
            self.__set_reg(Reg.MAYBE_AD_CONTROL, 0x0000)
            val = self.__get_reg(Reg.MAYBE_BUFFER_COUNT_06)
            self.showRegisters(self.__getStatusRegisters())

            #logger.debug("VALUE %04x", val)
            # TODO what is this ?
            self.__set_reg(Reg.UNKNOWN_55, (val - 0x07d1) & 0xffff)
            # __set_reg(Reg.UNKNOWN_55, 0x1547)
            self.__controlWrite83(b"\x03")
            b = 2000
            while b > 0:
                data = self.__data_bulk_read(min(b, 0x0200))
                if b == 2000:
                    logger.info('DATA %s', binascii.hexlify(data[0:31]))
                b -= 0x200

        self.__setCh1Couple(Coupling.DC)
        # __set_couple_div(b"\x00\x40")

        self.__setCh2Couple(Coupling.DC)
        # ?? TYPO
        # __set_couple_div(b"\x01\x00")

        self.__dso_init_seq2()

        self.__set_reg(Reg.UNKNOWN_67, 0x0000)
        self.__data_bulk_write(b"\x00\x00")

        # Some self.init end ?
        self.__set_reg(Reg.UNKNOWN_68, 0x0003)

        val = self.__get_reg(Reg.MAYBE_DEVICE_STATUS, 0x0009)
        self.__set_reg(Reg.MAYBE_DEVICE_CONTROL, 0x0001)
        val = self.__get_reg(Reg.MAYBE_DEVICE_STATUS, 0x0001)
        self.__set_reg(Reg.MAYBE_DEVICE_CONTROL, 0x0001)

        self.__set_reg(Reg.TRIG_CHANNEL, Channel.Ch1.value)
        # __set_reg(Reg.TRIG_CHANNEL, 0x0000)

        logger.info('__dsoInitial finish')
    #

    def showRegisters(self, values):
        vals = []
        for data in values[1:]:
            vals.append("0x%04x" % data)
        logger.info(" ".join(vals))

    def show_registers(self):
        with self.lock:
                self.showRegisters(self.__getStatusRegisters())

    def validate_read(self, expected, actual):
        if expected != actual:
                if len(expected) > 32:
                        xexpected = expected[0:32]
                else:
                        xexpected = expected
                if len(actual) > 32:
                        xactual = actual[0:32]
                else:
                        xactual = actual
                print('Failed %d %d' % (len(expected), len(actual)))
                print('  Expected; %s' % binascii.hexlify(xexpected,))
                print('  Actual:   %s' % binascii.hexlify(xactual,))
                # raise Exception('failed validate: %s' % msg)

    def print_values(self, values):
        c = 0
        found = False
        print("Channel 1")
        for i in range(len(values) >> 1):
            val = values[i*2]
            val = ((val-128))/1.0
            if not found and val < 10:
                continue
            found=True

            if c <= 100000:
                if (c % 10 == 0):
                    print("%4d: " % i, end='')
                print("%+7.2f " % val, end='')
                if (c % 10 == 9):
                    print()
            c += 1

        c = 0
        print("Channel 2")
        for i in range(len(values) >> 1):
            val = values[i*2+1]
            c += 1
            val = ((val-128))/1.0
            if c <= 100:
                print("%+7.2f " % val, end='')
                if (c % 10 == 0):
                    print()

    #

    def __get_status(self):
        return self.controlRead(0xC0, 0x0C, 0x008A, 0x0000, 1)

    def __check_status(self, st):
        for s in st:
            self.__controlWrite8B(b"\x03" b"\x01")
            buff = self.__get_status()
            self.validate_read(pack('B', s), buff)

    # I have no idea what are these. Some FPGA init code ?

    def __init_seq_1(self):
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01")

    def __init_seq_2(self):
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01")

    def __check_seq_2(self):
        self.__check_status(
            b"\x71" b"\x71" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x79" b"\x79")

    def __init_seq_3(self):
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01")

    def __check_seq_34(self):
        self.__check_status(
            b"\x71" b"\x71" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x71" b"\x71" b"\x79" b"\x71")

    def __init_seq_4(self):
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01")

    def __init_seq_5(self):
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01")

    def __check_seq_5(self):
        self.__check_status(
            b"\x71" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71")

    def __init_seq_6(self):
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01")

    def __check_seq_6(self):
        self.__check_status(
            b"\x71" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x79")

    def __init_seq_7(self):
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01")

    def __check_seq_78(self):
        self.__check_status(
            b"\x71" b"\x71" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71")

    def __init_seq_8(self):
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01")

    def __init_seq_9(self):
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01")

    def __check_seq_9(self):
        self.__check_status(
            b"\x71" b"\x71" b"\x79" b"\x79" b"\x71" b"\x71" b"\x79" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79")

    def __link_init_seq(self):
        self.__init_seq_1()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_2()
        self.__check_seq_2()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_3()
        self.__check_seq_34()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_4()
        self.__check_seq_34()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_5()
        self.__check_seq_5()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_6()
        self.__check_seq_6()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_7()
        self.__check_seq_78()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_8()
        self.__check_seq_78()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_9()
        self.__check_seq_9()

        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01")
        self.__check_status(
            b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01")
        self.__check_status(
            b"\x79" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x71" b"\x79" b"\x71" b"\x79" b"\x79")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01")
        self.__check_status(
            b"\x79" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x79" b"\x79" b"\x71")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01")
        self.__check_status(
            b"\x79" b"\x71" b"\x79" b"\x79" b"\x71" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79")

        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_1()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")

    def __dso_init_seq1(self):
        self.__init_seq_1()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_1()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_2()
        self.__check_seq_2()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_1()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_1()

        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01")
        self.__check_status(
            b"\x79" b"\x71" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01")
        self.__check_status(
            b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x79" b"\x79")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01")
        self.__check_status(
            b"\x79" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x79" b"\x79" b"\x71" b"\x79")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01")
        self.__check_status(
            b"\x79" b"\x79" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x71")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01")
        self.__check_status(
            b"\x71" b"\x79" b"\x71" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01")
        self.__check_status(
            b"\x79" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01")
        self.__check_status(
            b"\x79" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01")
        self.__check_status(
            b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x71" b"\x79" b"\x79" b"\x71")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01")
        self.__check_status(
            b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x79" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01")
        self.__check_status(
            b"\x71" b"\x79" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79" b"\x79" b"\x71" b"\x79")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01")
        self.__check_status(
            b"\x71" b"\x79" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71" b"\x79" b"\x71")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01")
        self.__check_status(
            b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x71" b"\x71" b"\x71" b"\x71" b"\x71" b"\x79" b"\x79" b"\x79" b"\x71")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x01")
        self.__check_status(
            b"\x79" b"\x71" b"\x79" b"\x79" b"\x71" b"\x79" b"\x71" b"\x71" b"\x71" b"\x79" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79" b"\x79")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x05" b"\x07" b"\x01")
        self.__check_status(
            b"\x71" b"\x79" b"\x71" b"\x79" b"\x71" b"\x71" b"\x79" b"\x71" b"\x79" b"\x79" b"\x79" b"\x79" b"\x71" b"\x79" b"\x71" b"\x71")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_1()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_1()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x07")
        self.__controlWrite8B(
            b"\x00" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01" b"\x03" b"\x01" b"\x03" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x05" b"\x07" b"\x01")
        self.__check_status(
            b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79" b"\x79")

        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_1()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")

    def __dso_init_seq2(self):
        self.__init_seq_1()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_2()
        self.__check_seq_2()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_3()
        self.__check_seq_34()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_4()
        self.__check_seq_34()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_5()
        self.__check_seq_5()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_6()
        self.__check_seq_6()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_7()
        self.__check_seq_78()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_8()
        self.__check_seq_78()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_9()
        self.__check_seq_9()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")
        self.__init_seq_1()
        self.__controlWrite8B(b"\x00")
        self.__controlWrite89(b"\x00")

    #
    #
    #
    #

if __name__ == "__main__":
    import argparse

    logging.basicConfig(encoding='utf-8', level=logging.DEBUG)

    parser = argparse.ArgumentParser(description='DsoUserApi')
    args = parser.parse_args()

    dso = PerytechDsoApi()
    udevs = dso.findDevices()
    dso.initDevice(udevs[0])

    dso.show_registers()
    dso.setCh1Couple(Coupling.DC)
    dso.show_registers()
    dso.setCh2Couple(Coupling.DC)
    dso.show_registers()
    dso.setSampleRate(SampleRate.kS100)
    dso.show_registers()
    dso.setVoltageDIV(Channel.Ch1, VoltageDIV.V1)
    dso.show_registers()
    dso.setVoltageDIV(Channel.Ch2, VoltageDIV.V1)
    dso.show_registers()
    d = dso.readData(2000)
    dso.show_registers()
    dso.print_values(d[0])

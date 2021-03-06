import os
import sys

import DAQmxUtility as dutil
import DigitalOutput as do


sys.path.insert(0, os.path.abspath('..'))

test = do.DigitalOutput()
physicalChannel = 'PXI1Slot3/port0/line0:7'

#################### Static Mode ####################
print("Starting Static Mode...")
test.mode = dutil.Mode.Static
test.samplesPerChannel = 1
test.clkSource = 'PFI6'
testBuffer = test.createTestBuffer()

try:
    test.init(physicalChannel)
    test.writeToBuffer(testBuffer)
    test.start()
    test.waitUntilDone()
    test.stop()
finally:
    test.close()
print("Static Mode Complete.")
    
################### Finite Mode ####################
print("Starting Finite Mode...")
test.mode = dutil.Mode.Finite
test.samplesPerChannel = 8005
#test.clkSource = '/PXI1Slot3/PXI_Trig0'
test.clkSource = '/PXI1Slot3/PXI_Star'
testBuffer = test.createTestBuffer()

try:
    test.init(physicalChannel)
    test.writeToBuffer(testBuffer)
    test.start()
    test.waitUntilDone()
    test.stop()
finally:
    test.close()
print("Finite Mode Complete.")

#################### Continuous Mode ###################
print("Starting Continuous Mode")
test.mode = dutil.Mode.Continuous

try:
    test.init(physicalChannel)
    test.writeToBuffer(testBuffer)
    test.start()
    input('Press enter to continue...')
    test.stop()
finally:
    test.close()

print("Continuous Mode Complete.")

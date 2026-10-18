import serial
import time
import sys

print("Opening port...")
try:
    ser = serial.Serial('/dev/cu.usbserial-0001', 115200, timeout=1.0)
    print("Port opened. Listening for 30 seconds. PRESS YOUR REMOTE BUTTON NOW!")
    
    start_time = time.time()
    while time.time() - start_time < 30:
        line = ser.readline()
        if line:
            print(f"[{time.time()-start_time:.1f}s] RAW: {line}")
            
except Exception as e:
    print(f"Error: {e}")
finally:
    if 'ser' in locals() and ser.is_open:
        ser.close()
    print("Done listening.")

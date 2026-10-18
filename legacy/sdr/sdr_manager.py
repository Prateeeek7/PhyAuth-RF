import time
import threading
import queue
import logging
import numpy as np
from typing import Optional, Callable, Union
from pathlib import Path
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SDRManager")

# Try to import pyrtlsdr, fallback to mock if not available
try:
    from rtlsdr import RtlSdr
    RTL_SDR_AVAILABLE = True
except Exception as e:
    logger.warning(f"pyrtlsdr or librtlsdr not available. Falling back to Simulation Mode. Error: {e}")
    RTL_SDR_AVAILABLE = False

class SDRManager:
    """
    Threaded controller for RTL-SDR device. Handles starting, stopping,
    and streaming IQ samples safely. Supports a simulation mode.
    """
    
    def __init__(self, simulation_mode: bool = False):
        self.simulation_mode = simulation_mode or not RTL_SDR_AVAILABLE
        self.sdr: Optional[RtlSdr] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.sample_rate = 2.048e6
        self.center_freq = 433.92e6
        self.gain: Union[str, float] = "auto"
        
        # Thread-safe queue for acquired samples
        self.sample_queue = queue.Queue(maxsize=100)
        
        # Callbacks for sample consumer
        self.callback: Optional[Callable[[np.ndarray], None]] = None
        
    def configure(self, sample_rate: float, center_freq: float, gain: Union[str, float] = "auto") -> bool:
        """
        Configure SDR settings. Must be called before start().
        """
        self.sample_rate = sample_rate
        self.center_freq = center_freq
        self.gain = gain
        
        if self.simulation_mode:
            logger.info(f"[SIMULATION] Configured mock SDR: Freq={center_freq} Hz, Rate={sample_rate} Hz, Gain={gain}")
            return True
            
        try:
            # Initialize hardware if not already done
            if not self.sdr:
                self.sdr = RtlSdr()
            
            self.sdr.sample_rate = sample_rate
            self.sdr.center_freq = center_freq
            
            if gain == "auto":
                self.sdr.gain = 'auto'
            else:
                self.sdr.gain = float(gain)
                
            logger.info(f"[HARDWARE] Configured RTL-SDR: Freq={self.sdr.center_freq} Hz, Rate={self.sdr.sample_rate} Hz, Gain={self.sdr.gain}")
            return True
        except Exception as e:
            logger.error(f"Failed to configure RTL-SDR hardware: {e}. Switching to Simulation Mode.")
            self.simulation_mode = True
            return True

    def start(self, callback: Callable[[np.ndarray], None] = None) -> bool:
        """
        Start the background sample acquisition thread.
        
        Args:
            callback: Optional function called whenever a new block of samples is read.
        """
        if self.running:
            return True
            
        self.callback = callback
        self.running = True
        
        # Clear out any stale queue entries
        while not self.sample_queue.empty():
            try:
                self.sample_queue.get_nowait()
            except queue.Empty:
                break
                
        if self.simulation_mode:
            self.thread = threading.Thread(target=self._simulation_loop, name="SDRSimThread", daemon=True)
        else:
            self.thread = threading.Thread(target=self._hardware_loop, name="SDRHardwareThread", daemon=True)
            
        self.thread.start()
        logger.info("SDR acquisition thread started.")
        return True

    def stop(self) -> None:
        """
        Stop the acquisition loop and join the thread.
        """
        if not self.running:
            return
            
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
            
        if not self.simulation_mode and self.sdr:
            try:
                # Cancel any pending async reads
                self.sdr.cancel_read_async()
            except Exception as e:
                logger.error(f"Error cancelling async read: {e}")
                
        logger.info("SDR acquisition thread stopped.")

    def close(self) -> None:
        """
        Release hardware resources.
        """
        self.stop()
        if self.sdr:
            try:
                self.sdr.close()
                logger.info("RTL-SDR hardware handle closed.")
            except Exception as e:
                logger.error(f"Error closing RTL-SDR hardware: {e}")
            self.sdr = None

    def _hardware_loop(self) -> None:
        """
        Synchronous loop reading chunks of samples from physical hardware.
        """
        chunk_size = 131072  # 128k samples per read
        
        while self.running:
            try:
                if not self.sdr:
                    break
                # Synchronous read
                samples = self.sdr.read_samples(chunk_size)
                
                # Push to queue or callback
                if self.callback:
                    self.callback(samples)
                else:
                    try:
                        self.sample_queue.put(samples, timeout=0.1)
                    except queue.Full:
                        # Drop oldest sample to prevent memory leaks if consumer stalls
                        try:
                            self.sample_queue.get_nowait()
                        except queue.Empty:
                            pass
                        self.sample_queue.put(samples)
                        
            except Exception as e:
                logger.error(f"Hardware read error: {e}")
                time.sleep(0.1)

    def _simulation_loop(self) -> None:
        """
        Simulation loop generating synthetic signals to simulate an active transmitter.
        """
        chunk_size = 65536
        sleep_time = chunk_size / self.sample_rate
        
        # Simulated devices
        devices = ["DEV_A", "DEV_B", "DEV_C"]
        
        # Pre-generate simulated hardware fingerprint signatures:
        # Each device has a stable CFO offset and IQ imbalance
        fingerprints = {
            "DEV_A": {"cfo": 1420.0, "g": 1.05, "phi": 3.2},
            "DEV_B": {"cfo": -2100.0, "g": 0.96, "phi": -1.8},
            "DEV_C": {"cfo": 500.0, "g": 1.01, "phi": 0.8}
        }
        
        current_dev = "DEV_A"
        time_counter = 0.0
        
        # Simulation generates a burst signal (active transmission packet) every 1.5 seconds
        burst_period = 1.5
        burst_duration = 0.4
        
        while self.running:
            start_time = time.time()
            
            # Decide if currently transmitting
            cycle_time = time_counter % burst_period
            is_transmitting = cycle_time < burst_duration
            
            # Occasionally swap transmitters to simulate different devices in range
            if cycle_time < sleep_time:
                # Cycle devices
                current_dev = devices[int(time_counter / burst_period) % len(devices)]
                
            fp = fingerprints[current_dev]
            
            # Time vector for this chunk
            t = np.arange(chunk_size) / self.sample_rate + time_counter
            
            if is_transmitting:
                # Modulated signal: BPSK/QPSK with device-specific CFO & IQ imbalance
                # Clean carrier + modulation symbols
                clean_sig = np.exp(1j * 2 * np.pi * 100e3 * t)  # 100 kHz modulated tone
                
                # Apply IQ Imbalance
                s_I = np.real(clean_sig)
                s_Q = np.imag(clean_sig)
                phi_rad = np.radians(fp["phi"])
                s_Q_imb = fp["g"] * np.sin(phi_rad) * s_I + fp["g"] * np.cos(phi_rad) * s_Q
                imb_sig = s_I + 1j * s_Q_imb
                
                # Apply CFO
                cfo_rot = np.exp(1j * 2 * np.pi * fp["cfo"] * t)
                sig = imb_sig * cfo_rot
                
                # Scale signal amplitude
                sig = 0.8 * sig
            else:
                # Idle channel: pure noise
                sig = np.zeros(chunk_size, dtype=complex)
                
            # Add AWGN (noise floor)
            noise = (np.random.normal(0, 0.02, chunk_size) + 1j * np.random.normal(0, 0.02, chunk_size))
            chunk = sig + noise
            
            # Stream out
            if self.callback:
                self.callback(chunk)
            else:
                try:
                    self.sample_queue.put(chunk, timeout=0.1)
                except queue.Full:
                    try:
                        self.sample_queue.get_nowait()
                    except queue.Empty:
                        pass
                    self.sample_queue.put(chunk)
                    
            time_counter += sleep_time
            
            # Maintain real-time speed
            elapsed = time.time() - start_time
            sleep_needed = max(0.0, sleep_time - elapsed)
            time.sleep(sleep_needed)

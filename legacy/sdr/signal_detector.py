import numpy as np

def estimate_noise_floor(signal: np.ndarray, window_size: int = 256) -> float:
    """
    Estimate the noise floor of a signal by dividing it into windows
    and taking the median of the average power of those windows.
    This is highly robust to the presence of active signals.
    
    Args:
        signal: 1D complex numpy array of IQ samples.
        window_size: Size of the windows to compute local power.
        
    Returns:
        Estimated noise floor in Watts (linear scale).
    """
    n = len(signal)
    if n < window_size:
        return float(np.mean(np.abs(signal)**2))
        
    num_windows = n // window_size
    powers = []
    for i in range(num_windows):
        win = signal[i*window_size : (i+1)*window_size]
        powers.append(np.mean(np.abs(win)**2))
        
    # Return the median power (in Watts)
    return float(np.median(powers))

def energy_detector(signal: np.ndarray, 
                    sample_rate: float, 
                    threshold_db: float = 10.0, 
                    window_size: int = 128,
                    hold_time_sec: float = 0.001) -> list[tuple[int, int]]:
    """
    Detect active signal regions using energy thresholding with hysteresis/hold time.
    
    Args:
        signal: 1D complex numpy array of IQ samples.
        sample_rate: Sampling rate in Hz.
        threshold_db: Threshold in dB above the estimated noise floor.
        window_size: Window size for calculating local energy.
        hold_time_sec: Minimum duration in seconds to hold the active state 
                       to prevent splitting a single packet due to amplitude drops.
                       
    Returns:
        List of tuples (start_idx, end_idx) indicating active signal regions.
    """
    n = len(signal)
    if n < window_size:
        return []
        
    # 1. Estimate noise floor
    noise_power_linear = estimate_noise_floor(signal, window_size)
    if noise_power_linear == 0:
        noise_power_linear = 1e-12
        
    threshold_linear = noise_power_linear * (10 ** (threshold_db / 10.0))
    
    # 2. Compute sliding power
    # Use convolution for fast moving average of signal power
    power_inst = np.abs(signal) ** 2
    kernel = np.ones(window_size) / window_size
    power_smooth = np.convolve(power_inst, kernel, mode='same')
    
    # 3. Detect active states with hold time
    hold_samples = int(hold_time_sec * sample_rate)
    
    active_regions = []
    is_active = False
    start_idx = 0
    cooldown_counter = 0
    
    for idx, p in enumerate(power_smooth):
        if p > threshold_linear:
            if not is_active:
                is_active = True
                start_idx = idx
            cooldown_counter = hold_samples  # Reset cooldown whenever power is high
        else:
            if is_active:
                cooldown_counter -= 1
                if cooldown_counter <= 0:
                    is_active = False
                    # Store region, adjusting for convolution shift
                    end_idx = idx
                    active_regions.append((max(0, start_idx - window_size//2), min(n, end_idx - window_size//2)))
                    
    # Handle end of signal edge
    if is_active:
        active_regions.append((max(0, start_idx - window_size//2), n))
        
    return active_regions

def detect_transient_cusum(signal: np.ndarray, 
                           threshold: float = 5.0, 
                           drift: float = 0.1) -> int:
    """
    Detect the start of a signal transient using the Cumulative Sum (CUSUM) algorithm
    on the instantaneous signal envelope.
    
    The algorithm monitors the rise in signal envelope amplitude above the noise floor.
    
    Args:
        signal: 1D complex numpy array of IQ samples.
        threshold: The decision threshold (H) for CUSUM. Higher means fewer false alarms.
        drift: The drift parameter (k). Determines the size of the shift in mean we want to detect.
               Typically set based on noise variance.
               
    Returns:
        Index of the estimated transient start, or 0 if no transient is detected.
    """
    envelope = np.abs(signal)
    
    # Estimate noise parameters from the first part of the signal (assumed to be noise/pre-transient)
    # We take the first 100 samples or 10% of the signal, whichever is smaller, to represent the noise floor
    noise_ref_len = min(100, len(signal) // 10)
    if noise_ref_len < 10:
        noise_ref_len = 10
        
    noise_mean = np.mean(envelope[:noise_ref_len])
    noise_std = np.std(envelope[:noise_ref_len])
    if noise_std == 0:
        noise_std = 1e-6
        
    # Normalize the envelope to have 0 mean and unit variance under noise conditions
    norm_envelope = (envelope - noise_mean) / noise_std
    
    # CUSUM accumulation
    S = 0.0
    zero_idx = 0
    
    for idx, val in enumerate(norm_envelope):
        # We look for a positive shift (increase in mean)
        # S_n = max(0, S_{n-1} + x_n - drift)
        term = val - drift
        S += term
        
        if S <= 0:
            S = 0.0
            zero_idx = idx  # Keep track of the last index where CUSUM was reset to 0
            
        if S > threshold:
            # Change detected! The transient start is the point where the sum began accumulating.
            return zero_idx
            
    return 0

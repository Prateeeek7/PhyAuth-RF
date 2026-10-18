import numpy as np

def estimate_cfo_phase_diff(signal: np.ndarray, sample_rate: float) -> float:
    """
    Estimate Carrier Frequency Offset (CFO) using the average phase difference of adjacent samples.
    This is based on Kay's / Fitz's estimator for a single tone or carrier component.
    
    Args:
        signal: 1D complex numpy array of IQ samples.
        sample_rate: Sampling rate in Hz.
        
    Returns:
        Estimated CFO in Hz.
    """
    if len(signal) < 2:
        return 0.0
    
    # Calculate phase of conjugate product of adjacent samples
    # angle(s[n] * conj(s[n-1])) represents the instantaneous frequency
    phase_diffs = np.angle(signal[1:] * np.conj(signal[:-1]))
    
    # Average phase difference
    avg_phase_diff = np.mean(phase_diffs)
    
    # Convert phase difference to frequency: f = delta_phi / (2 * pi * Ts)
    cfo = avg_phase_diff * sample_rate / (2 * np.pi)
    return float(cfo)

def estimate_cfo_spectral_centroid(signal: np.ndarray, sample_rate: float) -> float:
    """
    Estimate CFO using the centroid of the power spectrum (useful for modulated signals).
    
    Args:
        signal: 1D complex numpy array of IQ samples.
        sample_rate: Sampling rate in Hz.
        
    Returns:
        Estimated CFO in Hz.
    """
    n = len(signal)
    if n == 0:
        return 0.0
    
    # Compute FFT and shift center to 0 Hz
    fft_vals = np.fft.fftshift(np.fft.fft(signal))
    freqs = np.fft.fftshift(np.fft.fftfreq(n, d=1.0/sample_rate))
    
    # Power spectral density
    psd = np.abs(fft_vals) ** 2
    psd_sum = np.sum(psd)
    
    if psd_sum == 0:
        return 0.0
    
    # Centroid: sum(freq * power) / sum(power)
    centroid = np.sum(freqs * psd) / psd_sum
    return float(centroid)

def estimate_cfo_mth_power(signal: np.ndarray, sample_rate: float, M: int = 4) -> float:
    """
    Estimate CFO of M-PSK signals (M=2 for BPSK, M=4 for QPSK) using the M-th power spectral peak method.
    By raising the signal to the M-th power, PSK modulation is removed, creating a pure spectral line at M * CFO.
    
    Args:
        signal: 1D complex numpy array of IQ samples.
        sample_rate: Sampling rate in Hz.
        M: Modulation order (e.g. 4 for QPSK).
        
    Returns:
        Estimated CFO in Hz.
    """
    n = len(signal)
    if n == 0:
        return 0.0
        
    # Raise to M-th power to remove modulation
    sig_m = signal ** M
    
    # Compute FFT
    fft_vals = np.fft.fftshift(np.fft.fft(sig_m))
    freqs = np.fft.fftshift(np.fft.fftfreq(n, d=1.0/sample_rate))
    
    # Find peak frequency
    peak_idx = np.argmax(np.abs(fft_vals))
    peak_freq = freqs[peak_idx]
    
    # CFO is peak frequency divided by M
    cfo = peak_freq / M
    return float(cfo)

def estimate_iq_imbalance(signal: np.ndarray) -> tuple[float, float]:
    """
    Estimate amplitude and phase imbalance of a complex baseband signal.
    Assumes the underlying signal is zero-mean and that I and Q branches
    should ideally have equal power and be orthogonal.
    
    Let r_I and r_Q be the real and imaginary parts of the signal.
    Amplitude imbalance (g): g = sqrt(E[r_Q^2] / E[r_I^2])
    Phase imbalance (phi) in radians: sin(phi) = E[r_I * r_Q] / (g * E[r_I^2])
    
    Args:
        signal: 1D complex numpy array of IQ samples.
        
    Returns:
        A tuple of (amplitude_imbalance_g, phase_imbalance_phi_deg)
        - amplitude_imbalance_g: Ratio of Q-power to I-power (ideal is 1.0)
        - phase_imbalance_phi_deg: Deviation from orthogonal 90 deg phase (ideal is 0.0)
    """
    # Remove DC offset first
    r_I = np.real(signal) - np.mean(np.real(signal))
    r_Q = np.imag(signal) - np.mean(np.imag(signal))
    
    var_I = np.mean(r_I ** 2)
    var_Q = np.mean(r_Q ** 2)
    
    if var_I == 0 or var_Q == 0:
        return 1.0, 0.0
    
    # 1. Amplitude imbalance g
    g = np.sqrt(var_Q / var_I)
    
    # 2. Phase imbalance (phi)
    cov_IQ = np.mean(r_I * r_Q)
    sin_phi = cov_IQ / (g * var_I)
    
    # Clip sin_phi to avoid floating point errors out of [-1, 1]
    sin_phi = np.clip(sin_phi, -1.0, 1.0)
    phi = np.arcsin(sin_phi)
    
    # Convert phase imbalance to degrees
    phi_deg = np.degrees(phi)
    
    return float(g), float(phi_deg)

def correct_iq_imbalance(signal: np.ndarray, g: float, phi_deg: float) -> np.ndarray:
    """
    Apply correction for IQ imbalance using the estimated amplitude gain 'g'
    and phase imbalance 'phi' (in degrees).
    
    Gram-Schmidt correction formulas:
    s_I = r_I
    s_Q = (r_Q - g * sin(phi) * r_I) / (g * cos(phi))
    
    Args:
        signal: 1D complex numpy array of imbalanced IQ samples.
        g: Estimated amplitude imbalance.
        phi_deg: Estimated phase imbalance in degrees.
        
    Returns:
        1D complex numpy array of corrected IQ samples.
    """
    r_I = np.real(signal)
    r_Q = np.imag(signal)
    
    phi = np.radians(phi_deg)
    
    s_I = r_I
    denom = g * np.cos(phi)
    if abs(denom) < 1e-6:
        denom = 1e-6 if denom >= 0 else -1e-6
        
    s_Q = (r_Q - g * np.sin(phi) * r_I) / denom
    
    return s_I + 1j * s_Q

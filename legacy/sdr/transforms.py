import numpy as np
from scipy import signal as sp_signal

def compute_fft(iq_samples: np.ndarray, n_fft: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute the Fast Fourier Transform (FFT) of the IQ samples.
    
    Args:
        iq_samples: 1D complex numpy array of IQ samples.
        n_fft: Number of FFT points. If len(iq_samples) is different, 
               it will be padded or truncated.
               
    Returns:
        A tuple of (frequencies_normalized, fft_db)
        - frequencies_normalized: Normalized frequency scale between -0.5 and +0.5.
        - fft_db: FFT magnitude in decibels (log scale), normalized to peak.
    """
    n = len(iq_samples)
    if n == 0:
        return np.array([]), np.array([])
        
    # Apply Hamming window to reduce spectral leakage
    window = np.hamming(min(n, n_fft))
    if n < n_fft:
        # Zero pad signal if it is shorter than n_fft
        windowed_sig = np.zeros(n_fft, dtype=complex)
        windowed_sig[:n] = iq_samples * window
    else:
        windowed_sig = iq_samples[:n_fft] * window
        
    fft_vals = np.fft.fft(windowed_sig, n=n_fft)
    fft_shifted = np.fft.fftshift(fft_vals)
    
    # Compute magnitude in dB
    magnitude = np.abs(fft_shifted)
    # Avoid log of 0
    magnitude = np.maximum(magnitude, 1e-12)
    fft_db = 20 * np.log10(magnitude)
    
    # Normalize peak to 0 dB
    fft_db = fft_db - np.max(fft_db)
    
    # Generate normalized frequencies (-0.5 to 0.5)
    freqs = np.fft.fftshift(np.fft.fftfreq(n_fft))
    
    return freqs, fft_db

def compute_welch_psd(iq_samples: np.ndarray, 
                      sample_rate: float, 
                      nperseg: int = 256, 
                      noverlap: int = 128) -> tuple[np.ndarray, np.ndarray]:
    """
    Estimate the Power Spectral Density (PSD) using Welch's method.
    This provides a smoother spectral representation than a single raw FFT.
    
    Args:
        iq_samples: 1D complex numpy array of IQ samples.
        sample_rate: Sample rate of the receiver.
        nperseg: Length of each segment.
        noverlap: Number of points overlapping between segments.
        
    Returns:
        A tuple of (frequencies, psd_db)
        - frequencies: Frequency values in Hz.
        - psd_db: PSD values in dB/Hz.
    """
    if len(iq_samples) < nperseg:
        nperseg = len(iq_samples)
        noverlap = nperseg // 2
        
    if nperseg <= 0:
        return np.array([]), np.array([])
        
    freqs, psd = sp_signal.welch(iq_samples, 
                                 fs=sample_rate, 
                                 window='hamming', 
                                 nperseg=nperseg, 
                                 noverlap=noverlap, 
                                 scaling='density', 
                                 return_onesided=False)
    
    # Shift to center the spectrum (from 0...fs to -fs/2...fs/2)
    freqs = np.fft.fftshift(freqs)
    psd = np.fft.fftshift(psd)
    
    # Convert to dB
    psd = np.maximum(psd, 1e-18)
    psd_db = 10 * np.log10(psd)
    
    return freqs, psd_db

def compute_spectrogram(iq_samples: np.ndarray, 
                        n_fft: int = 256, 
                        n_overlap: int = 128) -> np.ndarray:
    """
    Compute the Short-Time Fourier Transform (STFT) spectrogram.
    
    Args:
        iq_samples: 1D complex numpy array of IQ samples.
        n_fft: Length of FFT window.
        n_overlap: Overlap between consecutive FFT windows.
        
    Returns:
        2D real-valued numpy array of shape (n_fft, time_steps)
        representing the spectrogram in dB, shifted so that center frequency is in the middle.
    """
    if len(iq_samples) < n_fft:
        # Zero pad signal to at least n_fft length
        padded = np.zeros(n_fft, dtype=complex)
        padded[:len(iq_samples)] = iq_samples
        iq_samples = padded
        
    # Standard STFT using scipy
    _, _, Zxx = sp_signal.stft(iq_samples, 
                              window='hamming', 
                              nperseg=n_fft, 
                              noverlap=n_overlap, 
                              return_onesided=False)
    
    # Shift vertical frequency axis so 0 Hz is centered
    Zxx_shifted = np.fft.fftshift(Zxx, axes=0)
    
    # Calculate magnitude in dB
    spectrogram_db = 20 * np.log10(np.maximum(np.abs(Zxx_shifted), 1e-12))
    
    # Normalize spectrogram values to range [0, 1] or relative to max for neural net convenience
    max_val = np.max(spectrogram_db)
    spectrogram_db = spectrogram_db - max_val  # peak is 0 dB
    
    # Clip low range to -100 dB (standard dynamic range for RF)
    spectrogram_db = np.clip(spectrogram_db, -100.0, 0.0)
    
    # Re-normalize to [0, 1] range: 0.0 is -100dB, 1.0 is 0dB
    normalized_spectrogram = (spectrogram_db + 100.0) / 100.0
    
    return normalized_spectrogram

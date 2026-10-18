import numpy as np
import pytest
from dsp.impairment_estimator import (
    estimate_cfo_phase_diff,
    estimate_cfo_spectral_centroid,
    estimate_cfo_mth_power,
    estimate_iq_imbalance,
    correct_iq_imbalance
)
from dsp.signal_detector import (
    estimate_noise_floor,
    energy_detector,
    detect_transient_cusum
)
from dsp.transforms import (
    compute_fft,
    compute_welch_psd,
    compute_spectrogram
)

def generate_synthetic_signal(
    num_samples: int = 10000,
    sample_rate: float = 2.048e6,
    cfo_hz: float = 0.0,
    iq_gain: float = 1.0,
    iq_phase_deg: float = 0.0,
    snr_db: float = 30.0,
    modulation: str = "qpsk"
) -> np.ndarray:
    """
    Generate a synthetic modulated signal with injected CFO and IQ imbalance.
    """
    t = np.arange(num_samples) / sample_rate
    
    # 1. Generate clean baseband symbols
    if modulation == "qpsk":
        # QPSK symbols: random combination of (+-1 +- j) / sqrt(2)
        symbols = (np.random.choice([-1, 1], num_samples) + 1j * np.random.choice([-1, 1], num_samples)) / np.sqrt(2)
    elif modulation == "sine":
        # Simple single tone
        symbols = np.exp(1j * 2 * np.pi * 50e3 * t) # 50 kHz tone
    else:
        # Dummy noise
        symbols = np.random.normal(0, 1, num_samples) + 1j * np.random.normal(0, 1, num_samples)

    # 2. Inject IQ Imbalance (transmitter side model)
    s_I = np.real(symbols)
    s_Q = np.imag(symbols)
    
    phi_rad = np.radians(iq_phase_deg)
    s_Q_imb = iq_gain * np.sin(phi_rad) * s_I + iq_gain * np.cos(phi_rad) * s_Q
    symbols_imbalanced = s_I + 1j * s_Q_imb

    # 3. Inject Carrier Frequency Offset (CFO)
    cfo_rotator = np.exp(1j * 2 * np.pi * cfo_hz * t)
    signal_cfo = symbols_imbalanced * cfo_rotator

    # 4. Inject Additive White Gaussian Noise (AWGN)
    sig_power = np.mean(np.abs(signal_cfo) ** 2)
    noise_power_db = 10 * np.log10(sig_power) - snr_db
    noise_power_linear = 10 ** (noise_power_db / 10.0)
    
    noise = np.sqrt(noise_power_linear / 2.0) * (
        np.random.normal(0, 1, num_samples) + 1j * np.random.normal(0, 1, num_samples)
    )
    
    return signal_cfo + noise

def test_cfo_estimation():
    sample_rate = 2.048e6
    injected_cfo = 15432.0 # 15.432 kHz
    
    # Use a single tone signal (sine) for phase_diff CFO estimation
    sig = generate_synthetic_signal(
        num_samples=10000,
        sample_rate=sample_rate,
        cfo_hz=injected_cfo,
        snr_db=30.0,
        modulation="sine"
    )
    
    # Estimate CFO
    est_cfo = estimate_cfo_phase_diff(sig, sample_rate)
    
    # We expect high precision for a single tone in high SNR
    # CFO of the tone is injected_cfo + tone_freq (50kHz), so estimated CFO is 65.432 kHz
    expected_cfo = injected_cfo + 50e3
    assert abs(est_cfo - expected_cfo) < 50.0  # within 50 Hz

    # Let's test with QPSK and estimate using M-th power estimator
    sig_qpsk = generate_synthetic_signal(
        num_samples=30000,
        sample_rate=sample_rate,
        cfo_hz=injected_cfo,
        snr_db=40.0,
        modulation="qpsk"
    )
    est_cfo_mth = estimate_cfo_mth_power(sig_qpsk, sample_rate, M=4)
    
    # Should accurately resolve the CFO within a few bins
    assert abs(est_cfo_mth - injected_cfo) < 250.0

def test_iq_imbalance_estimation_and_correction():
    # Inject 1.12 gain imbalance and 4.5 degrees phase imbalance
    injected_g = 1.12
    injected_phi_deg = 4.5
    
    sig = generate_synthetic_signal(
        num_samples=50000, # Large samples for stable expectation values
        cfo_hz=0.0,
        iq_gain=injected_g,
        iq_phase_deg=injected_phi_deg,
        snr_db=40.0,
        modulation="qpsk"
    )
    
    # Estimate imbalance
    est_g, est_phi_deg = estimate_iq_imbalance(sig)
    
    assert abs(est_g - injected_g) < 0.02
    assert abs(est_phi_deg - injected_phi_deg) < 0.5
    
    # Correct imbalance
    corrected_sig = correct_iq_imbalance(sig, est_g, est_phi_deg)
    
    # Estimate imbalance of corrected signal (should be close to ideal: g=1.0, phi=0.0)
    corr_g, corr_phi_deg = estimate_iq_imbalance(corrected_sig)
    
    assert abs(corr_g - 1.0) < 0.01
    assert abs(corr_phi_deg - 0.0) < 0.2

def test_signal_detection_energy():
    sample_rate = 2.048e6
    # Quiet channel noise: standard deviation 0.005 (power 5e-5)
    noise_part1 = (np.random.normal(0, 0.005, 2000) + 1j * np.random.normal(0, 0.005, 2000))
    # Active QPSK signal: standard deviation ~0.7 (power ~0.5)
    signal_part = generate_synthetic_signal(num_samples=4000, snr_db=25.0, modulation="qpsk") * 0.7
    # Quiet noise
    noise_part2 = (np.random.normal(0, 0.005, 4000) + 1j * np.random.normal(0, 0.005, 4000))
    
    combined = np.concatenate([noise_part1, signal_part, noise_part2])
    
    # Set hold time to 0 to prevent delay offset on signal drop
    regions = energy_detector(combined, sample_rate, threshold_db=15.0, window_size=128, hold_time_sec=0.0)
    
    assert len(regions) >= 1
    # Check that first region covers the active signal window (~2000 to ~6000)
    start, end = regions[0]
    assert abs(start - 2000) < 250
    assert abs(end - 6000) < 250

def test_transient_detection_cusum():
    # Quiet channel noise
    noise = (np.random.normal(0, 0.005, 500) + 1j * np.random.normal(0, 0.005, 500))
    # Active signal with ramp-up
    signal_ramp = generate_synthetic_signal(num_samples=1500, snr_db=30.0, modulation="qpsk") * 0.8
    ramp_factor = np.clip(np.arange(1500) / 100.0, 0.0, 1.0)
    signal_ramp = signal_ramp * ramp_factor
    
    combined = np.concatenate([noise, signal_ramp])
    
    # Use higher CUSUM threshold & drift to avoid false-triggering on noise fluctuations
    transient_start = detect_transient_cusum(combined, threshold=15.0, drift=0.3)
    
    # Transient start should be close to 500 (between 450 and 550)
    assert abs(transient_start - 500) < 50

def test_transforms():
    sig = generate_synthetic_signal(num_samples=1024, modulation="qpsk")
    
    # Compute FFT
    freqs, fft_db = compute_fft(sig, n_fft=1024)
    assert len(freqs) == 1024
    assert len(fft_db) == 1024
    assert abs(np.max(fft_db) - 0.0) < 1e-6  # normalized to 0 dB peak
    
    # Compute PSD
    f_psd, psd_db = compute_welch_psd(sig, sample_rate=2e6, nperseg=256, noverlap=128)
    assert len(f_psd) == 256
    assert len(psd_db) == 256
    
    # Compute Spectrogram
    spectrogram = compute_spectrogram(sig, n_fft=256, n_overlap=128)
    assert spectrogram.ndim == 2
    assert spectrogram.shape[0] == 256
    # Output should be normalized in range [0, 1]
    assert np.min(spectrogram) >= 0.0
    assert np.max(spectrogram) <= 1.0

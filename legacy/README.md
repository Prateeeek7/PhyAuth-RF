# Legacy (v1) code — not used

RTL-SDR / IQ-sample code from the first version of the project (SigMF writer,
CFO / IQ-imbalance estimators, FFT helpers, simulated SDR manager) and its tests.
The hardware is an ESP32 + SRX882 pulse-timing receiver, which never produces IQ
samples, so this code path was removed from the platform. It is kept here for
reference only and is excluded from the test run.

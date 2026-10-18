import json
import os
import numpy as np
from pathlib import Path
from datetime import datetime
from common.models import SigMFMetadata, SigMFGlobal, SigMFCapture, SigMFAnnotation

class SigMFWriter:
    """
    Writer for recording RF complex samples compliant with the SigMF v1.0.0 specification.
    Generates a binary file (*.sigmf-data) and a JSON metadata file (*.sigmf-meta).
    """
    
    def __init__(self, 
                 filepath_prefix: Path, 
                 sample_rate: float, 
                 center_frequency: float,
                 datatype: str = "cf32_le",
                 description: str = None,
                 author: str = None,
                 hardware: str = "RTL-SDR",
                 transmitter_id: str = None,
                 distance_meters: float = None,
                 orientation_deg: float = None,
                 session_id: str = None):
        """
        Args:
            filepath_prefix: Absolute or relative Path without extension.
            sample_rate: Sampling rate of the receiver (Hz).
            center_frequency: Local oscillator/center frequency (Hz).
            datatype: Data format, defaults to "cf32_le" (complex float32 little-endian).
        """
        self.prefix = Path(filepath_prefix)
        self.data_path = self.prefix.with_suffix(".sigmf-data")
        self.meta_path = self.prefix.with_suffix(".sigmf-meta")
        self.sample_rate = sample_rate
        self.center_frequency = center_frequency
        self.datatype = datatype
        
        # Ensure parent directory exists
        self.prefix.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize internal structures
        self.global_meta = SigMFGlobal(
            datatype=datatype,
            sample_rate=sample_rate,
            description=description,
            author=author,
            hardware=hardware,
            transmitter_id=transmitter_id,
            distance_meters=distance_meters,
            orientation_deg=orientation_deg,
            session_id=session_id
        )
        
        self.captures = []
        self.annotations = []
        self.sample_count = 0
        
        # Create or truncate the binary file
        with open(self.data_path, "wb") as f:
            pass
            
    def add_capture(self, frequency: float = None, timestamp: datetime = None) -> None:
        """
        Add a capture block indicating the frequency settings at a given sample index.
        """
        freq = frequency if frequency is not None else self.center_frequency
        ts = timestamp if timestamp is not None else datetime.utcnow()
        
        self.captures.append(
            SigMFCapture(
                sample_start=self.sample_count,
                frequency=freq,
                datetime=ts.isoformat() + "Z"
            )
        )
        
    def write_samples(self, samples: np.ndarray) -> None:
        """
        Append complex IQ samples to the binary file and update the sample count.
        
        Args:
            samples: 1D complex numpy array.
        """
        if len(samples) == 0:
            return
            
        # Ensure dtype is complex64 for float32 real/imag parts
        samples_c64 = samples.astype(np.complex64)
        
        # In SigMF, complex float32 little endian (cf32_le) is stored as interleaved I and Q floats
        # [I_0, Q_0, I_1, Q_1, ..., I_N, Q_N]
        # np.complex64 is stored in memory as float32 I followed by float32 Q,
        # which is exactly what we need for direct binary dumping.
        # Ensure little endian representation.
        if np.dtype(np.complex64).byteorder == '>' or (np.dtype(np.complex64).byteorder == '=' and np.sys.byteorder == 'big'):
            # Swap bytes if the host is big endian
            samples_c64 = samples_c64.byteswap()
            
        # Append to binary file
        with open(self.data_path, "ab") as f:
            f.write(samples_c64.tobytes())
            
        self.sample_count += len(samples)
        
    def add_annotation(self, 
                       sample_start: int, 
                       sample_count: int, 
                       label: str,
                       snr_est_db: float = None,
                       cfo_est_hz: float = None,
                       iq_gain_est: float = None,
                       iq_phase_est_deg: float = None) -> None:
        """
        Add an annotation representing metadata for a specific segment of the recording.
        """
        self.annotations.append(
            SigMFAnnotation(
                sample_start=sample_start,
                sample_count=sample_count,
                label=label,
                snr_est_db=snr_est_db,
                cfo_est_hz=cfo_est_hz,
                iq_gain_est=iq_gain_est,
                iq_phase_est_deg=iq_phase_est_deg
            )
        )
        
    def close(self) -> None:
        """
        Write the metadata JSON file. Must be called after all samples are written.
        """
        # If no captures were registered, register one at start
        if not self.captures:
            self.add_capture()
            
        metadata = SigMFMetadata(
            global_meta=self.global_meta,
            captures=self.captures,
            annotations=self.annotations
        )
        
        # SigMF Metadata requires specific key names in JSON (e.g. 'global' instead of 'global_meta')
        # We export with aliases
        meta_dict = json.loads(metadata.json(by_alias=True))
        
        # Clean up global/captures/annotations key naming to match SigMF structure
        # (e.g. Pydantic might serialize by alias, check if correct)
        with open(self.meta_path, "w") as f:
            json.dump(meta_dict, f, indent=4)


class SigMFReader:
    """
    Reader for loading SigMF dataset recordings.
    """
    
    def __init__(self, filepath_prefix: Path):
        self.prefix = Path(filepath_prefix)
        self.data_path = self.prefix.with_suffix(".sigmf-data")
        self.meta_path = self.prefix.with_suffix(".sigmf-meta")
        
        if not self.meta_path.exists():
            raise FileNotFoundError(f"SigMF metadata file {self.meta_path} does not exist.")
        if not self.data_path.exists():
            raise FileNotFoundError(f"SigMF binary data file {self.data_path} does not exist.")
            
        with open(self.meta_path, "r") as f:
            self.meta_dict = json.load(f)
            
        # Parse validation
        self.metadata = SigMFMetadata.parse_obj(self.meta_dict)
        self.sample_rate = self.metadata.global_meta.sample_rate
        self.datatype = self.metadata.global_meta.datatype
        
        if self.datatype != "cf32_le":
            raise ValueError(f"Unsupported SigMF datatype: {self.datatype}. Only 'cf32_le' is supported.")
            
    def read_all_samples(self) -> np.ndarray:
        """
        Read all complex IQ samples from the binary data file.
        """
        # cf32_le contains interleaved float32 values
        # We read them as complex64 directly
        data = np.fromfile(self.data_path, dtype=np.complex64)
        return data
        
    def read_segment(self, start_sample: int, num_samples: int) -> np.ndarray:
        """
        Read a specific segment of complex IQ samples from the file (memory efficient).
        """
        bytes_per_sample = 8  # complex64 is 8 bytes (two float32s)
        offset = start_sample * bytes_per_sample
        
        with open(self.data_path, "rb") as f:
            f.seek(offset)
            raw_bytes = f.read(num_samples * bytes_per_sample)
            
        samples = np.frombuffer(raw_bytes, dtype=np.complex64)
        return samples

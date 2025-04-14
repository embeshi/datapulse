import pandas as pd
from pathlib import Path
from typing import List, Dict, Union
import logging

logger = logging.getLogger(__name__)

def sample_csvs(file_paths: List[Union[str, Path]], num_rows: int = 10) -> Dict[str, str]:
    """Reads headers and sample rows from multiple CSVs."""
    samples = {}
    for file_path in file_paths:
        path = Path(file_path)
        if not path.is_file():
            logger.warning(f"CSV file not found, skipping sampling: {path}")
            samples[path.name] = "Error: File not found."
            continue

        try:
            logger.info(f"Sampling {num_rows} rows from {path.name}...")
            df_sample = pd.read_csv(path, nrows=num_rows)
            header = ",".join(df_sample.columns)
            # Convert sample rows back to CSV-like string format
            sample_data_str = df_sample.to_csv(index=False, header=False, lineterminator='\n').strip()
            samples[path.name] = f"Headers:\n{header}\n\nSample Data:\n{sample_data_str}"
        except Exception as e:
            logger.error(f"Error sampling file {path.name}: {e}")
            samples[path.name] = f"Error: Could not sample file ({e})"
    return samples
